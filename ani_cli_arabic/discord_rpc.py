"""Discord Rich Presence engine for AniNova.

Fully non-blocking: every public method only mutates a small shared state
dict under a lock and wakes a single background daemon thread (the "keeper").
All Discord IPC socket I/O — connect, presence updates, reconnects, clear,
close — happens exclusively on that thread, so the GUI, the player IPC and the
Watch Together sync loop are never touched by RPC work.

Resilience
----------
* Discord not running / the IPC pipe missing simply makes ``connect()`` fail;
  the keeper silently retries on a slow backoff (``CONNECT_RETRY_DELAY``) with
  zero log output.
* A dropped pipe mid-session is detected on the next send and the client is
  torn down; the keeper reconnects on the next cycle and resumes presence.
* ``pypresence`` is optional. When it is not installed the module degrades to
  a no-op singleton (``DISCORD_RPC_AVAILABLE == False``) and every call is a
  cheap, safe no-op.

Presence states
---------------
* **idle**   — "Browsing Anime" / "Exploring AniNova" (startup, after playback).
* **search** — "Searching for anime" while the user queries the catalog.
* **playback** — WATCHING activity with the anime title, episode, and a
  Discord-side live elapsed/remaining timer derived from the mpv position
  (``start = now - position``), which Discord counts up continuously server
  side. Pause clears the timer and prefixes "Paused ·".
* **room**   — Watch Together: "Hosting a Watch Together Room" / "Watching
  with friends", plus a party ``party_id``/``party_size`` derived from the
  room code and member count.

The keeper re-sends presence only when the rendered payload changes or a
keepalive interval (``KEEPALIVE_INTERVAL``) elapses, so it never spams the
Discord IPC pipe while the live timer is already being counted by Discord.
"""

import threading
import time
from typing import Any, Dict, Optional

try:
    from pypresence import Presence, PipeClosed
    try:
        from pypresence import ActivityType
    except ImportError:  # pragma: no cover - very old pypresence
        class ActivityType:
            PLAYING = 0
            STREAMING = 1
            LISTENING = 2
            WATCHING = 3
            CUSTOM = 4
            COMPETING = 5
    DISCORD_RPC_AVAILABLE = True
except ImportError:  # pragma: no cover - pypresence not installed
    DISCORD_RPC_AVAILABLE = False
    Presence = None
    PipeClosed = Exception
    ActivityType = None

from .version import APP_VERSION

# ─────────────────────────────────────────────────────────────────────────────
# DISCORD APPLICATION IDENTITY
#
# The **bold top-level name** Discord shows next to the Rich Presence is the
# *application name* registered for this Client ID in the Discord Developer
# Portal (https://discord.com/developers/applications). This ID belongs to the
# official "AniNova" application, so Discord renders the AniNova name.
#
# NOTE: pypresence reads this ID over the local Discord IPC pipe; the ID never
# leaves the machine. The Client ID also serves as a "secret" to NOBODY — it is
# public by design (every Discord app ships it in its client bundle).
# ─────────────────────────────────────────────────────────────────────────────
DISCORD_CLIENT_ID = "1539513639390675035"

# Large/small presence image shown next to the activity. Must be a public
# http(s) URL — upload your own AniNova logo (e.g. to https://postimg.cc) and
# paste the direct image link here. Small-text/branding always reads "AniNova".
DISCORD_LOGO_URL = "https://i.postimg.cc/DydJfKY3/logo.gif"
DISCORD_LOGO_TEXT = f"AniNova {APP_VERSION}"

# Presence destination for the action button (Discord requires an https URL).
GITHUB_URL = "https://github.com/nobynoooob/AniNova"

# Watch Together room party size cap (matches watch_together.MAX_MEMBERS).
MAX_PARTY = 8

# --- Keeper timing ----------------------------------------------------------
STATE_POLL_INTERVAL = 3.0       # keeper wake cadence (reaction to state changes)
KEEPALIVE_INTERVAL = 45.0       # re-send presence at least this often
CONNECT_RETRY_DELAY = 20.0      # silent retry when Discord isn't running

# --- Presence modes ----------------------------------------------------------
_MODE_IDLE = "idle"
_MODE_SEARCH = "search"
_MODE_PLAYBACK = "playback"
_MODE_ROOM = "room"

# Discord field limits (details/state 128, large/small text 128, button label 32).
_MAX_LINE = 120
_MAX_BUTTON_LABEL = 28


def _clamp(text: Any, limit: int = _MAX_LINE) -> str:
    """Coerce to a short single-line string for Discord presence fields."""
    try:
        s = " ".join(str(text or "").split())
    except Exception:
        s = ""
    if not s:
        s = "Anime"
    if len(s) > limit:
        return s[: limit - 1].rstrip() + "…"
    return s


def _fmt_ts(seconds: Optional[float]) -> str:
    """Format a playback position as ``MM:SS`` (or ``H:MM:SS`` past an hour)."""
    try:
        total = max(0.0, float(seconds))
    except (TypeError, ValueError):
        total = 0.0
    total = int(total)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class DiscordPresence:
    """Thread-safe Discord Rich Presence manager (single shared instance)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._wake = threading.Event()
        self._rpc: Any = None
        self._enabled = False
        self._mode = _MODE_IDLE
        self._fields: Dict[str, Any] = {}
        self._last_key: Optional[str] = None
        self._last_send: float = 0.0
        self._force_send = False
        # Privacy setting: whether the Watch Together room code may be shown on
        # Discord. Mirrors the ``show_rpc_room_code`` setting (default True),
        # read once at startup and kept live via ``set_room_code_visible``.
        self._show_room_code = self._read_room_code_setting()

    @staticmethod
    def _read_room_code_setting() -> bool:
        try:
            from .config import SHOW_RPC_ROOM_CODE_DEFAULT
            from .settings import SettingsManager
            return bool(SettingsManager().get("show_rpc_room_code", SHOW_RPC_ROOM_CODE_DEFAULT))
        except Exception:
            return True

    # ------------------------------------------------------------------
    # public API (never blocks; only mutates state + wakes the keeper)
    # ------------------------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable presence from the Settings toggle.

        Disabling immediately tears the RPC client down (clearing the user's
        presence) on the keeper thread; enabling restarts from the idle state.
        """
        with self._lock:
            self._enabled = bool(enabled)
            self._mode = _MODE_IDLE
            self._fields = {}
        self._ensure_thread()
        self._wake.set()

    def set_idle(self) -> None:
        """Show the browsing presence ("Browsing Anime" / "Exploring AniNova")."""
        with self._lock:
            self._mode = _MODE_IDLE
            self._fields = {}
        self._wake.set()

    def set_browsing(self, mode: str = "browse") -> None:
        """Idle presence with a refined state for specific sections.

        ``mode="search"`` renders "Searching for anime"; anything else renders
        the plain browsing presence. No-op when presence is disabled."""
        with self._lock:
            self._mode = _MODE_SEARCH if mode == "search" else _MODE_IDLE
            self._fields = {}
        self._wake.set()

    def set_playback(
        self,
        title: str,
        episode,
        playing: bool = True,
        position: Optional[float] = None,
        duration: Optional[float] = None,
        poster: Optional[str] = None,
        room: Optional[str] = None,
        code: Optional[str] = None,
        members: Optional[int] = None,
    ) -> None:
        """Watching presence for an active episode.

        ``position`` is the mpv ``time-pos``; while playing it seeds a Discord
        elapsed timer (``start = now - position``) that Discord counts up live,
        so the counter stays accurate without constant re-sends. ``room``/``code``
        overlay a Watch Together party ("Hosting"/"In Room <code>") and a live
        ``party_size`` when a room is active."""
        with self._lock:
            self._mode = _MODE_PLAYBACK
            self._fields = {
                "title": _clamp(title),
                "episode": _clamp(str(episode or "") if episode is not None else "", 32),
                "playing": bool(playing),
                "position": float(position) if position is not None else None,
                "duration": float(duration) if duration is not None else None,
                "poster": poster,
                "room": room,
                "code": str(code or ""),
                "members": int(members or 1),
            }
        self._wake.set()

    def set_room(self, role: str, code: str, members: int = 1) -> None:
        """Watch Together presence ("Hosting…"/"Watching with friends").

        Refreshing with the current member count keeps ``party_size`` live as
        people join and leave the room."""
        with self._lock:
            self._mode = _MODE_ROOM
            self._fields = {
                "role": str(role or "guest"),
                "code": str(code or ""),
                "members": int(members or 1),
            }
        self._wake.set()

    def clear_room(self) -> None:
        """Drop the Watch Together overlay.

        A room-only presence returns to browsing; a playback presence simply
        loses its room line and party."""
        with self._lock:
            if self._mode == _MODE_ROOM:
                self._mode = _MODE_IDLE
                self._fields = {}
            elif self._mode == _MODE_PLAYBACK:
                for key in ("room", "code", "members"):
                    self._fields.pop(key, None)
        self._wake.set()

    def set_room_code_visible(self, visible: bool) -> None:
        """Privacy toggle: whether the Watch Together room code appears on
        Discord (state line + ``party_id``). Flipping it re-renders the active
        presence immediately; hidden codes show "In a Watch Together Room"."""
        with self._lock:
            self._show_room_code = bool(visible)
        self._wake.set()

    def shutdown(self) -> None:
        """Stop the keeper and clear/close the RPC client (GUI exit)."""
        self._running = False
        self._wake.set()
        thread = self._thread
        if thread is not None:
            try:
                thread.join(timeout=3.0)
            except Exception:
                pass
        self._teardown_rpc()
        self._thread = None

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def connected(self) -> bool:
        return self._rpc is not None

    def status(self) -> Dict[str, Any]:
        """Current engine state for status bars / diagnostics."""
        with self._lock:
            return {
                "available": bool(DISCORD_RPC_AVAILABLE),
                "enabled": self._enabled,
                "connected": self._rpc is not None,
                "mode": self._mode,
                "show_room_code": self._show_room_code,
                "fields": dict(self._fields),
            }

    # ------------------------------------------------------------------
    # keeper thread
    # ------------------------------------------------------------------
    def _ensure_thread(self) -> None:
        if not DISCORD_RPC_AVAILABLE:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="discord-presence"
            )
            self._thread.start()

    def _loop(self) -> None:
        while self._running:
            if not self._enabled:
                # Toggle off (or never on): make sure nothing is left on the
                # user's profile, then sleep until the next event.
                self._teardown_rpc()
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            if self._rpc is None:
                if not self._connect():
                    self._wake.wait(CONNECT_RETRY_DELAY)
                    self._wake.clear()
                    continue
            try:
                self._send_if_needed()
            except PipeClosed:
                self._teardown_rpc()
            except Exception:
                self._teardown_rpc()
            self._wake.wait(STATE_POLL_INTERVAL)
            self._wake.clear()

    def _connect(self) -> bool:
        """Create a fresh pypresence client and handshake with Discord.

        A fresh instance per attempt avoids reusing a half-open pipe. Any
        failure (Discord closed, pipe missing) is swallowed — the caller
        applies the silent backoff."""
        if not DISCORD_RPC_AVAILABLE:
            return False
        try:
            rpc = Presence(DISCORD_CLIENT_ID)
            rpc.connect()
            self._rpc = rpc
            self._last_key = None
            self._last_send = 0.0
            self._force_send = True
            return True
        except Exception:
            self._rpc = None
            return False

    def _teardown_rpc(self) -> None:
        """Clear the activity and close the pipe (best-effort, never raises)."""
        rpc = self._rpc
        self._rpc = None
        self._last_key = None
        self._last_send = 0.0
        if rpc is None:
            return
        try:
            rpc.clear()
        except Exception:
            pass
        try:
            rpc.close()
        except Exception:
            pass

    def _send_if_needed(self) -> None:
        """Render the current presence and push it when it changed (or on
        keepalive). ``start`` is excluded from the change key: the elapsed
        timer is counted live by Discord, so we only re-seed it on state
        changes and keepalives, never on the 3s poll."""
        payload = self._build_payload()
        key = self._stable_key(payload)
        now = time.time()
        with self._lock:
            changed = (key != self._last_key) or (now - self._last_send > KEEPALIVE_INTERVAL) or self._force_send
        if not changed:
            return
        self._rpc.update(**payload)
        self._last_key = key
        self._last_send = time.time()
        self._force_send = False

    @staticmethod
    def _stable_key(payload: Dict[str, Any]) -> str:
        """Change key that ignores the live ``start`` timestamp."""
        fields = {k: v for k, v in payload.items() if k != "start"}
        try:
            return repr(sorted(fields.items(), key=lambda kv: str(kv[0])))
        except Exception:
            return repr(fields)

    # ------------------------------------------------------------------
    # payload rendering
    # ------------------------------------------------------------------
    def _build_payload(self) -> Dict[str, Any]:
        with self._lock:
            mode = self._mode
            fields = dict(self._fields)
            show_code = self._show_room_code

        common = {
            "small_image": DISCORD_LOGO_URL,
            "buttons": _BUTTONS,
            "activity_type": ActivityType.PLAYING if ActivityType is not None else 0,
        }

        if mode == _MODE_PLAYBACK:
            return self._playback_payload(fields, common, show_code)
        if mode == _MODE_ROOM:
            return self._room_payload(fields, common, show_code)
        if mode == _MODE_SEARCH:
            return {
                **common,
                "details": "Searching for anime",
                "state": "Exploring AniNova",
                "small_text": "Browsing AniNova",
                "large_image": DISCORD_LOGO_URL,
                "large_text": DISCORD_LOGO_TEXT,
            }
        return {
            **common,
            "details": "Browsing Anime",
            "state": "Exploring AniNova",
            "small_text": "Browsing AniNova",
            "large_image": DISCORD_LOGO_URL,
            "large_text": DISCORD_LOGO_TEXT,
        }

    def _playback_payload(self, fields: Dict[str, Any], common: Dict[str, Any], show_code: bool) -> Dict[str, Any]:
        title = fields.get("title") or "Anime"
        episode = fields.get("episode") or ""
        playing = bool(fields.get("playing"))
        position = fields.get("position")
        poster = fields.get("poster")
        room = fields.get("room")
        code = fields.get("code")
        members = int(fields.get("members") or 1)

        state_line = f"Episode {episode}" if episode else "Now Playing"
        small_text = DISCORD_LOGO_TEXT
        if room:
            prefix = "Hosting" if str(room) == "host" else "In"
            state_line = f"{state_line}  ·  {prefix} {self._room_label(code, members, show_code)}"
            small_text = self._room_tooltip(str(room), members)
        elif not playing:
            state_line = f"Paused · {state_line}"
            small_text = f"Paused at {_fmt_ts(position)}"

        payload = {
            **common,
            "activity_type": ActivityType.WATCHING if ActivityType is not None else 3,
            "details": _clamp(title),
            "state": _clamp(state_line),
            "small_text": _clamp(small_text),
            "large_image": self._image(poster),
            "large_text": _clamp(title),
        }
        if playing and position is not None:
            try:
                payload["start"] = int(time.time() - float(position))
            except (TypeError, ValueError):
                pass
        if room:
            payload["party_size"] = [members, MAX_PARTY]
            if show_code and code:
                payload["party_id"] = "wt-" + str(code)
        return payload

    def _room_payload(self, fields: Dict[str, Any], common: Dict[str, Any], show_code: bool) -> Dict[str, Any]:
        role = str(fields.get("role") or "guest")
        code = fields.get("code") or ""
        members = int(fields.get("members") or 1)
        details = (
            "Hosting a Watch Together Room" if role == "host"
            else "Watching with friends"
        )
        payload = {
            **common,
            "details": details,
            "state": _clamp(self._room_label(code, members, show_code, full=True)),
            "small_text": _clamp(self._room_tooltip(role, members)),
            "large_image": DISCORD_LOGO_URL,
            "large_text": "AniNova Watch Together",
            "party_size": [members, MAX_PARTY],
        }
        if show_code and code:
            payload["party_id"] = "wt-" + str(code)
        return payload

    @staticmethod
    def _room_label(code: str, members: int, show_code: bool, full: bool = False) -> str:
        """Room line rendered in the presence state.

        ``show_code`` ON renders "Room #CODE", OFF masks the code. ``full``
        (room-only presence) appends the party count "(X/MAX)". The non-full
        variant is appended after "Hosting"/"In" in the playback line, so the
        hidden form returns "a Watch Together Room" → "Hosting a Watch
        Together Room" / "In a Watch Together Room"."""
        if show_code and code:
            label = f"Room #{code}"
        elif full:
            label = "In a Watch Together Room"
        else:
            label = "a Watch Together Room"
        if full:
            label = f"{label} ({members}/{MAX_PARTY})"
        return label

    @staticmethod
    def _room_tooltip(role: str, members: int) -> str:
        """Dynamic small-image tooltip for Watch Together contexts."""
        if str(role) == "host":
            count = max(1, int(members))
            return f"Host ({count} member{'s' if count != 1 else ''})"
        return "Guest in Room"

    def _image(self, poster: Optional[str]) -> str:
        """Return a valid presence image. External http(s) poster URLs are
        passed straight through; anything unusable falls back to the logo."""
        if poster and str(poster).startswith(("http://", "https://")):
            return str(poster)
        return DISCORD_LOGO_URL


# Single interactive button shown in every presence state, pointing at the
# AniNova GitHub repository/releases page.
_BUTTONS = [{"label": "AniNova on GitHub", "url": GITHUB_URL}]


# Shared singleton so GUI wiring can ``from .discord_rpc import presence``.
presence = DiscordPresence()