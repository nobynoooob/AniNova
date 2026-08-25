"""Dynamic Arabic synopsis translation with a persistent cache.

When the curated dictionary and API metadata have no Arabic description, the
UI can request an on-the-fly translation through the desktop bridge (never
from the webview directly — CORS on translate endpoints is unreliable inside
embedded engines).

Endpoint: Google Translate's public ``client=gtx`` JSON API — fast, free,
no key. Translations are cached in memory for the session and persisted to
``~/.ani-cli-arabic/database/translations.json`` (hash-keyed, size-capped) so
an anime is only ever translated once per installation.
"""

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional

_GTX_URL = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&sl=auto&tl=ar&dt=t&q={q}"
)
_TIMEOUT = 6.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_MAX_CACHE_ENTRIES = 600
_MAX_SOURCE_LEN = 4000  # gtx query-length headroom


def _cache_path() -> Path:
    return Path.home() / ".ani-cli-arabic" / "database" / "translations.json"


class _Store:
    """Process-wide cache facade: in-memory dict mirrored to disk."""

    def __init__(self):
        self._lock = threading.Lock()
        self._mem: Dict[str, str] = {}
        self._loaded = False

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()

    def _load(self):
        if self._loaded:
            return
        try:
            p = _cache_path()
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._mem = {
                        str(k): str(v) for k, v in raw.items()
                        if isinstance(v, str) and v.strip()
                    }
        except Exception:
            self._mem = {}
        self._loaded = True

    def _persist(self):
        try:
            p = _cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            # Size cap: drop oldest-inserted entries beyond the limit.
            if len(self._mem) > _MAX_CACHE_ENTRIES:
                for k in list(self._mem.keys())[: len(self._mem) - _MAX_CACHE_ENTRIES]:
                    self._mem.pop(k, None)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._mem, ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
            tmp.replace(p)
        except Exception:
            pass

    def get(self, text: str) -> Optional[str]:
        with self._lock:
            self._load()
            return self._mem.get(self._key(text))

    def put(self, text: str, arabic: str):
        with self._lock:
            self._load()
            self._mem[self._key(text)] = arabic
            self._persist()


_store = _Store()


def get_cached_translation(text: str) -> Optional[str]:
    """Instant lookup (memory -> disk). Never touches the network."""
    text = str(text or "").strip()
    if not text:
        return None
    try:
        return _store.get(text)
    except Exception:
        return None


def _parse_gtx(payload) -> Optional[str]:
    """Extract the translated string from gtx's nested-array response."""
    try:
        segments = payload[0]
        parts = []
        for seg in segments:
            if isinstance(seg, (list, tuple)) and seg and isinstance(seg[0], str):
                parts.append(seg[0])
        out = "".join(parts).strip()
        return out or None
    except Exception:
        return None


def translate_to_arabic(text: str, _transport=None) -> Optional[str]:
    """Translate English synopsis text to Arabic.

    Order: cache -> network (gtx). Returns None when disabled inputs, offline
    failures, or non-Arabic results make a translation unusable. ``_transport``
    exists solely for tests (httpx.MockTransport).
    """
    text = str(text or "").strip()
    if not text or len(text) < 8:
        return None
    cached = get_cached_translation(text)
    if cached:
        return cached
    try:
        import httpx
        from urllib.parse import quote
        url = _GTX_URL.format(q=quote(text[:_MAX_SOURCE_LEN]))
        kwargs = {
            "timeout": _TIMEOUT,
            "follow_redirects": True,
            "headers": {"User-Agent": _UA},
        }
        if _transport is not None:
            kwargs["transport"] = _transport
        with httpx.Client(**kwargs) as client:
            r = client.get(url)
        if r.status_code != 200:
            return None
        ar = _parse_gtx(r.json())
        if not ar or not any("\u0600" <= ch <= "\u06FF" for ch in ar):
            return None  # endpoint answered but not with Arabic
        try:
            _store.put(text, ar)
        except Exception:
            pass
        return ar
    except Exception:
        return None
