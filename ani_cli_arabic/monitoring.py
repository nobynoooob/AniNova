"""AniNova telemetry engine (upgraded from ani-cli-ar's MonitoringSystem).

Core concept kept from the original:
  * a singleton ``MonitoringSystem``
  * a SHA-256 device fingerprint built from coarse platform info
  * strict opt-in via the ``analytics`` setting (default on, toggle in the
    GUI Privacy menu)
  * JSON events POSTed to ``{endpoint}/monitor`` with an ``X-Auth-Key`` header

Upgrades for AniNova:
  * **Single async worker** — one daemon sender thread owns *all* network I/O.
    Every ``track_*`` call is an O(1) queue push; the caller never touches a
    socket, so telemetry can never block playback, resolving, or the UI.
  * **Batching** — events are drained by the worker and flushed in a single
    POST (``{client, client_version, events: [...]}``) every ``_BATCH_MAX``
    events or ``_FLUSH_INTERVAL`` seconds. If a server rejects the batch shape
    (older deployments), events fall back to the legacy single-event format.
  * **Hard opt-out** — ``set_enabled(False)`` (wired live to the Privacy
    toggle) clears the pending queue and stops+joins the sender thread, so no
    network call is ever made while disabled. Heartbeats run inside the same
    worker and die with it.
  * **AniNova-specific events** — Watch Together rooms (host/guest,
    create/join/leave/end), Discord RPC engagement, theme usage, Auto-Skip
    triggers, and search counts (language only — never the query text).
  * **Privacy** — the legacy ``user_name`` context field is dropped; payloads
    carry only coarse OS/version context.
"""

import atexit
import hashlib
import platform
import queue
import threading
import time
import traceback as _traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .api import _get_analytics_endpoint_config
from .config import CURRENT_VERSION
from .version import __version__

# Sender/worker tuning.
_BATCH_MAX = 20            # flush when the pending batch reaches this size
_FLUSH_INTERVAL = 10.0     # …or when the oldest pending event is this old
_HEARTBEAT_INTERVAL = 30.0 # session heartbeat cadence (worker-side)
_REQUEST_TIMEOUT = 3.0     # per HTTP request (AGENTS.md: strict, non-blocking)
_SENDER_QUEUE_CAP = 500    # queue cap; overflow is dropped, never buffered
_THREAD_JOIN_TIMEOUT = 3.0
_MAX_TRACEBACK_LINES = 6

_SENDER_NAME = "ani-nova-telemetry"


class MonitoringSystem:
    """Thread-safe, opt-in, async-batched analytics engine (singleton).

    All ``track_*`` methods are fire-and-forget: they enrich the event locally
    and push it onto an internal queue. The single sender thread batches and
    POSTs them. Every failure path is swallowed — telemetry never raises and
    never blocks application code.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MonitoringSystem, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.user_fingerprint = self._generate_fingerprint()
        self._enabled = self._read_enabled()
        self._queue: "queue.Queue[Optional[dict]]" = queue.Queue(maxsize=_SENDER_QUEUE_CAP)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._sender_thread: Optional[threading.Thread] = None
        self._pending: List[dict] = []
        self._lock = threading.Lock()
        self._activity_lock = threading.Lock()
        self.current_activity = {
            "status": "idle",
            "current_anime": None,
            "current_episode": None,
            "watch_started_at": None,
        }
        self._session_start: Optional[float] = None
        atexit.register(self.shutdown)
        self._ensure_sender()

    # ------------------------------------------------------------------
    # lifecycle / opt-out
    # ------------------------------------------------------------------
    @staticmethod
    def _read_enabled() -> bool:
        try:
            from .settings import SettingsManager
            return bool(SettingsManager().get("analytics", True))
        except Exception:
            return False

    def set_enabled(self, enabled: bool) -> None:
        """Live opt-in/out from the Privacy settings toggle.

        Disabling hard-stops the sender thread and clears the pending queue, so
        no telemetry HTTP request is ever made while disabled. Enabling starts
        (or restarts) the worker from scratch.
        """
        with self._lock:
            self._enabled = bool(enabled)
        if self._enabled:
            self._ensure_sender()
            self._wake.set()
        else:
            self._stop_sender()
            # Discard anything still queued — zero network afterwards.
            with self._lock:
                self._pending = []
            try:
                while True:
                    self._queue.get_nowait()
            except queue.Empty:
                pass

    def shutdown(self) -> None:
        """Stop the worker and flush any remaining events synchronously.

        Idempotent; registered with ``atexit`` so the tail of a session (e.g.
        ``app_session_end``) is delivered even though the app is about to exit.
        If analytics were disabled, nothing is flushed.
        """
        self._stop.set()
        self._wake.set()
        thread = self._sender_thread
        if thread is not None:
            try:
                thread.join(timeout=_THREAD_JOIN_TIMEOUT)
            except Exception:
                pass
        self._sender_thread = None
        with self._lock:
            pending = list(self._pending)
            self._pending = []
            enabled = self._enabled
        if not enabled:
            return
        while True:
            try:
                pending.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if pending:
            self._send_events(pending)

    def _ensure_sender(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            if self._sender_thread is not None and self._sender_thread.is_alive():
                return
            self._stop.clear()
            self._sender_thread = threading.Thread(
                target=self._sender_loop, daemon=True, name=_SENDER_NAME
            )
            self._sender_thread.start()

    def _stop_sender(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._sender_thread
        if thread is not None:
            try:
                thread.join(timeout=_THREAD_JOIN_TIMEOUT)
            except Exception:
                pass
        with self._lock:
            self._sender_thread = None

    # ------------------------------------------------------------------
    # async worker
    # ------------------------------------------------------------------
    def _sender_loop(self) -> None:
        last_flush = time.time()
        last_heartbeat = time.time()
        while not self._stop.is_set():
            # Drain whatever is queued into the pending batch.
            while True:
                try:
                    ev = self._queue.get_nowait()
                except queue.Empty:
                    break
                if ev is not None:
                    with self._lock:
                        self._pending.append(ev)
            now = time.time()
            with self._lock:
                pending = list(self._pending)
            if pending and (
                len(pending) >= _BATCH_MAX or now - last_flush >= _FLUSH_INTERVAL
            ):
                self._send_events(pending)
                with self._lock:
                    self._pending = self._pending[len(pending):]
                last_flush = time.time()
            if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                self._send_heartbeat()
                last_heartbeat = time.time()
            # Sleep until the next flush/heartbeat deadline or a wake (new
            # event, opt-out, shutdown).
            now = time.time()
            wait = 1.0
            with self._lock:
                if self._pending:
                    wait = min(wait, max(0.0, last_flush + _FLUSH_INTERVAL - now))
                wait = min(wait, max(0.0, last_heartbeat + _HEARTBEAT_INTERVAL - now))
            if wait > 0:
                self._wake.wait(wait)
            self._wake.clear()

    def _enrich(self, details: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(details or {})
        for key, value in self._system_context().items():
            if value is not None and str(value) != "":
                enriched.setdefault(key, value)
        if not enriched.get("translation_mode"):
            enriched["translation_mode"] = self._translation_mode(enriched)
        return enriched

    def _enqueue(self, action: str, details: Dict[str, Any], sync: bool = False) -> None:
        if not self._enabled:
            return
        event = {
            "fingerprint": self.user_fingerprint,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "details": self._enrich(details),
        }
        if sync:
            self._send_events([event])
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            return
        self._wake.set()

    def _send_events(self, events: List[dict]) -> None:
        """POST a batch; fall back to legacy single-event sends if the server
        rejects the batch shape. Never raises."""
        if not events:
            return
        try:
            endpoint_url, auth_secret = _get_analytics_endpoint_config()
            headers = {
                "Content-Type": "application/json",
                "X-Auth-Key": auth_secret,
                "User-Agent": "AniNova-Monitor/1.0",
            }
            batch = {
                "fingerprint": self.user_fingerprint,
                "client": "AniNova",
                "client_version": __version__,
                "events": events,
            }
            resp = requests.post(
                f"{endpoint_url}/monitor", json=batch, headers=headers, timeout=_REQUEST_TIMEOUT
            )
            if resp.status_code in (400, 405, 422):
                # Older server only understands single events.
                for ev in events:
                    requests.post(
                        f"{endpoint_url}/monitor",
                        json=ev,
                        headers=headers,
                        timeout=_REQUEST_TIMEOUT,
                    )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # opt-in guards
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def track_app_start(self) -> None:
        self._enqueue("app_start", {"version": CURRENT_VERSION, "ui": "gui"})

    def track_app_session(self) -> None:
        """Record the session start; ``app_session_end`` is flushed on exit."""
        try:
            self._session_start = time.time()
            atexit.register(self._send_session_end)
        except Exception:
            pass

    def track_video_play(
        self,
        anime_title: str,
        episode: str,
        mode: str = "stream",
        player: str = "",
        provider: str = "",
        quality: str = "",
        ui: str = "gui",
        watch_start: float = None,
        watch_end: float = None,
        resolve_ms: float = None,
    ) -> None:
        details: Dict[str, Any] = {
            "anime": anime_title,
            "episode": episode,
            "mode": mode,
            "player": player or "",
            "provider": provider or "",
            "quality": quality or "",
            "ui": ui or "gui",
        }
        if resolve_ms is not None:
            try:
                details["resolve_ms"] = round(max(float(resolve_ms), 0.0), 1)
            except (TypeError, ValueError):
                pass
        if watch_start is not None and watch_end is not None:
            try:
                start = float(watch_start)
                end = float(watch_end)
                details["watch_start"] = datetime.fromtimestamp(start, timezone.utc).isoformat()
                details["watch_end"] = datetime.fromtimestamp(end, timezone.utc).isoformat()
                details["watch_duration_seconds"] = round(max(end - start, 0.0), 3)
            except (TypeError, ValueError, OverflowError):
                pass
        self._enqueue("video_play", details)

    def track_provider_fallback(
        self, from_provider: str, to_provider: str = "", reason: str = ""
    ) -> None:
        """A provider failed to produce a stream and the chain moved on.

        Feeds v_provider_stats (failure rates) and v_fallbacks. Providers only —
        never URLs or titles."""
        self._enqueue("provider_fallback", {
            "from_provider": str(from_provider or ""),
            "to_provider": str(to_provider or ""),
            "reason": str(reason or "")[:120],
        })

    def track_buffer_stall(
        self, anime: str = "", episode: str = "", stalled_seconds: float = None
    ) -> None:
        """Playback stalled waiting on the network (buffer underrun)."""
        details: Dict[str, Any] = {
            "anime": str(anime or ""),
            "episode": str(episode or ""),
        }
        if stalled_seconds is not None:
            try:
                details["stalled_seconds"] = round(max(float(stalled_seconds), 0.0), 2)
            except (TypeError, ValueError):
                pass
        self._enqueue("buffer_stall", details)

    def track_sync_error(
        self, role: str, drift_seconds: float = None, corrected: bool = True
    ) -> None:
        """Watch Together sync correction (drift exceeded the hard-seek band).

        Coarse timing only — no room codes or member identities."""
        details: Dict[str, Any] = {
            "role": str(role or "guest"),
            "corrected": bool(corrected),
        }
        if drift_seconds is not None:
            try:
                details["drift_seconds"] = round(float(drift_seconds), 3)
            except (TypeError, ValueError):
                pass
        self._enqueue("sync_error", details)

    def track_watch_together(
        self, role: str, event: str, members: int = 1, duration_s: float = None
    ) -> None:
        """Watch Together engagement. ``role`` is host|guest, ``event`` one of
        create|join|leave|end. Only member counts are sent — never room codes.
        ``duration_s`` (optional) carries the room session length on leave/end."""
        details: Dict[str, Any] = {
            "role": str(role or "guest"),
            "event": str(event or ""),
            "members": max(1, int(members or 1)),
        }
        if duration_s is not None:
            try:
                details["duration_s"] = round(max(float(duration_s), 0.0), 1)
            except (TypeError, ValueError):
                pass
        self._enqueue("room_event", details)

    def track_rpc(self, action: str, mode: str = "") -> None:
        """Coarse Discord Rich Presence engagement (enable/disable/connect).
        ``mode`` is an optional coarse presence state; no codes or titles."""
        details: Dict[str, Any] = {"action": str(action or "")}
        if mode:
            details["mode"] = str(mode)
        self._enqueue("rpc_event", details)

    def track_theme(self, theme: str) -> None:
        self._enqueue("theme_event", {"theme": str(theme or "")})

    def track_skip(
        self,
        kind: str,
        action: str = "skipped",
        accurate: bool = None,
        delay_seconds: float = None,
    ) -> None:
        """Auto-Skip engagement — OP/ED (or recap) skip actually performed.

        ``accurate`` reports whether the skip executed as intended;
        ``delay_seconds`` is how long after the window opened the skip fired
        (poll cadence) — together they give the server-side accuracy metrics."""
        details: Dict[str, Any] = {"kind": str(kind or ""), "action": str(action or "")}
        if accurate is not None:
            details["accurate"] = bool(accurate)
        if delay_seconds is not None:
            try:
                details["delay_seconds"] = round(max(float(delay_seconds), 0.0), 2)
            except (TypeError, ValueError):
                pass
        self._enqueue("skip_event", details)

    def track_search(self, language: str = "english") -> None:
        """Search counts by catalog language. The query text is intentionally
        never transmitted."""
        self._enqueue("search_event", {"language": str(language or "english")})

    def set_activity(self, status: str, anime: str = None, episode=None) -> None:
        """Update the global current-activity state used by heartbeats.

        status is "watching" or "idle". While watching, anime/episode are the
        currently playing title and its episode identifier.
        """
        status = (status or "idle").lower()
        if status not in ("idle", "watching"):
            status = "idle"
        with self._activity_lock:
            self.current_activity["status"] = status
            if status == "watching":
                self.current_activity["current_anime"] = anime
                self.current_activity["current_episode"] = episode
                self.current_activity["watch_started_at"] = time.time()
            else:
                self.current_activity["current_anime"] = None
                self.current_activity["current_episode"] = None
                self.current_activity["watch_started_at"] = None

    def _send_heartbeat(self) -> None:
        with self._activity_lock:
            activity = dict(self.current_activity)
        start = self._session_start or time.time()
        details = {
            "session_start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "elapsed_session_seconds": round(time.time() - start, 3),
            "status": activity.get("status", "idle"),
            "current_anime": activity.get("current_anime"),
            "current_episode": activity.get("current_episode"),
        }
        watch_started = activity.get("watch_started_at")
        if watch_started:
            details["watch_started_at"] = datetime.fromtimestamp(
                watch_started, timezone.utc
            ).isoformat()
        self._enqueue("heartbeat", details)

    def _send_session_end(self) -> None:
        try:
            end = time.time()
            start = getattr(self, "_session_start", None) or end
            self._enqueue(
                "app_session_end",
                {
                    "session_start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                    "session_end": datetime.fromtimestamp(end, timezone.utc).isoformat(),
                    "session_duration_seconds": round(end - start, 3),
                },
                sync=True,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # diagnostics
    # ------------------------------------------------------------------
    def track_error(
        self,
        error_msg: str = "",
        context: dict = None,
        exception: BaseException = None,
        exc_info: tuple = None,
    ) -> None:
        """Report a diagnostic error event.

        All extraction is local and cheap; the network send happens on the
        background worker and fails silently when offline.
        """
        details: Dict[str, Any] = {}

        exc_type = exc_val = exc_tb = None
        if exception is not None:
            exc_type = type(exception)
            exc_val = exception
            if getattr(exception, "__traceback__", None) is not None:
                exc_tb = exception.__traceback__
        elif exc_info is not None and isinstance(exc_info, tuple) and exc_info[0] is not None:
            exc_type, exc_val, exc_tb = exc_info

        if exc_type is not None:
            details["exception_type"] = getattr(exc_type, "__name__", str(exc_type))
            details["error_msg"] = error_msg or str(exc_val) or ""
            if exc_tb is not None:
                try:
                    formatted = _traceback.format_exception(exc_type, exc_val, exc_tb)
                except Exception:
                    formatted = None
                if formatted:
                    details["traceback"] = self._truncate_traceback(formatted)
        else:
            details["error_msg"] = error_msg or ""

        if isinstance(context, dict):
            for key, value in context.items():
                if value is not None and str(value) != "":
                    details[key] = value

        if exc_val is not None:
            if details.get("http_status") is None:
                status = getattr(exc_val, "status_code", None)
                if status is None and getattr(exc_val, "response", None) is not None:
                    status = exc_val.response.status_code
                if status:
                    details["http_status"] = int(status)

            if not details.get("server_url") and not details.get("stream_url"):
                url = getattr(exc_val, "url", None)
                if url is None and getattr(exc_val, "request", None) is not None:
                    url = exc_val.request.url
                if url:
                    details["server_url"] = self._host_of(url)

        if not details.get("translation_mode"):
            details["translation_mode"] = self._translation_mode(details)

        self._enqueue("error", details)

    def fetch_stats(self, limit: int = 500) -> Optional[dict]:
        """Fetch aggregated streaming history from the remote telemetry endpoint.

        Returns None if analytics are disabled, the endpoint is unreachable, or
        no playback data is available for this device.
        """
        try:
            from .settings import SettingsManager
            if not SettingsManager().get("analytics"):
                return None
        except Exception:
            return None

        try:
            endpoint_url, auth_secret = _get_analytics_endpoint_config()
            headers = {
                "X-Auth-Key": auth_secret,
                "User-Agent": "AniNova-Monitor/1.0",
            }
            resp = requests.get(
                f"{endpoint_url}/stats",
                params={"fingerprint": self.user_fingerprint, "limit": limit},
                headers=headers,
                timeout=8,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _generate_fingerprint() -> str:
        try:
            components = [
                platform.node(),
                platform.machine(),
                platform.system(),
                platform.release(),
                platform.processor(),
            ]
            raw_str = "|".join(str(c) for c in components)
            return hashlib.sha256(raw_str.encode()).hexdigest()[:16]
        except Exception:
            return "unknown_user"

    @staticmethod
    def _system_context() -> dict:
        """Coarse, non-identifying context attached to every event."""
        return {
            "os": f"{platform.system()} {platform.release()}",
            "app_version": __version__,
        }

    @staticmethod
    def _translation_mode(details: dict) -> str:
        """Map user settings/CLI language preference to a canonical mode."""
        mode = details.get("translation_mode") or details.get("sub_type")
        if mode:
            return str(mode)
        try:
            from .settings import SettingsManager
            lang = str(SettingsManager().get("preferred_language", "Arabic Sub"))
            mapping = {
                "Arabic Sub": "arabic_sub",
                "English Sub": "sub",
                "English Dub": "dub",
            }
            for key, value in mapping.items():
                if key.lower() in lang.lower():
                    return value
        except Exception:
            pass
        return "sub"

    @staticmethod
    def _host_of(url) -> str:
        try:
            from urllib.parse import urlsplit
            return urlsplit(str(url)).hostname or str(url)
        except Exception:
            return str(url)

    @staticmethod
    def _truncate_traceback(formatted) -> str:
        try:
            joined = "".join(formatted).rstrip()
        except Exception:
            return str(formatted)
        lines = joined.splitlines()
        if len(lines) > _MAX_TRACEBACK_LINES:
            return "\n".join(lines[-_MAX_TRACEBACK_LINES:])
        return joined


# Global instance
monitor = MonitoringSystem()