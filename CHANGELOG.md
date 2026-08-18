# Changelog

All notable changes to **ani-cli-arabic** (ani-cli-ar), a terminal-based anime streaming client with Arabic subtitle support.

Format follows [Keep a Changelog](https://keepachangelog.com/) conventions. This project does not follow strict SemVer; minor and alpha/beta suffixes denote ongoing work.

---

## [Unreleased]

---

## [v1.4.1] - 2026-08-18

### 🐛 Bug Fixes & Stability
- **Settings modal contrast fix**: native `<select>`/`<option>` controls ignored page CSS and rendered with the OS light palette on pywebview engines (WebView2 / GTK), making dropdown text unreadable. Added `color-scheme: dark` on `:root` (dark native controls app-wide), `appearance: none` on the modal's selects (so their dark background actually applies) with a custom chevron arrow, explicit dark `option` styling (`#1e1e2e` bg / `#f0f0f0` text, accent highlight for hover/checked), and higher-contrast hover (`#5a5a6e` border) / focus (accent border + glow ring) states across all 8 settings sections.

---

## [v1.4.0] - 2026-08-18

### ⚙️ Comprehensive Settings Menu (GUI)
- New ⚙ **Settings** button in the top nav opens a dedicated modal with 8 sections: Playback, Auto-Skip, Pre-Roll, Watch Together & Hotkeys, Player & Downloads, Language & Provider, Appearance, and Privacy — recreating every core `ani-cli-ar` option plus new GUI-first ones.
- Backend settings bridge rewritten: `get_settings()` now returns all **25** settings keys (properly typed), new `save_settings(patch)` validates/whitelists keys, clamps ints (pre-roll 1–120 s, hotkey step 1–300 s), drops invalid enum values without failing the save, and persists atomically to the same `~/.ani-cli-arabic/database/config.json` the core CLI consumes. New `reset_settings()` + `SettingsManager.reset_to_defaults()` restore factory defaults from the menu.
- Live side effects: toggling/editing global-hotkey settings re-arms the system-wide listener immediately when a Watch Together host room is active; `default_quality` and `player` now pre-select the details-page quality/player dropdowns; the Auto-Skip status pill updates on save.
- **Themes**: 18 accent palettes (full CLI theme-name parity + the default sunrise look) apply instantly via CSS variables. The stored default theme is now `sunrise` so existing users keep the exact same look on upgrade (the CLI falls back to its own blue default regardless).

### 🎨 Branding — Linux builds unified as AniNova
- The Linux release asset is now **`AniNova-v<version>-Linux.tar.gz`** (was `ani-cli-ar-gui-linux.tar.gz`), versioned from the git tag with a `version.py` fallback — matching the Windows naming convention.
- `build_desktop.py` defaults the GUI executable name to **`AniNova`** (both OSes build with `--exe-name AniNova`); builder banner and portable-zip README rebranded.
- New `assets/aninova.desktop` (Name/Exec/Icon → AniNova/aninova) replaces the old `ani-cli-ar.desktop`; `scripts/install_linux.sh` installs the `AniNova` binary and `aninova` icon; bundle icon renamed `aninova.png`.
- README (EN/AR) asset tables, `launch.sh` comment, and AGENTS.md packaging docs updated. pip entry points (`ani-cli-ar-gui` / `aninova`) and the Windows asset name are unchanged.

---

## [v1.3.1] - 2026-08-18

### 🔧 Auto-Skip vs. Watch Together — IPC polling collision fix
- **Root cause**: mpv dispatches IPC commands on a single thread. The v1.3.0 `AutoSkipMonitor` opened its own socket and polled `time-pos`/`pause` every 0.5 s *in parallel with* the Watch Host sync loop. Under network stalls (HLS buffering, hard seeks) the extra commands could starve the host's `get_pause()` read, so a host pause transition was missed and guests kept playing — the room fell out of sync.
- **Centralized polling (host rooms)**: the monitor is now **passive** — it reads `(time_pos, paused, ts)` from the snapshot the host sync loop already publishes (`WatchHost.poll_state()`, updated under `_sync_lock`) and reuses the host's shared `MpvIpcClient` for its rare seek/OSD. It issues **zero** `get_property` commands of its own, restoring the pre-v1.3.0 IPC traffic level exactly.
- **Pause broadcast hardened**: `_sync_loop` now reads `pause` **first** and retries it once before reading `time-pos`, so a pause transition is captured even if the command queue is momentarily backed up.
- **Suspend on pause**: in standalone (non-room) playback the active monitor **fully suspends time-pos polling while paused**, checking only the pause flag at a relaxed 1.5 s cadence; no skip can ever fire while paused.
- **Skip cooldown**: a 2.0 s cooldown after each skip prevents a double seek / double `EV_SEEK` broadcast when a hard seek briefly reports the pre-seek position.
- Empirically verified against real mpv: concurrent multi-client polling causes no drops, and the passive monitor + real `_sync_loop` skip, pause-broadcast, and resume-broadcast correctly.

---

## [v1.3.0] - 2026-08-18

### 🎬 Automated Skip-Intro/Outro
- New `auto_skip.py` module: fetches OP/ED timestamps from the AniSkip community API (`api.aniskip.com/v2/skip-times`), caches them in a bounded thread-safe LRU (`SkipCache`, 256 entries), and prefetches them on a background daemon thread at play time — zero launch latency.
- `AutoSkipMonitor` (daemon thread) samples the host mpv `time-pos` over the room socket every 0.5 s, auto-seeks past the opening/ending once it crosses the skip window (1.5 s trigger window, re-arms after the interval or an intentional rewind before it), and flashes an mpv OSD ("Skipped Opening/Ending"). Intervals are resolved lazily, so a late-arriving fetch still lands mid-playback; the monitor self-exits when the player socket drops.
- English track only (AniSkip keys off AniList ids the Arabic pipeline never carries), mpv only, gated by `player_choice == "mpv"` and `category != "ar_sub"`. New settings: `auto_skip_enabled=True`, `auto_skip_osd=True` (exposed via `get_settings` + `auto_skip_status()`); status indicator `#skipText` in the top bar.
- Watch Together: the host's auto-skip announces to every guest via `WatchHost.notify_auto_skip()` — a Protocol v2 `EV_SEEK` broadcast that mirrors a manual seek exactly (guests seek in sync, sync-loop caches updated under `_sync_lock`, no double-broadcast, no new protocol surface).

### ⚡ Global Hotkeys — UI freeze fix + crash guards
- **Async startup**: `GlobalHotkeyManager.start()` now only does cheap local checks on the caller and runs the full backend setup (X11 display connect, key grabs, `RegisterHotKey`, Carbon) on a fully detached daemon thread. The "Host Room" click no longer blocks on the GUI/bridge thread — no more "Application is not responding", even if the X server is slow or unreachable.
- `start()` returns once startup is *initiated*; live state is reported via `status()` (`starting`/`active`/`inactive`) and surfaced in the UI through `global_hotkeys_status()` (`starting` flag added). `stop()` is safe to call mid-startup.
- Fixed three latent X11 ctypes crashes that could segfault the whole process: `XDefaultRootWindow` now declares its `c_ulong` return (a default `c_int` truncated the 64-bit Window ID), `XUngrabKeyboard` declares `c_void_p` argtypes (untyped ctypes truncated the `Display*` pointer), and `_XKeyEvent` gained trailing padding so `XNextEvent`'s full ~192-byte `XEvent` union write can't overflow the buffer.
- `_X11Backend.stop()` joins the pump thread (≤1s) before closing the display to avoid a close-while-reading race.

---

## [v1.2.0] - 2026-08-18

### ⌨️ Global Hardware-Level Host Controls
- System-wide Watch Together host hotkeys that work while the app is tabbed out (full-screen game/browser): play/pause, seek forward/backward, next/previous episode.
- Zero-dependency implementation (`global_hotkeys.py`, stdlib `ctypes` only): Windows `RegisterHotKey`, Linux `XGrabKey` (X11; Wayland auto-detected → disabled), macOS Carbon best-effort. Each backend runs its own daemon event-loop thread.
- Hotkey specs are `mods+key` (e.g. `ctrl+alt+p`); defaults are configurable via settings: `global_hotkey_play_pause`, `seek_forward`/`seek_backward`, `next_episode`/`prev_episode`, `global_skip_seconds=10`.
- Actions route through `WatchHost.apply_global_action()` — a Protocol v2 fast path that drives the host player via thread-safe IPC and immediately broadcasts `PLAY`/`PAUSE`/`SEEK` to guests; the sync loop shares its broadcast caches under `_sync_lock` so it never double-broadcasts or fights a hotkey action.
- Next/prev replays the current title's sibling episode using the `_playing` snapshot captured at playback start.
- UI status: `host_room` now reports a `hotkeys` flag (backend live or not); `leave_room` cleanly stops the listener.

---

## [v1.1.0] - 2026-08-18

### 🔒 Watch Together — Host-is-King protocol v2
- Every host broadcast is stamped with a monotonic `seq`, sender clock `ts`, and media `epoch`; guests drop stale/duplicate messages (`seq <= last_seen`) and stale-epoch media work.
- New per-poll `_enforce_authority()` pass: guests re-assert the last host pause state between heartbeats, so any local pause/seek is immediately overridden (host is the absolute source of truth).
- The host heartbeat is now an authoritative snapshot (media + time + playing + epoch), so guests self-heal even when a discrete PLAY/PAUSE/SEEK/LOAD is dropped.
- Seamless next/prev transitions: `epoch` bumps on every load and stale in-flight resolution/launch work from older episodes is discarded (a slow fetch can no longer clobber the current episode); the host kills its previous player before relaunching so the room IPC socket / rc port is always free.
- Session-gated `notify_stop(session=...)`: a stale stop from a superseded play call can no longer tear down a newer episode.
- New `STOP` event: guests tear down their player cleanly when the host ends playback.

---

## [v1.9.5] - 2026-08-03 (Stable Release)

Stable release consolidating the 1.9.5 alpha line.

### 🚀 New Features & Options
- Room roster / member list with live status badges (synced / buffering / drift) broadcast to all members in Watch Together.
- Host authority model: the host is the single source of truth for playback; guests apply host-driven state.
- Kick / promote (co-host) / control-toggle member management from the host.
- Host transfer to a guest member.

### 🐛 Bug Fixes & Stability
- Watch Together connection hardening: missing-package, missing-credentials, timeouts, channel creation, websocket subscribe, and `send_broadcast` failures now print full `traceback.format_exc()` diagnostics instead of failing silently.
- Guard against launching the player / resolving streams when no active media is loaded (empty `title`/`episode`/`url` payloads).
- Provider chain now rejects raw player-metadata dicts / JSON blobs passed as `stream_url` and falls back to the next provider.
- Stream URL extraction un-escapes html/js entities (`\u0026`, `\&quot;`, `&amp;`, `\/`) and only returns validated `http(s)` links.
- ok.ru / OKCDN embed resolution now correctly pulls `hlsManifestUrl` (playable manifest) instead of raw metadata.

### ⚡ Performance & Player Optimizations
- MPV imported arguments include `--demuxer-max-bytes=150M` and `--demuxer-readahead-secs=30`.
- Added `set_speed` to both `MpvIpcClient` and `VlcIpcClient` to support rate-based synchronization.
- VLC `--rc-quiet` gated on VLC 4.x+ (avoids unknown-option warnings on VLC 3.x).

---

## [v1.9.5a3] - 2026-08-03

### 🐛 Bug Fixes & Stability
- Version-pinning bump for the pre-release 1.9.5 line.

---

## [v1.9.5a2] - 2026-08-03

### 🐛 Bug Fixes & Stability
- Wave 2 pre-release corrections toward the 1.9.5 stable.

---

## [v1.9.5a1] - 2026-08-03

### 🚀 New Features & Options
- Watch Together member management: room roster tracking, member kick, promote to co-host, and transfer-host actions.
- Host-authority sync: guests follow host playback unconditionally.
- Status reporting from guests (drift / playing / buffering) driving live member badges.

---

## [v1.9.4] - 2026-08-02

### 🐛 Bug Fixes & Stability
- Added Windows TCP IPC fallback for the mpv Watch Together socket (`AF_UNIX` unavailable on some Windows Python builds).
- Miruro stream resolution fixed (browser pipe fallback robustness).
- Normalized local language state across provider switching.

### ⚡ Performance & Player Optimizations
- Watch Together IPv4 loopback IPC transport used on Windows.

---

## [v1.9.4b2] - 2026-08-01

### 🐛 Bug Fixes & Stability
- Fix Miruro stream resolution and normalize local language state.
- Beta corrections prior to the 1.9.4 release.

---

## [v1.9.4b1] - 2026-08-01

### 🚀 New Features & Options
- `--test` update flag to opt into beta/pre-release update checks.

### 🐛 Bug Fixes & Stability
- Beta-test release for the 1.9.4 line; changelog-less internal release.

---

## [v1.9.4-dev] - 2026-08-01

### 🐛 Bug Fixes & Stability
- Dev bump introducing `--test` update support and Miruro fixes.

---

## [v1.9.3] - 2026-08-01

### 🚀 New Features & Options
- Session tracking with live heartbeats.
- `--stats` flag: printable streaming-history summary.
- Error analytics with rich diagnostic details (player / provider / quality / error action attributes).

### ⚡ Performance & Player Optimizations
- VLC support added to Watch Together with per-session player selection (mpv or VLC).
- Host-only playback controls enforced for Watch Together guests.

---

## [v1.9.2] - 2026-07-31

### 🐛 Bug Fixes & Stability
- Version bump separating the Watch Together rewrite from telemetry work.

---

## [v1.9.1] - 2026-07-31

### 🚀 New Features & Options
- Watch Together rooms over Supabase Realtime Broadcast + mpv IPC (first release).
- Hardcoded default Supabase credentials so rooms work out of the box.

### 🐛 Bug Fixes & Stability
- Migrated to the **async** Supabase client: supabase-py 2.x only supports Realtime on the async client; the sync client's `channel()` raised `NotImplementedError`. Realtime now runs on a dedicated asyncio loop thread with a sync channel wrapper (`subscribe` / `send_broadcast` / `unsubscribe`).

---

## [v1.9.0] - 2026-07-31

### 🚀 New Features & Options
- **Preferred provider** setting in the TUI.
- **Player selection** across mpv / VLC with `ask` as the default.
- Analytics backend (serverless + `api/index.py` deployment) for opt-in telemetry; fixed `usage_logs` RLS policies.
- `install.sh` installer; package renamed to `ani-cli-ar`.

### ⚡ Performance & Optimizations
- Playwright-based Miruro scraper replacing direct HTTP (bypasses Cloudflare on the secure pipe).
- Performance optimizations documented in `OPTIMIZATIONS.md`.
- Shared HTTP connection pooling and API discovery cache.

---

## [v1.8.9] - 2026-07-31

### 🚀 New Features & Options
- Dub language support.

### 🐛 Bug Fixes & Stability
- Retry / rate-limit handling in the provider chain.
- Update-flag plumbing for the updater.

---

## [v1.8.5] - 2026-07-26

### 🚀 New Features & Options
- Native English scraper pipeline (gogoanime / hi-anime / miruro-backed chain).
- Multiple media-player support (choose your preferred player).

### 🐛 Bug Fixes & Stability
- Working state snapshot tagged `v1.8.5-working`.

---

## [v1.8.4] - 2026-04-27 (approx.)

### 🧩 Features & Options
- Donation support section in the UI and README.
- README polish (Arabic layout, navigation/gap styling).

---

## [v1.8.3] - 2026-04-08

### 🐛 Bug Fixes & Stability
- Fixes #5.
- FIXED Downloads (aria2c / IDM flows).
- FIXED Favorites system.

---

## [v1.8.2] - 2026-03-20

### 🚀 New Features & Options
- Robust dependency installation with multi-mirror support and auto package-manager detection.
- Mandatory auto-updates with UI lockout when an update is pending.

### 🐛 Bug Fixes & Stability
- Fixed yt-dlp binary download path (bypasses pip resolution issues).
- Fixed MPV release parsing that could mistakenly download FFmpeg archives.
- Secured error handling, consolidated duplicate UI logic, improved cross-platform robustness.
- Removed redundant comments, AI slop, and unused imports.

### ⚡ Performance & Player Optimizations
- Cleaner project structure (removed stale `/out` folder and duplicate files).

---

## [v1.8.1] - 2026-01-08

### 🐛 Bug Fixes & Stability
- Fixed `fzf` integration on Windows.

---

## [v1.8] - 2026-01-07

### 🚀 New Features & Options
- **MAJOR CHANGES** — new rewrite documented in the changelog narrative.
- Star-history chart in README.

### 🐛 Bug Fixes & Stability
- Fixed PyPI publishing workflow.
- Fixed AUR workflow.
- Python 3.12 recommended (3.13+ may hit numpy compilation issues).

---

## [v1.7.3] - 2026-01-06

### 🚀 New Features & Options
- **MAJOR CHANGES** — added many features; see release notes.

---

## [v1.7.2] - 2026-01-04

### 🐛 Bug Fixes & Stability
- Fixes #3.
- General Linux compatibility — confirmed on kitty, konsole, and GNOME terminal.
- Cleaner folder-structure rework.

### ⚡ Performance & Player Optimizations
- Smoother overall terminal experience.

---

## [v1.7] - 2026-01-02

### 🚀 New Features & Options
- Redesigned GitHub page.
- Showcase section in README; new showcase video.

### 🐛 Bug Fixes & Stability
- Fixed mpv failing to launch on Linux Mint (community-reported).
- Fixed showcase-video resolution issue.
- Fixed release workflow (changelog special characters) and build config (license / classifiers).

---

## [v1.6] - 2025-12-28

### 🚀 New Features & Options
- Reworked API and UI components for improved state management and update handling.

---

## [v1.5.x] - 2025-12-26

### 🐛 Bug Fixes & Stability
- v1.5.3: merge/cleanup release.
- Earlier 1.5: enhanced version parsing and display in `version_info.txt`.

---

## [v1.2.x] - 2025-12-23/25

### 🚀 New Features & Options
- **Download support**: aria2c (fast) + IDM integration on Windows.
- **MAL integration**: `Relevant` (R) option fetches currently-airing anime via the Jikan API with SFW filtering.
- **Watch history**: watched episodes marked with an eye icon.
- **Next/Previous/Replay** menu after watching or downloading.

### 🐛 Bug Fixes & Stability
- v1.2.1: workflow fix.

---

## [v1.3.x] - 2025-12-25

### 🐛 Bug Fixes & Stability
- 1.3.3: corrected terminology in the Arabic README for terminal usage.

---

## [v1.0.0] - 2025-11-26

### 🚀 New Features & Options
- Initial public release.
- Rich TUI built with the Rich library.
- 17 color themes.
- Multiple quality options (1080p / 720p / 480p).
- Batch episode downloading.
- Trailer support (YouTube).
- Search (English / Japanese / Arabic titles), trending, top-rated, genre and studio browsing.
- Watch history, favorites system, and episode tracking.
- Discord Rich Presence with anime posters.
- Automatic update checker (can be disabled).
- Dependency auto-installer.
- CLI mode (`-i "title"`) plus TUI; cross-platform Windows / Linux.

---

[v1.8.2]: https://github.com/np4abdou1/ani-cli-arabic/releases/tag/v1.8.2
[v1.8.3]: https://github.com/np4abdou1/ani-cli-arabic/releases/tag/v1.8.3
[v1.8.5]: https://github.com/np4abdou1/ani-cli-arabic/releases/tag/v1.8.5-working
[v1.9.0]: https://github.com/np4abdou1/ani-cli-arabic/releases/tag/v1.9.0
[v1.9.1]: https://github.com/np4abdou1/ani-cli-arabic/releases/tag/v1.9.1
[v1.9.4]: https://github.com/np4abdou1/ani-cli-arabic/releases/tag/v1.9.4
[v1.9.5]: https://github.com/np4abdou1/ani-cli-arabic/releases/tag/v1.9.5