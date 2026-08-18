# AniNova

## Development Rules & Guidelines

### 🤖 Role & Behavior Directive
- **Proactive Partner**: Do not just execute commands proactively. Audit the codebase, detect performance bottlenecks, and proactively implement clean optimizations.
- **Safety & Guardrails**: IF a user prompt or modification would break critical dependencies, crash stream loading, or break builds, YOU MUST WARN THE USER FIRST and refuse to execute the breaking change.
- **Provider Parity**: All providers in `scrapers/` and the Arabic `api.py` pipeline must remain fully exposed and selectable in the GUI. Never disable a provider unless technically impossible on desktop platforms.

### ⚡ Performance Guidelines
1. Never block the UI thread during server resolving or video extraction. Use asynchronous workers or background threads.
2. Always pass MPV buffer/caching flags for slow connections (`--cache=yes`, `--cache-secs=300`, `--demuxer-max-bytes=150M`).
3. Never let Playwright browser work serialize with the UI — resolution must run on worker threads with `abort_event`/`cancel_event` support.

## Package structure
- Single package `ani_cli_arabic/`, entry point `ani_cli_arabic.gui:main` (`python -m ani_cli_arabic.gui`)
- PyWebView desktop GUI: `gui.py` hosts `ui/index.html` (webview SPA, `pywebview.api` JS bridge)
- Two independent language tracks: Arabic (via `api.py` → `AnimeAPI`) and English (via `scrapers/`)

## English scraping pipeline
- `ENGLISH_PROVIDERS = ["miruro", "hianime", "allanime", "api", "mkissa", "gogoanime"]` in `scrapers/provider_manager.py`
- Every scraper MUST inherit `BaseScraper` (ABC) and implement `search(query)`, `get_episodes(anime_id)`, `get_stream_url(episode_id)`
- `ProviderManager.resolve_stream()` chains providers in order, per-step failure isolation (each method wrapped in try/except returning None)
- Provider timeout: `_PROVIDER_TIMEOUT = 30.0` seconds (accommodates Playwright page loads)
- Stream dict format: `{"stream_url": str|None, "headers": dict}`

## Provider details
| Provider | Source | Stream method | Status |
|----------|--------|---------------|--------|
| `miruro` | miruro.tv secure pipe via Playwright | Playwright headless → `page.evaluate(fetch)` on pipe API | **Working** — pipe returns gzip(base64(json)) with m3u8 URLs from `hls.anidb.app` via `pewe` provider |
| `hianime` | hianime.to `/ajax/` protocol | HTTP first, then Playwright `page.evaluate(fetch)` | Search/episodes parse from ajax JSON; sources CF-gated on most networks (mirror `hi-anime.co` reachable, `.to` unreachable) |
| `allanime` | allanime.* / allmanga.to GraphQL API | HTTP POST to `api.allanime.day/api` | **Search + episodes verified working** (fast HTTP); episode sources gated behind `AA_CRYPTO_MISSING` AES-GCM client handshake, `get_stream_url` returns None (falls through to next provider) |
| `api` | Consumet-protocol API | HTTP to `ANI_API_BASE_URL` | Requires self-hosted endpoint; `_discover()` auto-detects working public instances |
| `mkissa` | mkissa.to + GraphQL API | Playwright network interceptor | Search/episodes work via HTTP; stream blocked by Turnstile captcha |
| `gogoanime` | gogoanime.co.za + live mirror hosts | HTTP + embed resolver (`embeds.py`) | Search/episodes work via HTTP; live episode host auto-discovered from hrefs; embed (kwik.cx) blocked by Cloudflare on this network |
- Shared embed gateway in `embeds.py`: `extract_media_url(html)`, `resolve_embed(url, referer)` → plain HTTP first, Playwright route/capture fallback. gogoanime episode IDs are full URLs `{scheme}://{host}/{slug}/{ep}` parsed with `urlparse` in `get_stream_url`.
- Miruro uses **Playwright** (not curl_cffi) to bypass Cloudflare on `miruro.tv/api/secure/pipe`. The pipe endpoint is behind Cloudflare WAF and only responds from a real browser JS context. Implementation: shared `Browser` instance (thread-safe), new `BrowserContext`+`Page` per call, `page.goto(miruro.tv)` to set CF cookies, then `page.evaluate(fetch)` to call the pipe. Search still uses AniList GraphQL via httpx (no CF, fast).
- **AniList outage resilience**: AniList GraphQL (`graphql.anilist.co`) occasionally returns the documented 403 "temporarily disabled due to severe stability issues" outage signal — this is a real upstream outage, NOT a bot-block, and cannot be bypassed by headers/Playwright. When AniList search fails, `MiruroScraper.search()` falls back to the miruro pipe's own `search` path (`_search_pipe`), which returns AniList-shaped results (`id` = AniList id). Results are scored client-side by `_search_score()` (exact match 1.0, substring 0.9, word-overlap ratio) across romaji/english/native titles. Note: during outages the pipe search may return a generic popular list ignoring the query term — the client-side scoring is what filters it down.
- Miruro stream resolution is unaffected by the AniList outage as long as search returns an AniList id — the `episodes`/`sources` pipe paths only need `anilistId`.
- Provider priority in `_PROVIDER_PRIORITY`: `["pewe", "kiwi", "bee", "bonk", "ally", "moo", "hop"]`. `pewe` (anidb.app CDN) is first — returns playable m3u8 URLs. `kiwi` uses `uwucdn.top` which is blocked by Cloudflare (403). The `eid` values are shared across providers (animepahe IDs), so priority ordering determines which CDN is used.
- Streams from `hls.anidb.app` are playable in mpv with `Referer: https://anidb.app/`. Verified via httpx (200, m3u8 content) and mpv (plays 1920x1080 h264 successfully).
- Playwright browser is shared at the class level (`MiruroScraper._browser`) — thread-safe. A new context+page is created per pipe call. Total time: ~5s for episodes, ~4-5s for sources (within 30s provider timeout).
- curl_cffi is no longer used by miruro (pipe rejects curl_cffi with 403 CF challenge). If curl_cffi is still in dependencies, it can be removed.
- Old scraper files `animepahe.py` and `anikoto.py` exist in repo but are NOT registered in `provider_manager.py` (kept out of the chain). `animepahe.py` has a `_capture_json` guard so non-JSON Playwright responses no longer crash its search.
- AllAnime `get_stream_url` now performs the **full client-crypto handshake in pure Python** (no Playwright needed) and is verified working end-to-end:
  - `aa-boot` HMAC token (`x-aa-boot` header) from build mask `jv("98")` = `a425a353...` (32 bytes).
  - Fresh bootstrap `GET api.mkissa.net/client-crypto/v1/bootstrap?buildId=81&k=k7` → `partB` + `epoch` (rotates every ~3 days; key = `partB XOR mask`). Must be fetched on every run.
  - `aaReq` = base64(`0x01` + iv[12] + AES-GCM(payload) + **tag[16]**). IV = first 12 bytes of `SHA-256(epoch:98:qh:ts:k7)`; payload `{v:1,ts,epoch,buildId:"98",qh,k:"k7"}` with `ts = floor(now/300000)*300000`. **Critical gotcha**: WebCrypto `encrypt()` returns ct+tag appended; in Python you must append `enc.tag` (missing it yields `AA_CRYPTO_STALE`).
  - POST to `api.mkissa.net/api` with the site's **exact F8 episode query text** (hash `2f563bb8...` — a custom/short query yields resolver crash `Cannot set properties of undefined`). Send `x-build-id:98` header + `extensions.persistedQuery.sha256Hash` = SHA-256 of the query text.
  - **Build id/mask migration**: the mkissa client rotates `buildId` and its 32-byte mask. The bootstrap endpoint returns `unknown_build_id` for stale build ids and `invalid_boot_token` for a valid id with the wrong mask. **The mask (and epoch arithmetic) must be verified against the live client bundle (`.../_app/immutable/chunks/C1lH2fxR.js`) whenever `_bootstrap()` silently returns `None`.** See above for the current build id/mask values.
  - Response `tobeparsed` blob decrypts (AES-256-GCM, tag in last 16 bytes) to the real `sourceUrls` JSON.
  - `--`-prefixed sourceUrls are AllAnime's hex remap obfuscation (`_HEX_REMAP` table) → `/apivtwo/clock?id=...` paths (clock API is 404/CF-gated, generally unusable). Decoded via the table, not kept.
  - AllAnime sourceUrls are iframe embeds (Filemoon/Vidnest = CF-gated; Ok.ru = playable m3u8 via `hlsManifestUrl` in its metadata JSON, handled in `embeds.py` by `_HLS_MANIFEST_ESC_RE`). `get_stream_url` falls back to resolving embeds via `embeds.resolve_embed`.
- `api.allanime.day/api` validates the same crypto as mkissa (returns `AA_CRYPTO_STALE` for stale keys, `NEED_CAPTCHA` under IP rate-limit bursts) but `mkissa.net` is the working host.

## Arabic pipeline (separate, untouched by English work)
- `ARABIC_PROVIDERS = ["arabic_api_primary", "arabic_api_backup"]` — implemented in `api.py` via `AnimeAPI` class
- Uses `api.py` endpoints and `get_streaming_servers()` / `build_mediafire_url()` for quality selection
- Kept strictly separated from English code — English and Arabic provider loops must never mix or cross-fallback

## Watch Together (Host-is-King protocol v2)
- Transport: Supabase Realtime Broadcast on `room:<code>` (public relay, no NAT issues). Protocol v2 (`PROTOCOL_VERSION=2`) hardens the layer on top: every host message is stamped with a monotonic `seq`, sender clock `ts`, and a media-generation `epoch`.
- **Host is the single source of truth.** Guests are pure mirrors: launched with `lock_controls=True` (mpv `--no-input-default-bindings` / VLC unbound hotkeys) and a per-poll `_enforce_authority()` pass re-asserts the last host pause state (overrides any local pause/seek unless the host granted `CONTROL`).
- **`seq`** dedupes/orders host broadcasts (guests drop `seq <= last_seen`). **`epoch`** is bumped on every `notify_load`; guests discard stale in-flight resolution/launch work from older epochs (a slow fetch can't clobber the new episode). **`ts`** feeds latency compensation.
- The heartbeat is an **authoritative snapshot** (media + time + playing + epoch), so guests self-heal even if a discrete PLAY/PAUSE/SEEK/LOAD is dropped. Media is shared by broadcasting the **host's resolved stream URL + headers** — guests launch the same source instantly, no duplicate scraping.
- **Seamless next/prev**: `play_episode` (host) kills the previous host player before relaunching (frees the room IPC socket / rc port) and captures `host._session`. The stale, still-blocked earlier `play_episode` releases and calls `notify_stop(session=old)` which is **ignored** (`notify_stop` is session-gated). `EV_STOP` is broadcast only on real session end; guests tear down via `_handle_stop`.
- Event set: `LOAD_MEDIA`, `PLAY`, `PAUSE`, `SEEK`, `HEARTBEAT`, `JOIN`, `LEAVE`, `STATE`, `MEMBERS`, `STATUS`, `KICK`, `CONTROL`, `TRANSFER_HOST`, `STOP`.
- Host and guest each pick mpv or VLC at session start (in `gui.py`, respects `settings.player` default).
- mpv host: `MpvIpcClient` on a unique Unix socket (`_unique_socket_path`). VLC host: `VlcIpcClient` over TCP on a free loopback port (`_pick_free_port`, range 42000-43000), selected before launch.
- VLC is launched with `--extraintf=rc --rc-host=127.0.0.1:<PORT>` (host, keeps Qt GUI) or `--intf=rc` is NOT used — guests use the same `--extraintf=rc` launch plus unbind hotkeys.
- **`--rc-quiet` is NOT available on VLC 3.x** (dropped after 2.x) — do not pass it; the rc interface doesn't echo commands in VLC 3, and responses are terminated by the `> ` prompt.
- VLC rc commands used: `get_time` (integer seconds), `status` (parse `( state playing|paused|stopped )`), `seek <int>` (absolute), `pause` (toggles), `play`, `quit`. `is_playing` is unreliable for pause detection (returns 1 while paused) — use `status`.
- `set_pause()` reads current state first, then sends `pause` only if mismatched (since `pause` toggles).
- Guest VLC control lock: `--key-play= --key-jump+short= --key-jump+medium= --key-jump+long= --key-jump+extrashort= --key-next= --key-prev= --key-stop= --key-quit=` (inline empty values). **Never** pass empty-string values as separate argv entries (`--key-play=` `""`) — VLC treats the `""` as an empty MRL and opens a DVD instead of the URL.
- Both `MpvIpcClient` and `VlcIpcClient` expose the same interface: `connect`, `close`, `get_time_pos`, `get_pause`, `set_pause`, `seek`, `connected`. Broadcasts stay player-agnostic JSON.

## Automated Skip-Intro/Outro (AniSkip)
- Module `auto_skip.py`: `fetch_skip_times(anilist_id, episode)` → `GET https://api.aniskip.com/v2/skip-times/{aid}/{ep}?types[]=op&types[]=ed&episodeLength=0` (5 s timeout, silent failure → `[]`). Parse fields: `results[].interval.startTime`/`endTime` (NOT `start`/`end`), `results[].skipType` ∈ `op`/`ed`.
- `SkipCache` (thread-safe, LRU max 256) + `get_skip_times()`/`prefetch_skip_times()` module helpers. Prefetch runs on a background daemon thread at play time (idempotent when cached) — zero launch latency.
- `AutoSkipMonitor(ipc, resolver, on_skip=None, osd=True, state_source=None)` daemon thread. **Two observation modes** so it never fights the Watch Host over mpv's single-threaded IPC command queue (mpv dispatches commands on ONE thread; a redundant get_property poller can starve the host's pause read under network stalls):
  - **Passive** (`state_source` = `WatchHost.poll_state`): the monitor reads `(time_pos, paused, ts)` from the snapshot the host sync loop already publishes — it issues ZERO get_property commands and reuses the host's shared `MpvIpcClient` for its rare seek/OSD (`auto_skip["ipc"] = host._ipc`). Used whenever a host room is active.
  - **Active** (no `state_source`, standalone): polls its own socket, but **fully suspends time-pos polling while paused** — only the pause flag is polled at `PAUSED_POLL_INTERVAL` (1.5 s). No skip can ever fire while paused.
  - Trigger rule (both modes): `start <= pos < end` AND (`last_pos < start` crossed forward OR `pos - start <= 1.5` fresh entry); seeks to `end`, OSD `show_text("Skipped Opening/Ending", 2000)`, calls `on_skip(end, skip_type)`. Re-arms once `pos >= end` or `pos < start`; `SKIP_COOLDOWN` (2.0 s) suppresses a second trigger right after a hard seek (mpv may briefly report the pre-seek position). Passive mode treats a snapshot older than `SOURCE_STALE` (5.0 s) as a dead poll and exits after `_MAX_DEAD_POLLS`; it never closes a shared client (`_owns_ipc=False`). Intervals resolve lazily (late fetch still lands).
- `WatchHost.poll_state()` returns `(time_pos, paused, ts)` under `_sync_lock`; `_sync_loop` reads **pause first with one immediate retry** (highest-priority state) before time-pos, so a stalled command queue can never silently drop a host pause transition from guests.
- Wired mpv-only and English-track-only in `gui.py play_episode` (gate: `player_choice == "mpv"` and `category != "ar_sub"`): builds `auto_skip = {"resolver": lambda: get_skip_times(aid, ep), "osd": bool}`; when a Watch Together host room is active, adds `"on_skip"` → `host.notify_auto_skip(target, label)`.
- `WatchHost.notify_auto_skip(target, label)` = Protocol v2 fast path mirroring a manual seek: broadcasts `EV_SEEK {"time": target}`, sets `_last_broadcast_seek_time`/`_last_polled_time` under `_sync_lock` (prevents double-broadcast), OSD to guests. It does NOT seek — the monitor already sought the host player.
- `player.py`: `_start_auto_skip(auto_skip)` starts the monitor beside the progress poller; both `_play_mpv` (single-rendition) and the multi-variant branch `stop()` + `join(timeout=3.0)` it after `proc.wait()`. `play_with_quality_fallback(..., auto_skip=None)` threads the config through. `auto_skip` keys: `{"resolver", "osd", "on_skip", "state_source", "ipc"}` — `ipc` is the shared host `MpvIpcClient` (not owned/closed) in host rooms, else the socket path string (owned client).
- Settings: `auto_skip_enabled=True`, `auto_skip_osd=True`; exposed via `get_settings` + `JSApi.auto_skip_status()`; SPA indicator `#skipText` in the top bar.
- **Global hardware-level host controls** (`global_hotkeys.py`): zero-dependency system-wide hotkeys that work while the host is tabbed out (full-screen game/browser). Backends are stdlib `ctypes` only — Windows `RegisterHotKey` + `PeekMessageW` (`MOD_NOREPEAT`), Linux `XGrabKey` + `XNextEvent` on `libX11.so.6` with `XAllowEvents(ReplayKeyboard)` (Wayland detected → unsupported), macOS Carbon `RegisterEventHotKey` best-effort. Each backend runs its OS event loop on a daemon thread, never blocking the GUI/sync/IPC.
- **Async startup (UI-freeze guard)**: `GlobalHotkeyManager.start()` only runs cheap local env checks (platform/session/DISPLAY) on the caller and hands ALL blocking backend setup — `XOpenDisplay`, key grabs, `RegisterHotKey` — to a fully detached daemon thread (`global-hotkeys-init`). The pywebview bridge thread (e.g. the "Host Room" click) never makes a blocking OS call, so the UI stays responsive even when the X server is slow/unreachable. Poll `status()` for `starting`/`active`/`inactive`; `start()` returns True once startup is *initiated* (final state is async). `stop()` can be called mid-startup safely.
- **X11 ctypes correctness (crash guards)**: set explicit `restype`/`argtypes` on every Xlib call — `XDefaultRootWindow` returns `c_ulong` (a default `c_int` truncates the 64-bit Window ID), and `XUngrabKeyboard`/`XCloseDisplay` take `Display*` as `c_void_p` (untyped ctypes truncates pointers to `c_int` → segfault). `XNextEvent` writes a **full `XEvent` union (~192 B)**, so `_XKeyEvent` carries trailing padding (`c_ubyte[128]`) to prevent a buffer overflow. `_X11Backend.stop()` sets the stop event and joins the pump thread (≤1s) before closing the display.
- Hotkey specs are `mods+key` strings (`ctrl+alt+p`, `ctrl+alt+right`, `f9`); `win`/`super`/`meta`/`cmd`/`command` are all canonicalized to `win`; unknown modifiers are rejected (`parse_hotkey` → `(None, None)`). Defaults live in `settings.py`: `global_hotkeys_enabled=True`, `global_hotkey_play_pause=ctrl+alt+p`, seek forward/back = `ctrl+alt+right`/`left`, next/prev episode = `ctrl+alt+up`/`down`, `global_skip_seconds=10`.
- `WatchHost.apply_global_action(action, skip_seconds)` is the fast path: it acts on the host player through thread-safe IPC and immediately broadcasts `PLAY`/`PAUSE`/`SEEK` (guests apply in `_on_message`, then heartbeat + `_enforce_authority` reconfirm). The sync loop shares its caches (`_last_broadcast_pause`, `_last_polled_time`, `_last_broadcast_seek_time`) with the hotkey thread under `_sync_lock` so they never double-broadcast or fight.
- GUI wiring: `host_room` calls `_start_global_hotkeys(host)` (returns `hotkeys` flag in the result; tracks `global_hotkeys_status()`), `leave_room` calls `_stop_global_hotkeys()`. `global_hotkeys_status()` reports `active`/`starting`/`error`. The listener callback `_on_global_hotkey` never blocks its daemon thread — every action is pushed onto a worker thread. Next/prev replays the current title's sibling episode via `_play_sibling_episode` (uses the `_playing` snapshot captured in `play_episode`, runs on a worker because `play_episode` blocks until the player exits).

## Key files
| File | Purpose |
|------|---------|
| `scrapers/provider_manager.py` | Provider chaining, `resolve_stream()` |
| `scrapers/miruro.py` | Miruro pipe decryption scraper (primary, working) |
| `scrapers/api_provider.py` | Consumet-protocol API scraper |
| `scrapers/mkissa.py` | Mkissa HTTP + Playwright scraper |
| `scrapers/gogoanime.py` | Gogoanime HTTP + Playwright scraper |
| `scrapers/hianime.py` | HiAnime `/ajax/` HTTP + Playwright scraper |
| `scrapers/allanime.py` | AllAnime GraphQL scraper (search/episodes verified) |
| `scrapers/embeds.py` | Shared embed gateway: `extract_media_url`, `resolve_embed` |
| `api.py` | Arabic provider `AnimeAPI` |
| `gui.py` | PyWebView GUI entry (`main`), `JSApi` JS bridge, resolve/abort pipeline |
| `ui/index.html` | Webview SPA frontend (loaded by gui.py) |
| `watch_together.py` | Watch Together: `SupabaseRealtime`, `MpvIpcClient`, `VlcIpcClient`, `WatchHost`/`WatchGuest`, `apply_global_action` |
| `global_hotkeys.py` | Zero-dependency global hotkeys (Windows `RegisterHotKey`, Linux `XGrabKey`, macOS Carbon), `GlobalHotkeyManager` |
| `player.py` | `PlayerManager`: mpv/VLC arg builders, `build_vlc_args` (rc + lock flags) |
| `playwright_bootstrap.py` | stdlib-only runtime Chromium auto-install (`ensure_playwright_chromium`) used by scrapers when the browser isn't bundled |

## External tooling
- **mpv** required for playback
- **ffmpeg** helper dependency
- **Playwright** (Chromium) for stream extraction on miruro (primary), mkissa, and gogoanime — browser shared at class level in MiruroScraper
- Set `ANI_API_BASE_URL` environment variable to point the `api` scraper at a self-hosted Consumet instance
- `cryptography` (not pycryptodome) is required by `allanime.py` for the best-effort `tobeparsed` AES-256-CTR decrypt

## Packaging / releases
- `build_desktop.py --target gui` builds the windowed PyWebView executable with `ui/` assets. `--exclude-module` adds exclusions, `--onedir` produces a portable folder, `--bundle-mpv` embeds mpv, `--zip` produces `dist/<exe>.zip`.
- Release binaries do **NOT** bundle the Playwright Chromium browser (that bloated old builds to 430 MB). The Playwright driver is still bundled via `--collect-all playwright`; on first stream use `playwright_bootstrap.ensure_playwright_chromium` downloads Chromium into the user's ms-playwright cache.
- `.github/workflows/build.yml` runs `build-gui` (windows/linux) plus a `release` job that uploads the AniNova assets. Windows bundles mpv; Linux relies on system mpv.

## Version / packaging
- Single source of version: `ani_cli_arabic/version.py:__version__`
- GUI package entry points: `ani-cli-ar-gui` / `aninova` (both `ani_cli_arabic.gui:main`)
- Desktop releases via `build_desktop.py` + `.github/workflows/build.yml` (GitHub Actions)

## Conventions
- No tests exist in the repo
- No formatter/linter config (no ruff, black, pylint config found)
- CI: `.github/workflows/build.yml` (GUI desktop builds on tag pushes)

## Execution guidelines

### Automatic Playwright fallback
- OpenCode is authorized and expected to use Playwright stealth browser rendering immediately when direct HTTP (httpx/requests) requests fail, return Cloudflare challenges (403/503), or encounter anti-bot protection.
- Do not wait for confirmation to use Playwright — fall back automatically from HTTP to headless Playwright to pass JS challenges and extract streams.

### Network & timeouts
- Enforce strict 5.0-second `asyncio.wait_for` timeout on direct HTTP stream resolution calls.
- For Playwright browser page loads, allow up to `_PROVIDER_TIMEOUT` (30.0s) since page rendering and JS execution take longer.
- All HTTP requests must include realistic browser headers (`User-Agent`, `Referer`, `Accept`) to minimize anti-bot blocking.
- Playwright browser is shared at the class level (`MiruroScraper._browser`) — thread-safe. A new context+page is created per pipe call.

### UI & error handling
- Print clean progress logs during provider evaluation: `[?] Attempting provider: {name}...`, `[✓] Stream found via {name}!`, `[✗] {name} returned no stream.`
- Never let `NoneType` values reach string operations (`.lower()`, `.strip()`, etc.) — always sanitize optional input with a safe default before use.

## Permanent Developer Directives

### Safety & Creative Autonomy

1. **Safety First (Sanity Check)**
   - Before implementing any requested feature or bugfix, verify that it does not introduce breaking changes, performance regressions, or platform incompatibilities (especially between Linux and Windows).
   - If a requested change is problematic or unsafe, DO NOT implement it blindly. Instead, skip or modify it safely, and explain the technical reasoning in the task summary.

2. **Creative Autonomy & Quality-of-Life Improvements**
   - You are empowered to introduce extra UX enhancements, code refactors, or subtle quality-of-life additions related to the user's current goal, even if not explicitly requested.
   - Any added proactive features must be clearly highlighted in the final output summary so the user is fully aware of them.
