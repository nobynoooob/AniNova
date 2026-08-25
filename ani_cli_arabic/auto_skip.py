"""Automated Skip-Intro/Outro Detection for AniNova playback.

Fetch opening/ending theme timestamps from the community AniSkip database and
automatically seek past them while the episode plays, keeping the binge
experience uninterrupted. Playback is monitored through the same mpv IPC
transport used everywhere else in the app (never a GUI-thread call).

Components:
* ``fetch_skip_times()``       — AniSkip v2 API client (strict 5s timeout,
                                 silent failure -> empty list).
* ``SkipCache``                — bounded, thread-safe in-memory cache keyed by
                                 ``(anilist_id, episode)`` so a session never
                                 refetches the same episode.
* ``prefetch_skip_times()``    — background (daemon-thread) fetch so playback
                                 starts with zero added latency.
* ``AutoSkipMonitor``          — daemon thread that polls mpv ``time-pos`` and
                                 seeks past OP/ED boundaries the moment the
                                 playback head crosses into them, with an OSD
                                 flash and an optional callback (used by Watch
                                 Together hosts to broadcast the skip to every
                                 guest in sync).

Nothing in this module ever blocks the UI thread: HTTP uses a hard 5s timeout
and every loop lives on a daemon thread. Best-effort throughout — any failure
degrades to "no skipping" silently.
"""

import dataclasses
import threading
import time
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

from .watch_together import MpvIpcClient

# AniSkip API (community-maintained OP/ED/recap timestamps, keyed by AniList id).
ANISKIP_BASE = "https://api.aniskip.com/v2/skip-times"
SKIP_TYPES = ("op", "ed")
_SKIP_LABELS = {"op": "Opening", "ed": "Ending"}

# Hard timeout for the skip-times HTTP call (AGENTS.md: strict 5.0s).
FETCH_TIMEOUT = 5.0
# How long after the interval start the head may still trigger a skip. Covers
# the poll cadence so a slow poll cycle can't miss the boundary entirely.
TRIGGER_WINDOW = 1.5
# mpv poll cadence (cheap local IPC round-trip, on a daemon thread).
POLL_INTERVAL = 0.5
# While the player is paused the monitor stops polling time-pos entirely and
# only checks the pause flag at this relaxed cadence (it must not contend with
# the Watch Host sync loop over mpv's single-threaded IPC command queue).
PAUSED_POLL_INTERVAL = 1.5
# Seconds after a triggered skip during which no further skip may fire. A hard
# seek ("set_property time-pos") can report the pre-seek position briefly;
# this cooldown prevents a double seek / double EV_SEEK broadcast.
SKIP_COOLDOWN = 2.0
# How old a Watch Host state snapshot may be before it is treated as stale
# (room gone, player exited) and the monitor starts counting dead polls.
SOURCE_STALE = 5.0
# Number of consecutive failed polls (player gone) before the monitor exits.
_MAX_DEAD_POLLS = 6

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://aniskip.com/",
}


@dataclasses.dataclass
class SkipInterval:
    """A single OP/ED window, in seconds, for one episode."""

    skip_type: str  # "op" | "ed"
    start: float
    end: float

    @property
    def label(self) -> str:
        return _SKIP_LABELS.get(self.skip_type, self.skip_type.title())

    def is_valid(self) -> bool:
        return self.end > self.start >= 0


def fetch_skip_times(
    anilist_id,
    episode,
    timeout: float = FETCH_TIMEOUT,
) -> List[SkipInterval]:
    """Query AniSkip for OP/ED timestamps. Never raises; returns [] on any
    failure, on missing data (``found: false``) and for invalid ids."""
    try:
        aid = int(anilist_id)
        ep = int(episode)
    except (TypeError, ValueError):
        return []
    if aid <= 0 or ep <= 0:
        return []
    import httpx

    query = "&".join(f"types[]={t}" for t in SKIP_TYPES)
    url = f"{ANISKIP_BASE}/{aid}/{ep}?{query}&episodeLength=0"
    try:
        resp = httpx.get(url, timeout=timeout, headers=_BROWSER_HEADERS)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []
    if not isinstance(data, dict) or not data.get("found"):
        return []
    intervals: List[SkipInterval] = []
    for result in data.get("results") or []:
        if not isinstance(result, dict):
            continue
        interval = result.get("interval") or {}
        try:
            it = SkipInterval(
                skip_type=str(result.get("skipType") or ""),
                start=float(interval.get("startTime")),
                end=float(interval.get("endTime")),
            )
        except (TypeError, ValueError):
            continue
        if it.skip_type in SKIP_TYPES and it.is_valid():
            intervals.append(it)
    return intervals


class SkipCache:
    """Bounded, thread-safe in-memory store of fetched skip intervals."""

    MAX_ENTRIES = 256

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._max = max(max_entries, 1)
        self._data: "OrderedDict[Tuple[str, int], List[SkipInterval]]" = OrderedDict()
        self._lock = threading.Lock()

    def _key(self, anilist_id, episode) -> Optional[Tuple[str, int]]:
        try:
            return str(anilist_id), int(episode)
        except (TypeError, ValueError):
            return None

    def get(self, anilist_id, episode) -> List[SkipInterval]:
        key = self._key(anilist_id, episode)
        if key is None:
            return []
        with self._lock:
            intervals = self._data.get(key)
            if intervals is not None:
                self._data.move_to_end(key)
            return list(intervals or [])

    def put(self, anilist_id, episode, intervals: List[SkipInterval]) -> None:
        key = self._key(anilist_id, episode)
        if key is None:
            return
        with self._lock:
            self._data[key] = list(intervals)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


_cache = SkipCache()


def get_skip_times(anilist_id, episode) -> List[SkipInterval]:
    """Thread-safe lookup of cached skip intervals for ``(anilist_id, episode)``.

    Returns ``[]`` when the episode is unknown or still being fetched (the
    AutoSkipMonitor resolves lazily, so a later fetch still lands mid-play)."""
    return _cache.get(anilist_id, episode)


def prefetch_skip_times(anilist_id, episode) -> None:
    """Fetch skip times for an episode on a background daemon thread.

    Called at play time so the data is usually ready long before the OP
    starts (and never adds launch latency). Idempotent: a cached value skips
    the network call entirely."""
    try:
        aid = int(anilist_id)
        ep = int(episode)
    except (TypeError, ValueError):
        return
    if aid <= 0 or ep <= 0:
        return
    if _cache.get(aid, ep):
        return

    def _fetch():
        intervals = fetch_skip_times(aid, ep)
        if intervals:
            _cache.put(aid, ep, intervals)

    threading.Thread(target=_fetch, daemon=True, name="auto-skip-prefetch").start()


class AutoSkipMonitor:
    """Daemon thread that watches mpv playback and skips OP/ED windows.

    ``ipc`` is either an ``MpvIpcClient`` (shared, not closed on stop) or a
    socket path/address string (a dedicated client is created and owned). Skip
    intervals come lazily from ``resolver`` (typically the shared ``SkipCache``)
    so a background fetch that lands mid-playback is picked up automatically.
    ``on_skip(target, label)`` is invoked right after the seek — Watch Together
    hosts use it to broadcast the new time so every guest skips in sync.

    Two observation modes, to avoid fighting the Watch Host over mpv's
    single-threaded IPC command queue:

    * **Passive** (``state_source`` given, e.g. ``WatchHost.poll_state``): mpv
      state is read from the source the host sync loop already maintains. The
      monitor never issues get_property requests of its own and only uses the
      IPC connection for the rare seek / OSD commands.
    * **Active** (default, no ``state_source``): the monitor polls its own
      client, but suspends time-pos polling entirely while the player is
      paused (it only checks the pause flag at a relaxed cadence).

    While paused, no skip can ever fire.
    """

    def __init__(
        self,
        ipc,
        resolver: Optional[Callable[[], List[SkipInterval]]] = None,
        on_skip: Optional[Callable[[float, str], None]] = None,
        osd: bool = True,
        state_source: Optional[Callable[[], Optional[Tuple]]] = None,
    ):
        self._owns_ipc = not isinstance(ipc, MpvIpcClient)
        self._ipc = ipc
        self._resolver = resolver
        self._on_skip = on_skip
        self._osd_enabled = bool(osd)
        self._state_source = state_source
        self._intervals: List[SkipInterval] = []
        self._triggered: Dict[str, bool] = {}
        self._skip_cooldown: float = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.skipped: List[dict] = []

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        if isinstance(self._ipc, str):
            self._ipc = MpvIpcClient(self._ipc)
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="auto-skip-monitor"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the monitor thread to finish (best-effort)."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _load_intervals(self) -> None:
        if not self._intervals and self._resolver is not None:
            try:
                self._intervals = [i for i in (self._resolver() or []) if i.is_valid()]
                self._triggered = {i.skip_type: False for i in self._intervals}
            except Exception:
                pass

    def _trigger(self, interval: SkipInterval, pos: Optional[float] = None) -> None:
        try:
            self._ipc.seek(interval.end)
        except Exception:
            return
        self._triggered[interval.skip_type] = True
        self._skip_cooldown = time.time()
        self.skipped.append(
            {
                "type": interval.skip_type,
                "label": interval.label,
                "start": interval.start,
                "end": interval.end,
                "time": time.time(),
            }
        )
        if self._osd_enabled:
            try:
                show = getattr(self._ipc, "show_text", None)
                if show is not None:
                    show(f"Skipped {interval.label}", 2000)
            except Exception:
                pass
        cb = self._on_skip
        if cb is not None:
            try:
                cb(interval.end, interval.skip_type)
            except Exception:
                pass
        # Telemetry: an Auto-Skip actually fired (op/ed/recap) — fire on the
        # async analytics worker, never here. ``delay_seconds`` (position minus
        # window start at fire time) is the accuracy/latency signal.
        try:
            from .monitoring import monitor
            delay = None
            if pos is not None and interval.end > interval.start:
                delay = max(float(pos) - float(interval.start), 0.0)
            monitor.track_skip(interval.skip_type, accurate=True, delay_seconds=delay)
        except Exception:
            pass

    def _loop(self) -> None:
        dead_polls = 0
        last_pos: Optional[float] = None
        try:
            while not self._stop.is_set():
                self._load_intervals()
                if self._state_source is not None:
                    # Passive mode: read the Watch Host's already-polled state.
                    # No get_property requests are issued to mpv here.
                    pos, paused = self._read_state_source()
                    if pos is None:
                        dead_polls += 1
                        if dead_polls >= _MAX_DEAD_POLLS:
                            break
                        time.sleep(POLL_INTERVAL)
                        continue
                    dead_polls = 0
                else:
                    # Active mode: own the polling, but never fight mpv while
                    # the player is paused — only the pause flag is checked at
                    # a relaxed cadence (time-pos polling fully suspended).
                    if not getattr(self._ipc, "connected", False):
                        if not self._ipc.connect(timeout=2.0):
                            dead_polls += 1
                            if dead_polls >= _MAX_DEAD_POLLS:
                                break
                            time.sleep(POLL_INTERVAL)
                            continue
                    try:
                        paused = self._ipc.get_pause()
                    except Exception:
                        paused = None
                    if paused is True:
                        last_pos = None
                        dead_polls = 0
                        time.sleep(PAUSED_POLL_INTERVAL)
                        continue
                    pos = None
                    try:
                        pos = self._ipc.get_time_pos()
                    except Exception:
                        pos = None
                    if pos is None:
                        dead_polls += 1
                        if dead_polls >= _MAX_DEAD_POLLS:
                            break
                        time.sleep(POLL_INTERVAL)
                        continue
                    dead_polls = 0
                if paused is True:
                    # Suspended while paused (both modes) — never skip, never
                    # probe time-pos, just wait for playback to resume.
                    last_pos = None
                    time.sleep(PAUSED_POLL_INTERVAL)
                    continue
                if time.time() - self._skip_cooldown < SKIP_COOLDOWN:
                    last_pos = pos
                    time.sleep(POLL_INTERVAL)
                    continue
                for interval in self._intervals:
                    if pos >= interval.end or pos < interval.start:
                        self._triggered[interval.skip_type] = False
                        continue
                    if self._triggered[interval.skip_type]:
                        continue
                    crossed_forward = last_pos is not None and last_pos < interval.start
                    fresh_entry = (pos - interval.start) <= TRIGGER_WINDOW
                    if crossed_forward or fresh_entry:
                        self._trigger(interval, pos=pos)
                last_pos = pos
                time.sleep(POLL_INTERVAL)
        finally:
            if self._owns_ipc:
                try:
                    self._ipc.close()
                except Exception:
                    pass

    def _read_state_source(self) -> Tuple[Optional[float], Optional[bool]]:
        """Read ``(time_pos, paused)`` from the passive state source.

        Returns ``(None, None)`` when the source is missing, errored, or stale
        (the room's player has exited or the snapshot stopped updating), so the
        caller counts a dead poll and eventually exits."""
        src = None
        if self._state_source is not None:
            try:
                src = self._state_source()
            except Exception:
                src = None
        if not src or len(src) < 3:
            return None, None
        pos = src[0]
        ts = src[2]
        if pos is None or (time.time() - float(ts or 0.0)) > SOURCE_STALE:
            return None, None
        return float(pos), (bool(src[1]) if src[1] is not None else None)
