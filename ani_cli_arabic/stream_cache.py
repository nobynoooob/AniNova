"""TTL-backed stream-URL cache shared by the GUI pipeline and Watch Together.

HLS manifest URLs stay valid far longer than a typical viewing session, yet
every episode click (and every room guest) re-ran the full provider chain.
This module caches successful resolutions keyed by
``(identity, episode, category, resolution)`` with a conservative TTL, plus an
in-flight registry so concurrent callers (user click + background prefetch,
host + joining guests) never duplicate the same upstream resolution.
"""

import threading
import time
from collections import OrderedDict
from typing import Dict, Optional


# Conservative: most anime CDN tokens live hours; 90 min keeps stale-token
# risk low while covering binge sessions and room rejoins.
DEFAULT_TTL = 90 * 60
MAX_ENTRIES = 64


def normalize_ep(ep) -> str:
    """Canonical episode component ('12' for 12/12.0/\"12\", '12.5' kept)."""
    try:
        f = float(ep)
    except (TypeError, ValueError):
        return str(ep or "").strip()
    return str(int(f)) if f == int(f) else repr(f)


def make_key(identity, ep, category, resolution="") -> tuple:
    """Stable cache key. ``identity`` may be an AniList id or a title — both
    are namespaced identically because callers always reuse the same identity
    kind for a given flow."""
    return (
        str(identity or "").strip().lower(),
        normalize_ep(ep),
        str(category or "").strip().lower(),
        str(resolution or "").strip().lower(),
    )


class StreamCache:
    """Process-wide singleton. All methods are thread-safe."""

    _instance: Optional["StreamCache"] = None
    _singleton_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "StreamCache":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: Dict[tuple, dict] = OrderedDict()
        self._inflight: Dict[tuple, float] = {}

    def get(self, key: tuple) -> Optional[dict]:
        """Return ``{"stream_url", "headers", "provider"}`` for a live entry,
        refreshing LRU recency. Expired entries are dropped on access."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if time.time() >= entry["expires_at"]:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return {
                "stream_url": entry["stream_url"],
                "headers": dict(entry["headers"] or {}),
                "provider": entry.get("provider", ""),
            }

    def put(self, key: tuple, stream_url: str, headers: Optional[dict],
            provider: str = "", ttl: float = DEFAULT_TTL) -> bool:
        """Cache a successful resolution. Empty URLs are never cached."""
        url = str(stream_url or "").strip()
        if not url:
            return False
        with self._lock:
            self._entries[key] = {
                "stream_url": url,
                "headers": dict(headers or {}),
                "provider": str(provider or ""),
                "expires_at": time.time() + max(1.0, float(ttl)),
            }
            self._entries.move_to_end(key)
            while len(self._entries) > MAX_ENTRIES:
                self._entries.popitem(last=False)
        return True

    def invalidate(self, key: tuple):
        """Drop one entry (e.g. after a confirmed dead-URL playback failure)."""
        with self._lock:
            self._entries.pop(key, None)

    # -- in-flight dedupe -------------------------------------------------
    def begin(self, key: tuple) -> bool:
        """Claim exclusive rights to resolve ``key``. False => someone else
        (prefetch, another guest worker) is already resolving it."""
        now = time.time()
        with self._lock:
            # Reap abandoned claims older than the provider budget ceiling.
            for k in [k for k, ts in self._inflight.items() if now - ts > 120.0]:
                self._inflight.pop(k, None)
            if key in self._inflight:
                return False
            self._inflight[key] = now
            return True

    def end(self, key: tuple):
        with self._lock:
            self._inflight.pop(key, None)
