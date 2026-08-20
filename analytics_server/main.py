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
            "select": "client,action,client_version,timestamp",
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
