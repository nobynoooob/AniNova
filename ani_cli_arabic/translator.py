"""Dynamic Arabic synopsis translation with a persistent cache.

When the curated dictionary and API metadata have no Arabic description, the
UI can request an on-the-fly translation through the desktop bridge (never
from the webview directly — CORS on translate endpoints is unreliable inside
embedded engines).

Provider chain (first success wins):
  1. Google gtx JSON API      — fast, but aggressively IP-rate-limited (429)
  2. MyMemory translated.net   — free keyless fallback, generous limits

Every step logs to stderr with a ``[translator]`` prefix so pipeline issues
(blocks, offline, parse failures) are traceable in console output.

Translations are cached in memory for the session and persisted to
``~/.ani-cli-arabic/database/translations.json`` (hash-keyed, size-capped) so
an anime is only ever translated once per installation. Cached entries also
shield against provider blocks entirely.
"""

import hashlib
import json
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

_GTX_URL = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&sl=auto&tl=ar&dt=t&q={q}"
)
_MYMEMORY_URL = "https://api.mymemory.translated.net/get"
_TIMEOUT = 6.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_MAX_CACHE_ENTRIES = 600
_MAX_SOURCE_LEN = 4000  # gtx query-length headroom


def _log(msg: str):
    try:
        sys.stderr.write(f"[translator] {msg}\n")
    except Exception:
        pass


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
                    _log(f"disk cache loaded ({len(self._mem)} entries)")
        except Exception as exc:
            self._mem = {}
            _log(f"disk cache load failed: {type(exc).__name__}: {exc}")
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
        except Exception as exc:
            _log(f"disk persist failed: {type(exc).__name__}: {exc}")

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


def _is_arabic(s: Optional[str]) -> bool:
    return bool(s) and any("\u0600" <= ch <= "\u06FF" for ch in s)


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


def _client_kwargs(_transport=None) -> dict:
    kwargs = {
        "timeout": _TIMEOUT,
        "follow_redirects": True,
        "headers": {"User-Agent": _UA},
    }
    if _transport is not None:
        kwargs["transport"] = _transport
    return kwargs


def _translate_gtx(text: str, _transport=None) -> Optional[str]:
    """Google gtx provider. Frequently 429-blocked by IP; that is EXPECTED and
    simply falls through to MyMemory."""
    import httpx
    from urllib.parse import quote
    url = _GTX_URL.format(q=quote(text[:_MAX_SOURCE_LEN]))
    with httpx.Client(**_client_kwargs(_transport)) as client:
        r = client.get(url)
    if r.status_code != 200:
        _log(f"gtx blocked (HTTP {r.status_code}) - falling back to MyMemory")
        return None
    ar = _parse_gtx(r.json())
    if not _is_arabic(ar):
        _log("gtx returned non-Arabic payload - falling back to MyMemory")
        return None
    return ar


def _translate_mymemory(text: str, _transport=None) -> Optional[str]:
    """MyMemory translated.net provider (free, keyless, IP-friendlier)."""
    import httpx
    with httpx.Client(**_client_kwargs(_transport)) as client:
        r = client.get(_MYMEMORY_URL, params={"q": text[:_MAX_SOURCE_LEN],
                                              "langpair": "en|ar"})
    if r.status_code != 200:
        _log(f"mymemory HTTP {r.status_code}")
        return None
    data = r.json()
    out = ((data.get("responseData") or {}).get("translatedText") or "").strip()
    # MyMemory signals quota/blocked states via responseStatus != 200 while
    # still returning HTTP 200 with an error string in translatedText.
    status = int(data.get("responseStatus") or 0)
    if status and status != 200:
        _log(f"mymemory responseStatus={status}")
        return None
    if not out or not _is_arabic(out) or out.startswith("MYMEMORY WARNING"):
        _log("mymemory returned unusable payload")
        return None
    return out


def translate_to_arabic(text: str, _transport=None) -> Optional[str]:
    """Translate English synopsis text to Arabic.

    Order: cache -> gtx -> MyMemory. Returns None when disabled inputs,
    offline failures, or unusable results make a translation impossible.
    ``_transport`` exists solely for tests (httpx.MockTransport).
    """
    text = str(text or "").strip()
    if not text or len(text) < 8:
        return None
    cached = get_cached_translation(text)
    if cached:
        _log("cache hit")
        return cached
    _log(f"translating {len(text)} chars...")
    for name, fn in (("gtx", _translate_gtx), ("mymemory", _translate_mymemory)):
        try:
            ar = fn(text, _transport)
        except Exception as exc:
            _log(f"{name} raised {type(exc).__name__}: {exc}")
            continue
        if ar:
            _log(f"{name} OK -> caching ({len(ar)} chars)")
            try:
                _store.put(text, ar)
            except Exception:
                pass
            return ar
    _log("all providers failed")
    return None
