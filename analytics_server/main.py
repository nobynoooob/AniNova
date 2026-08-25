import os
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client


class MonitorPayload(BaseModel):
    fingerprint: str = ""
    timestamp: str = ""
    action: str = ""
    details: Dict[str, Any] = {}
    client: str = ""
    client_version: str = ""
    events: Optional[list] = None


app = FastAPI(title="ani-cli-arabic Analytics Server")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
AUTH_KEY = os.environ.get("ANALYTICS_AUTH_KEY", "")
TABLE_NAME = os.environ.get("ANALYTICS_TABLE", "usage_logs")

_supabase: Optional[Client] = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def _check_auth(x_auth_key: Optional[str]) -> None:
    if not AUTH_KEY:
        return
    if not x_auth_key or x_auth_key != AUTH_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Auth-Key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/monitor")
def monitor(
    payload: MonitorPayload,
    x_auth_key: Optional[str] = Header(default=None),
):
    _check_auth(x_auth_key)

    # Accept both the legacy single-event shape and the batched shape the
    # AniNova client sends ({fingerprint, client, client_version, events: []}).
    #
    # Client isolation: the AniNova client always tags itself ("AniNova");
    # anything arriving in the legacy single-event shape without a client tag
    # (the old ani-cli-ar client sends none) is stored as "legacy".
    batch_client = (payload.client or "AniNova").strip() or "legacy"
    batch_client_version = (payload.client_version or "").strip()
    rows = []
    if payload.events:
        for ev in payload.events:
            if not isinstance(ev, dict):
                continue
            rows.append({
                "fingerprint": ev.get("fingerprint") or payload.fingerprint,
                "timestamp": ev.get("timestamp") or payload.timestamp,
                "action": ev.get("action") or payload.action,
                "details": ev.get("details") or {},
                "client": (ev.get("client") or batch_client).strip() or "legacy",
                "client_version": (ev.get("client_version") or batch_client_version).strip(),
            })
    else:
        rows.append({
            "fingerprint": payload.fingerprint,
            "timestamp": payload.timestamp,
            "action": payload.action,
            "details": payload.details,
            "client": (payload.client or "legacy").strip() or "legacy",
            "client_version": (payload.client_version or "").strip(),
        })

    if not rows:
        raise HTTPException(status_code=400, detail="No valid events in payload")

    try:
        table = get_supabase().table(TABLE_NAME)
        inserted = 0
        for row in rows:
            result = table.insert(row).execute()
            inserted += len(result.data) if result.data else 0
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to insert: {exc}")

    return {"status": "ok", "inserted": inserted}


@app.get("/stats")
def stats(
    fingerprint: str = "",
    limit: int = 500,
    client: str = "AniNova",
    x_auth_key: Optional[str] = Header(default=None),
):
    """Return an aggregated streaming-history summary for a fingerprint.

    By default this isolates **AniNova** telemetry (``client=AniNova``) from
    legacy ani-cli-ar events. Pass ``client=legacy`` (or ``client=all``) to
    change the scope. RLS still scopes rows to the ``x-fingerprint`` header.
    """
    _check_auth(x_auth_key)
    limit = max(1, min(int(limit), 2000))
    client = (client or "AniNova").strip() or "AniNova"

    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        }
        params = {
            "action": "eq.video_play",
            "select": "timestamp,details",
            "order": "timestamp.desc",
            "limit": str(limit),
        }
        if fingerprint:
            params["fingerprint"] = f"eq.{fingerprint}"
            headers["x-fingerprint"] = fingerprint
        if client != "all":
            params["client"] = f"eq.{client}"

        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            params=params,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")

    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Unexpected response from telemetry store")

    total = len(rows)
    titles = Counter()
    players = Counter()
    providers = Counter()
    qualities = Counter()
    recent_7d = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    last_played: Optional[datetime] = None
    last_title = None
    last_episode = None

    for row in rows:
        details = row.get("details") or {}
        if not isinstance(details, dict):
            details = {}

        title = str(details.get("anime") or "Unknown")
        episode = str(details.get("episode") or "")
        titles[title] += 1
        players[str(details.get("player") or "unknown")] += 1
        providers[str(details.get("provider") or "unknown")] += 1
        qualities[str(details.get("quality") or "unknown")] += 1

        ts = row.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > cutoff:
                    recent_7d += 1
                if last_played is None or dt > last_played:
                    last_played = dt
                    last_title = title
                    last_episode = episode
            except Exception:
                pass

    return {
        "source": "remote",
        "fingerprint": fingerprint,
        "client": client,
        "total_plays": total,
        "unique_titles": len(titles),
        "recent_7d": recent_7d,
        "last_played": last_played.isoformat() if last_played else None,
        "last_title": last_title,
        "last_episode": last_episode,
        "top_titles": [
            {"title": title, "count": count}
            for title, count in titles.most_common(10)
        ],
        "by_player": dict(players),
        "by_provider": dict(providers),
        "by_quality": dict(qualities),
    }


@app.get("/overview")
def overview(
    client: str = "AniNova",
    days: int = 30,
    x_auth_key: Optional[str] = Header(default=None),
):
    """Dashboard-friendly aggregate: event counts by action for a client.

    Defaults to ``client=AniNova`` so the AniNova dashboard never mixes in
    legacy ani-cli-ar events. ``client=all`` removes the filter; ``days``
    bounds the window (0 = all time).
    """
    _check_auth(x_auth_key)
    client = (client or "AniNova").strip() or "AniNova"
    days = max(0, min(int(days), 3650))

    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        }
        params: Dict[str, Any] = {
            "select": "client,action,client_version,fingerprint,timestamp",
            "order": "timestamp.desc",
            "limit": "2000",
        }
        if client != "all":
            params["client"] = f"eq.{client}"
        if days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            params["timestamp"] = f"gte.{cutoff}"

        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}",
            params=params,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")

    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Unexpected response from telemetry store")

    by_action: Counter = Counter()
    by_client: Counter = Counter()
    by_version: Counter = Counter()
    unique_devices: Dict[str, set] = {}  # client -> set of distinct fingerprints
    for row in rows:
        row_client = str(row.get("client") or "legacy")
        by_action[f"{row_client}:{str(row.get('action') or 'unknown')}"] += 1
        by_client[row_client] += 1
        version = str(row.get("client_version") or "")
        if version:
            by_version[f"{row_client}:{version}"] += 1
        fp = str(row.get("fingerprint") or "")
        if fp:
            unique_devices.setdefault(row_client, set()).add(fp)

    return {
        "client": client,
        "days": days,
        "total_events": len(rows),
        "unique_devices": {c: len(fps) for c, fps in unique_devices.items()},
        "by_client": dict(by_client),
        "by_version": dict(by_version),
        "by_action": dict(by_action),
    }


# ---------------------------------------------------------------------------
# Analytics view endpoints
#
# Every view below is defined in schema.sql and is AniNova-scoped (client =
# 'AniNova' baked into the view definitions), so legacy ani-cli-ar rows can
# never leak into these metrics. Queries run with the service-role key, which
# bypasses RLS; the security_invoker views keep anon-key dashboard access
# fingerprint-scoped.
# ---------------------------------------------------------------------------

def _query_view(view: str, limit: int = 200, order: str = "", extra: Dict[str, str] = None):
    """Query one SQL analytics view through PostgREST. Returns a list."""
    params: Dict[str, Any] = {"select": "*", "limit": str(max(1, min(int(limit), 2000)))}
    if order:
        params["order"] = order
    for key, value in (extra or {}).items():
        params[key] = value
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/{view}",
        params=params,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"unexpected response shape from {view}")
    return data


def _query_one(view: str, extra: Dict[str, str] = None) -> dict:
    """Single-row views (aggregates): return {} when empty instead of 404-ish []."""
    rows = _query_view(view, limit=1, extra=extra)
    return rows[0] if rows else {}


@app.get("/active")
def active_users(x_auth_key: Optional[str] = Header(default=None)):
    """Real-time active users (heartbeat seen in the last 5 minutes)."""
    _check_auth(x_auth_key)
    try:
        return {"source": "remote", "active": _query_one("v_active_users")}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/audience")
def audience(x_auth_key: Optional[str] = Header(default=None)):
    """DAU series (30d) + WAU/MAU totals."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "dau_daily": _query_view("v_dau_daily", limit=30, order="day.desc"),
            "totals": _query_one("v_mau_monthly"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/sessions")
def sessions(x_auth_key: Optional[str] = Header(default=None)):
    """Session tracking: closed sessions per day with duration stats."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "sessions_daily": _query_view("v_sessions", limit=60, order="day.desc"),
            "watch_duration_by_anime": _query_view(
                "v_watch_duration", limit=50, order="total_watch_seconds.desc"
            ),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/systems")
def systems(x_auth_key: Optional[str] = Header(default=None)):
    """System specs & comps: OS breakdown, player preference, version spread."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "specs": _query_view("v_system_specs", limit=100, order="events.desc"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/errors")
def errors(
    limit: int = 20,
    x_auth_key: Optional[str] = Header(default=None),
):
    """Error log summary + recent full stack traces (playback crashes)."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "summary": _query_view("v_error_summary", limit=100, order="occurrences.desc"),
            "traces": _query_view("v_error_traces", limit=limit),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/providers")
def providers(x_auth_key: Optional[str] = Header(default=None)):
    """Provider success/failure rates + recent fallback switches."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "stats": _query_view("v_provider_stats", limit=50, order="successes.desc"),
            "fallbacks": _query_view("v_fallbacks", limit=50),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/content")
def content(x_auth_key: Optional[str] = Header(default=None)):
    """Content tops: top played anime ranking + search language distribution."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "top_anime": _query_view("v_top_anime", limit=25, order="plays.desc"),
            "search_languages": _query_view("v_search_languages", limit=20, order="searches.desc"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/watch-together")
def watch_together_metrics(x_auth_key: Optional[str] = Header(default=None)):
    """Watch Together metrics: rooms, host/guest ratio, durations, sync errors."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "summary": _query_one("v_watch_together"),
            "trend": _query_view("v_room_trend", limit=60, order="day.desc"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/auto-skip")
def auto_skip_metrics(x_auth_key: Optional[str] = Header(default=None)):
    """Auto-Skip insights: OP/ED trigger counts, latency & accuracy."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "skips": _query_view("v_auto_skip", limit=20, order="triggers.desc"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/ui")
def ui_metrics(x_auth_key: Optional[str] = Header(default=None)):
    """Rich Presence toggle rates + theme preferences."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "features": _query_view("v_rpc_ui", limit=50, order="events.desc"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/stream-quality")
def stream_quality(x_auth_key: Optional[str] = Header(default=None)):
    """Performance: provider resolve times (p50/p95), buffer stalls, quality mix."""
    _check_auth(x_auth_key)
    try:
        return {
            "source": "remote",
            "resolve_times": _query_view("v_stream_quality", limit=50, order="plays.desc"),
            "buffer_stalls": _query_view("v_buffer_stalls", limit=60, order="day.desc"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to query telemetry: {exc}")


@app.get("/dashboard")
def dashboard(x_auth_key: Optional[str] = Header(default=None)):
    """One-shot snapshot combining every metric domain (small limits)."""
    _check_auth(x_auth_key)
    out: Dict[str, Any] = {"source": "remote"}
    failures: Dict[str, str] = {}
    sections = {
        "active": lambda: {"active": _query_one("v_active_users")},
        "audience_totals": lambda: _query_one("v_mau_monthly"),
        "top_anime": lambda: _query_view("v_top_anime", limit=10, order="plays.desc"),
        "search_languages": lambda: _query_view("v_search_languages", limit=10, order="searches.desc"),
        "systems": lambda: _query_view("v_system_specs", limit=20, order="events.desc"),
        "providers": lambda: _query_view("v_provider_stats", limit=15, order="successes.desc"),
        "errors": lambda: _query_view("v_error_summary", limit=10, order="occurrences.desc"),
        "sessions": lambda: _query_view("v_sessions", limit=14, order="day.desc"),
        "watch_together": lambda: _query_one("v_watch_together"),
        "auto_skip": lambda: _query_view("v_auto_skip", limit=10, order="triggers.desc"),
        "rpc_ui": lambda: _query_view("v_rpc_ui", limit=15, order="events.desc"),
        "stream_quality": lambda: _query_view("v_stream_quality", limit=15, order="plays.desc"),
        "daily_summary": lambda: _query_view("v_daily_summary", limit=90, order="day.desc"),
    }
    for name, fn in sections.items():
        try:
            out[name] = fn()
        except Exception as exc:
            failures[name] = str(exc)
    if failures:
        out["partial_failures"] = failures
    return out
