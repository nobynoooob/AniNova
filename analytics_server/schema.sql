-- ============================================================================
-- AniNova Analytics Schema — complete setup for the dedicated AniNova project.
--
-- Supersedes the legacy ani-cli-ar schema (same core table + RLS, extended
-- with client isolation columns and a full analytics view layer).
--
-- Idempotent: safe to re-run in the Supabase SQL Editor at any time.
--   * tables/indexes use IF NOT EXISTS
--   * policies are dropped and recreated
--   * views/functions are CREATE OR REPLACE
--
-- Sections:
--   1. Core event store (usage_logs) + indexes
--   2. Row Level Security (insert open, select scoped by x-fingerprint header)
--   3. Safe JSON helpers
--   4. Legacy-parity metrics: system specs, errors/providers, active usage &
--      sessions, content tops
--   5. AniNova-exclusive metrics: Watch Together, Auto-Skip, RPC/UI,
--      stream quality & performance
--   6. Dashboard rollups
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) Core event store
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.usage_logs (
    id BIGSERIAL PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    action TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    client TEXT NOT NULL DEFAULT 'legacy',
    client_version TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_action
    ON public.usage_logs (action);

CREATE INDEX IF NOT EXISTS idx_usage_logs_fingerprint
    ON public.usage_logs (fingerprint);

CREATE INDEX IF NOT EXISTS idx_usage_logs_timestamp
    ON public.usage_logs (timestamp DESC);

-- Client isolation (AniNova vs legacy ani-cli-ar): every dashboard scan
-- filters on client first, so index the leading column everywhere.
CREATE INDEX IF NOT EXISTS idx_usage_logs_client_action
    ON public.usage_logs (client, action);

CREATE INDEX IF NOT EXISTS idx_usage_logs_client_timestamp
    ON public.usage_logs (client, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_usage_logs_client_action_ts
    ON public.usage_logs (client, action, timestamp DESC);

-- ----------------------------------------------------------------------------
-- 2) Row Level Security
--    Inserts stay open (the CLI posts with the anon key); reads are scoped to
--    the x-fingerprint request header so a device can only ever see its own
--    rows without a privileged key. The server uses the service-role key,
--    which bypasses RLS entirely.
-- ----------------------------------------------------------------------------

ALTER TABLE public.usage_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS insert_usage_logs_anon ON public.usage_logs;
CREATE POLICY insert_usage_logs_anon
    ON public.usage_logs
    FOR INSERT
    TO anon
    WITH CHECK (true);

DROP POLICY IF EXISTS insert_usage_logs_authenticated ON public.usage_logs;
CREATE POLICY insert_usage_logs_authenticated
    ON public.usage_logs
    FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- "Allow individual read access via fingerprint" (legacy parity, ported):
DROP POLICY IF EXISTS select_usage_logs_scoped ON public.usage_logs;
CREATE POLICY select_usage_logs_scoped
    ON public.usage_logs
    FOR SELECT
    TO anon, authenticated
    USING (
        fingerprint = NULLIF(
            current_setting('request.headers', true)::json->>'x-fingerprint',
            ''
        )
    );

-- ----------------------------------------------------------------------------
-- 3) Safe JSON helpers
--    details values arrive from many client versions; never cast blindly.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.json_num(d jsonb, k text)
RETURNS double precision
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN d->>k ~ '^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$'
        THEN (d->>k)::double precision
        ELSE NULL
    END
$$;

-- ----------------------------------------------------------------------------
-- 4) Legacy-parity metrics (adapted for AniNova; legacy rows excluded)
-- ----------------------------------------------------------------------------

-- System specs & comps: OS breakdown (Linux vs Windows vs ...), player
-- preference, app version spread — one dimension/value/events/devices shape.
CREATE OR REPLACE VIEW public.v_system_specs WITH (security_invoker = true) AS
SELECT 'os' AS dimension,
       COALESCE(NULLIF(split_part(details->>'os', ' ', 1), ''), 'Unknown') AS value,
       count(*) AS events,
       count(DISTINCT fingerprint) AS devices,
       max(timestamp) AS last_seen
FROM public.usage_logs
WHERE client = 'AniNova' AND action IN ('app_start', 'heartbeat')
GROUP BY 1, 2
UNION ALL
SELECT 'player' AS dimension,
       COALESCE(NULLIF(details->>'player', ''), 'unknown') AS value,
       count(*) AS events,
       count(DISTINCT fingerprint) AS devices,
       max(timestamp) AS last_seen
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'video_play'
GROUP BY 1, 2
UNION ALL
SELECT 'app_version' AS dimension,
       COALESCE(NULLIF(details->>'app_version', ''), 'unknown') AS value,
       count(*) AS events,
       count(DISTINCT fingerprint) AS devices,
       max(timestamp) AS last_seen
FROM public.usage_logs
WHERE client = 'AniNova' AND action IN ('app_start', 'heartbeat')
GROUP BY 1, 2;

-- Error log summary: grouped by exception type + short message, occurrence
-- counts, affected devices, HTTP status mix, traceback availability.
CREATE OR REPLACE VIEW public.v_error_summary WITH (security_invoker = true) AS
SELECT COALESCE(NULLIF(details->>'exception_type', ''), 'Error') AS exception_type,
       LEFT(COALESCE(details->>'error_msg', ''), 160) AS message,
       count(*) AS occurrences,
       count(DISTINCT fingerprint) AS devices,
       max(public.json_num(details, 'http_status'))::int AS http_status,
       bool_or(details ? 'traceback') AS has_traceback,
       max(timestamp) AS last_seen
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'error'
GROUP BY 1, 2;

-- Full stack-trace feed for playback crashes (query with limit/order via
-- PostgREST; each row carries the truncated-but-complete captured traceback).
CREATE OR REPLACE VIEW public.v_error_traces WITH (security_invoker = true) AS
SELECT timestamp,
       fingerprint,
       client_version,
       COALESCE(NULLIF(details->>'exception_type', ''), 'Error') AS exception_type,
       COALESCE(details->>'error_msg', '') AS error_msg,
       COALESCE(details->>'traceback', '') AS traceback,
       details
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'error' AND details ? 'traceback';

-- Provider success/failure rates: successes come from video_play rows,
-- failures from provider_fallback events (failed provider = from_provider).
CREATE OR REPLACE VIEW public.v_provider_stats WITH (security_invoker = true) AS
WITH succ AS (
    SELECT COALESCE(NULLIF(details->>'provider', ''), 'unknown') AS provider,
           count(*) AS successes
    FROM public.usage_logs
    WHERE client = 'AniNova' AND action = 'video_play'
    GROUP BY 1
),
fail AS (
    SELECT COALESCE(NULLIF(details->>'from_provider', ''), 'unknown') AS provider,
           count(*) AS failures
    FROM public.usage_logs
    WHERE client = 'AniNova' AND action = 'provider_fallback'
    GROUP BY 1
)
SELECT COALESCE(succ.provider, fail.provider) AS provider,
       COALESCE(succ.successes, 0) AS successes,
       COALESCE(fail.failures, 0) AS failures,
       ROUND(
           COALESCE(fail.failures, 0)::numeric * 100
           / NULLIF(COALESCE(succ.successes, 0) + COALESCE(fail.failures, 0), 0)
       , 1) AS failure_rate_pct
FROM succ
FULL OUTER JOIN fail ON succ.provider = fail.provider;

-- Real-time active users (heartbeat seen in the last 5 minutes).
CREATE OR REPLACE VIEW public.v_active_users WITH (security_invoker = true) AS
SELECT count(DISTINCT fingerprint) AS active_now,
       count(DISTINCT fingerprint) FILTER (WHERE details->>'status' = 'watching') AS active_watching,
       max(timestamp) AS last_seen
FROM public.usage_logs
WHERE client = 'AniNova'
  AND action = 'heartbeat'
  AND timestamp > now() - interval '5 minutes';

-- Daily Active Users series (trailing 30 days).
CREATE OR REPLACE VIEW public.v_dau_daily WITH (security_invoker = true) AS
SELECT date_trunc('day', timestamp) AS day,
       count(DISTINCT fingerprint) AS dau,
       count(*) AS events
FROM public.usage_logs
WHERE client = 'AniNova' AND timestamp > now() - interval '30 days'
GROUP BY 1;

-- Monthly Active Users (distinct devices over the trailing 30 days), split by
-- latest-seen app version.
CREATE OR REPLACE VIEW public.v_mau_monthly WITH (security_invoker = true) AS
SELECT count(DISTINCT fingerprint) AS mau_30d,
       count(DISTINCT fingerprint) FILTER (
           WHERE timestamp > now() - interval '7 days'
       ) AS wau_7d
FROM public.usage_logs
WHERE client = 'AniNova' AND timestamp > now() - interval '30 days';

-- Session tracking: sessions closed per day with duration stats (from the
-- atexit-flushed app_session_end events).
CREATE OR REPLACE VIEW public.v_sessions WITH (security_invoker = true) AS
SELECT date_trunc('day', timestamp) AS day,
       count(*) AS sessions,
       count(DISTINCT fingerprint) AS devices,
       ROUND(AVG(public.json_num(details, 'session_duration_seconds'))::numeric, 1) AS avg_session_seconds,
       ROUND(SUM(public.json_num(details, 'session_duration_seconds'))::numeric, 1) AS total_session_seconds
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'app_session_end'
  AND public.json_num(details, 'session_duration_seconds') IS NOT NULL
GROUP BY 1;

-- Episode watch duration per anime (from video_play watch windows).
CREATE OR REPLACE VIEW public.v_watch_duration WITH (security_invoker = true) AS
SELECT details->>'anime' AS anime,
       count(*) AS plays,
       count(DISTINCT fingerprint) AS devices,
       ROUND(SUM(public.json_num(details, 'watch_duration_seconds'))::numeric, 1) AS total_watch_seconds,
       ROUND(AVG(public.json_num(details, 'watch_duration_seconds'))::numeric, 1) AS avg_watch_seconds
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'video_play'
  AND public.json_num(details, 'watch_duration_seconds') IS NOT NULL
GROUP BY 1;

-- Content tops: top played anime ranking.
CREATE OR REPLACE VIEW public.v_top_anime WITH (security_invoker = true) AS
SELECT details->>'anime' AS anime,
       count(*) AS plays,
       count(DISTINCT fingerprint) AS viewers,
       count(DISTINCT details->>'episode') AS episodes_watched,
       max(timestamp) AS last_played
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'video_play'
  AND COALESCE(details->>'anime', '') <> ''
GROUP BY 1;

-- Search language distribution (query text is never transmitted).
CREATE OR REPLACE VIEW public.v_search_languages WITH (security_invoker = true) AS
SELECT COALESCE(NULLIF(details->>'language', ''), 'unknown') AS language,
       count(*) AS searches,
       count(DISTINCT fingerprint) AS devices,
       ROUND(count(*)::numeric * 100 / NULLIF(SUM(count(*)) OVER (), 0), 1) AS share_pct
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'search_event'
GROUP BY 1;

-- ----------------------------------------------------------------------------
-- 5) AniNova-exclusive metrics
-- ----------------------------------------------------------------------------

-- Watch Together: wide single-row summary (rooms, roles, durations, sync).
CREATE OR REPLACE VIEW public.v_watch_together WITH (security_invoker = true) AS
SELECT
    (SELECT count(*) FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event' AND details->>'event'='create')
        AS rooms_created,
    (SELECT count(*) FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event' AND details->>'event'='join')
        AS joins,
    (SELECT count(*) FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event' AND details->>'event'='leave')
        AS leaves,
    (SELECT count(*) FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event' AND details->>'event'='end')
        AS rooms_ended,
    (SELECT count(*) FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event' AND details->>'role'='host')
        AS host_events,
    (SELECT count(*) FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event' AND details->>'role'='guest')
        AS guest_events,
    (SELECT ROUND(
                count(*) FILTER (WHERE details->>'role'='host')::numeric * 100
                / NULLIF(count(*), 0), 1)
     FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event')
        AS host_share_pct,
    (SELECT ROUND(AVG(public.json_num(details, 'members'))::numeric, 2)
     FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event'
       AND public.json_num(details, 'members') IS NOT NULL)
        AS avg_members,
    (SELECT ROUND(AVG(public.json_num(details, 'duration_s'))::numeric, 1)
     FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event' AND details->>'event' IN ('end','leave')
       AND public.json_num(details, 'duration_s') IS NOT NULL)
        AS avg_session_seconds,
    (SELECT count(*) FROM public.usage_logs
     WHERE client='AniNova' AND action='sync_error')
        AS sync_errors,
    (SELECT ROUND(AVG(public.json_num(details, 'drift_seconds'))::numeric, 2)
     FROM public.usage_logs
     WHERE client='AniNova' AND action='sync_error'
       AND public.json_num(details, 'drift_seconds') IS NOT NULL)
        AS avg_sync_drift_seconds,
    (SELECT max(timestamp) FROM public.usage_logs
     WHERE client='AniNova' AND action='room_event')
        AS last_room_activity;

-- Room creation trend per day.
CREATE OR REPLACE VIEW public.v_room_trend WITH (security_invoker = true) AS
SELECT date_trunc('day', timestamp) AS day,
       count(*) FILTER (WHERE details->>'event' = 'create') AS rooms_created,
       count(*) FILTER (WHERE details->>'event' = 'join') AS joins,
       count(*) FILTER (WHERE details->>'event' IN ('end','leave')) AS sessions_closed
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'room_event'
GROUP BY 1;

-- Auto-Skip insights: trigger counts by kind (op/ed/recap), skip latency
-- (delay after window start) as the accuracy proxy, distinct devices.
CREATE OR REPLACE VIEW public.v_auto_skip WITH (security_invoker = true) AS
SELECT COALESCE(NULLIF(details->>'kind', ''), 'unknown') AS kind,
       COALESCE(NULLIF(details->>'action', ''), 'skipped') AS action,
       count(*) AS triggers,
       count(DISTINCT fingerprint) AS devices,
       ROUND(AVG(public.json_num(details, 'delay_seconds'))::numeric, 2) AS avg_delay_seconds,
       ROUND((count(*) FILTER (WHERE COALESCE(details->>'accurate','true') = 'true')::numeric
              * 100) / NULLIF(count(*), 0), 1) AS accurate_pct,
       max(timestamp) AS last_trigger
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'skip_event'
GROUP BY 1, 2;

-- Rich Presence & UI customization: RPC toggle rates + theme preferences in
-- one dimension/choice shape.
CREATE OR REPLACE VIEW public.v_rpc_ui WITH (security_invoker = true) AS
SELECT 'rpc' AS feature,
       COALESCE(NULLIF(details->>'action', ''), 'unknown') AS choice,
       count(*) AS events,
       count(DISTINCT fingerprint) AS devices,
       max(timestamp) AS last_seen
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'rpc_event'
GROUP BY 1, 2
UNION ALL
SELECT 'theme' AS feature,
       COALESCE(NULLIF(lower(details->>'theme'), ''), 'unknown') AS choice,
       count(*) AS events,
       count(DISTINCT fingerprint) AS devices,
       max(timestamp) AS last_seen
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'theme_event'
GROUP BY 1, 2;

-- Performance & stream quality: provider resolve times (p50/p95), quality mix.
CREATE OR REPLACE VIEW public.v_stream_quality WITH (security_invoker = true) AS
SELECT COALESCE(NULLIF(details->>'provider', ''), 'unknown') AS provider,
       count(*) AS plays,
       ROUND(AVG(public.json_num(details, 'resolve_ms'))::numeric, 0) AS avg_resolve_ms,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY public.json_num(details, 'resolve_ms'))::numeric, 0) AS p50_resolve_ms,
       ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY public.json_num(details, 'resolve_ms'))::numeric, 0) AS p95_resolve_ms,
       count(*) FILTER (WHERE COALESCE(details->>'quality','') <> '') AS quality_tagged_plays,
       ROUND(AVG(public.json_num(details, 'watch_duration_seconds'))::numeric, 1) AS avg_watch_seconds
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'video_play'
GROUP BY 1;

-- Stream buffer stalls (playback underruns reported by the player monitor).
CREATE OR REPLACE VIEW public.v_buffer_stalls WITH (security_invoker = true) AS
SELECT date_trunc('day', timestamp) AS day,
       count(*) AS stalls,
       count(DISTINCT fingerprint) AS devices,
       ROUND(AVG(public.json_num(details, 'stalled_seconds'))::numeric, 1) AS avg_stall_seconds,
       mode() WITHIN GROUP (ORDER BY details->>'anime') AS most_affected_anime
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'buffer_stall'
GROUP BY 1;

-- Fallback switch feed: which provider failed, what took over, and why.
CREATE OR REPLACE VIEW public.v_fallbacks WITH (security_invoker = true) AS
SELECT timestamp,
       fingerprint,
       client_version,
       COALESCE(details->>'from_provider', '') AS from_provider,
       COALESCE(details->>'to_provider', '') AS to_provider,
       COALESCE(details->>'reason', '') AS reason
FROM public.usage_logs
WHERE client = 'AniNova' AND action = 'provider_fallback';

-- ----------------------------------------------------------------------------
-- 6) Dashboard rollup: events per day per action (master chart source)
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW public.v_daily_summary WITH (security_invoker = true) AS
SELECT date_trunc('day', timestamp) AS day,
       action,
       count(*) AS events,
       count(DISTINCT fingerprint) AS devices
FROM public.usage_logs
WHERE client = 'AniNova' AND timestamp > now() - interval '90 days'
GROUP BY 1, 2;

-- ----------------------------------------------------------------------------
-- Access grants for the views/helpers (idempotent). The server reads through
-- the service-role key; these grants additionally allow anon/authenticated
-- dashboards, still bounded by the underlying RLS policy thanks to
-- security_invoker views.
-- ----------------------------------------------------------------------------

GRANT SELECT ON
    public.v_system_specs,
    public.v_error_summary,
    public.v_error_traces,
    public.v_provider_stats,
    public.v_active_users,
    public.v_dau_daily,
    public.v_mau_monthly,
    public.v_sessions,
    public.v_watch_duration,
    public.v_top_anime,
    public.v_search_languages,
    public.v_watch_together,
    public.v_room_trend,
    public.v_auto_skip,
    public.v_rpc_ui,
    public.v_stream_quality,
    public.v_buffer_stalls,
    public.v_fallbacks,
    public.v_daily_summary
TO anon, authenticated;

GRANT EXECUTE ON FUNCTION public.json_num(jsonb, text) TO anon, authenticated;
