"""Shared, lazily-started Playwright runtime for browser-backed scrapers.

Every scraper used to spin up its own ``sync_playwright()`` + ``chromium.launch()``
per call — a multi-second fixed cost on every episode click, even for fast
HTTP-first providers. This module keeps a single headless Chromium alive on a
dedicated worker thread and serializes all page operations through it, which is
the one layout that is actually safe with Playwright's sync API (all Playwright
work happens on the thread that started it).

* **Lazy**: importing this module costs nothing; the browser (and the
  ``ensure_playwright_chromium`` download check) is only started the first time
  a scraper that actually needs it calls :func:`browser_run`.
* **Thread-safe**: callers may submit jobs from any thread; jobs run one at a
  time on the worker thread.
* **Centralized**: browser-path bootstrap (``configure_browsers_path`` +
  ``ensure_playwright_chromium``) lives here, so HTTP-only scrapers never touch
  Playwright code.
"""
import queue
import sys
import threading
import time
from typing import Callable, Dict, Optional

from ._http_log import log_http_error, log_timing

_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
]
_LAUNCH_TIMEOUT = 60.0
# How long a job may wait in the queue for its turn on the single worker
# thread before the caller gives up. This is separate from the *execution*
# budget: once the worker starts the job, the caller gets the full ``timeout``
# (see ``_PlaywrightRuntime.run``).
_QUEUE_WAIT_TIMEOUT = 20.0
_DEFAULT_JOB_TIMEOUT = 30.0

_STOP = object()

# UI hook: gui.py registers a callback here so Linux missing-deps failures can
# surface as a user-facing toast. Decoupled via setter to avoid a circular
# import (scrapers must never import the GUI module).
_problem_listener: Optional[Callable] = None


def set_launch_problem_listener(fn: Optional[Callable]) -> None:
    """Register ``fn(message)`` invoked once per detected launch problem."""
    global _problem_listener
    _problem_listener = fn


def _notify_launch_problem(message: str) -> None:
    fn = _problem_listener
    if fn is not None:
        try:
            fn(str(message))
        except Exception:
            pass


class _PlaywrightRuntime:

    # Minimum seconds between Chromium recovery attempts (install + relaunch)
    _RECOVER_COOLDOWN = 60.0

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._launch_trigger = threading.Event()
        self._launched = threading.Event()
        self._browser = None
        self._pw = None
        self._launch_error: Optional[str] = None
        self._deps_hint: Optional[str] = None
        self._last_recover = 0.0
        self._thread = threading.Thread(
            target=self._worker, name="pw-runtime", daemon=True
        )
        self._thread.start()

    def _launch_browser(self) -> bool:
        """Bootstrap (auto-installing Chromium when missing) and launch the
        shared browser. Worker-thread only. Returns True when connected."""
        try:
            from ..playwright_bootstrap import (
                configure_browsers_path,
                ensure_playwright_chromium,
                resolve_chromium_executable,
            )
            configure_browsers_path()
            # A system/distro Chromium (env override or /usr/bin/chromium)
            # removes the need for the Playwright-managed download entirely.
            exe = resolve_chromium_executable()
            if exe:
                print(f"[browser] using system Chromium: {exe}")
            else:
                ensure_playwright_chromium()
            from playwright.sync_api import sync_playwright
            t0 = time.monotonic()
            pw = sync_playwright().start()
            self._browser = pw.chromium.launch(
                headless=True,
                args=_LAUNCH_ARGS,
                executable_path=exe,
            )
            self._pw = pw
            log_timing("browser:launch", time.monotonic() - t0)
            self._launch_error = None
            self._deps_hint = None
            return True
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            self._launch_error = f"playwright install exited {code}"
            log_http_error("browser", "install+launch", "chromium",
                           exc=None, note=self._launch_error)
        except Exception as exc:
            self._launch_error = f"{type(exc).__name__}: {exc}"
            log_http_error("browser", "install+launch", "chromium", exc=exc,
                           note="playwright runtime start")
        # Raw failure reason on stdout for terminal log tracing (after
        # classification so the actionable hint, when present, is included).
        self._classify_launch_failure()
        print(f"[browser] launch FAILED: {self._launch_error}")
        if getattr(self, "_deps_hint", None):
            print(f"[browser] fix: {self._deps_hint}")
        return False

    def _classify_launch_failure(self):
        """Detect Linux missing-system-deps failures and surface an actionable
        hint (stderr + registered UI listener)."""
        # Always defined, even for instances built without __init__ (tests).
        self._deps_hint = getattr(self, "_deps_hint", None)
        from ..playwright_bootstrap import (
            looks_like_missing_deps, install_deps_hint,
        )
        if not looks_like_missing_deps(self._launch_error):
            return
        self._deps_hint = install_deps_hint()
        sys.stderr.write(
            "\n"
            "==============================================================\n"
            "[!] Chromium cannot start: Linux system libraries are missing.\n"
            "    Fix it by running this once in your terminal:\n\n"
            f"        {self._deps_hint}\n\n"
            "==============================================================\n\n"
        )
        try:
            _notify_launch_problem(self._deps_hint)
        except Exception:
            pass

    def _try_recover(self) -> bool:
        """Chromium vanished or crashed mid-session: force a reinstall and
        relaunch, cooldown-gated so a broken environment cannot loop."""
        now = time.monotonic()
        if now - self._last_recover < self._RECOVER_COOLDOWN:
            return False
        self._last_recover = now
        sys.stderr.write(
            "[browser] Chromium missing or crashed - reinstalling...\n"
        )
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None
        self._browser = None
        return self._launch_browser()

    def _worker(self):
        # Wait until someone actually needs the browser (true lazy start).
        self._launch_trigger.wait()
        if not self._launch_browser():
            pass  # error surfaced per-job below; recovery stays possible
        self._launched.set()

        while True:
            job = self._queue.get()
            if job is _STOP:
                break
            fn, res_q, started, cancel_event = job
            if cancel_event is not None and cancel_event.is_set():
                # Aborted while still queued: skip execution entirely so the
                # worker slot is freed instead of wasting it on dead work.
                started.set()
                res_q.put(("ok", None))
                continue
            started.set()
            if self._browser is None or not self._browser.is_connected():
                # Auto-heal: reinstall Chromium + relaunch instead of failing
                # every job until restart (guards miruro/mkissa/hianime).
                if not self._try_recover():
                    hint = getattr(self, "_deps_hint", None)
                    err = RuntimeError(self._launch_error or "browser not available")
                    if hint:
                        # Surface the actionable fix through the provider chain
                        err = RuntimeError(f"{err} — fix: {hint}")
                    res_q.put(("err", err))
                    continue
            try:
                res_q.put(("ok", fn(self._browser)))
            except Exception as exc:
                res_q.put(("err", exc))

    def run(
        self,
        fn: Callable,
        timeout: float = _DEFAULT_JOB_TIMEOUT,
        cancel_event: Optional[threading.Event] = None,
    ):
        """Execute ``fn(browser)`` on the runtime thread and return its result.

        The ``timeout`` budget is measured from when the job *starts executing*
        on the worker, not from submission — queue-wait time behind other jobs
        does not consume the execution budget. ``cancel_event`` (when provided
        and set) aborts a still-queued job before it runs.

        Returns None if the browser failed to launch, the job never got a turn
        within ``_QUEUE_WAIT_TIMEOUT``, or the job exceeded ``timeout``; raises
        the job's exception otherwise.
        """
        if cancel_event is not None and cancel_event.is_set():
            return None
        self._launch_trigger.set()
        if not self._launched.wait(timeout=_LAUNCH_TIMEOUT):
            return None
        # NOTE: a stale _launch_error must NOT gate jobs here — the worker's
        # recovery pass (Chromium reinstall + relaunch) decides per-job.
        res_q: queue.Queue = queue.Queue(maxsize=1)
        started = threading.Event()
        self._queue.put((fn, res_q, started, cancel_event))
        if not started.wait(timeout=_QUEUE_WAIT_TIMEOUT):
            return None
        try:
            kind, value = res_q.get(timeout=timeout)
        except queue.Empty:
            return None
        if kind == "err":
            raise value
        return value

    def close(self):
        try:
            self._queue.put(_STOP)
        except Exception:
            pass


_runtime = None
_runtime_lock = threading.Lock()


def _get_runtime() -> _PlaywrightRuntime:
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = _PlaywrightRuntime()
    return _runtime


def browser_run(
    fn: Callable,
    timeout: float = _DEFAULT_JOB_TIMEOUT,
    cancel_event: Optional[threading.Event] = None,
):
    """Run ``fn(browser)`` on the shared lazy browser.

    ``fn`` receives the shared ``browser`` instance and is responsible for
    creating/closing its own context + page (contexts are cheap; the browser
    launch is the expensive part we reuse). Use :func:`new_page_job` for the
    common single-page pattern. ``cancel_event`` (optional) aborts the job
    before it starts if set while it is still queued.
    """
    return _get_runtime().run(fn, timeout=timeout, cancel_event=cancel_event)


def new_page_job(
    fn: Callable,
    *,
    user_agent: Optional[str] = None,
    viewport: Optional[dict] = None,
    init_script: Optional[str] = None,
    timeout: float = _DEFAULT_JOB_TIMEOUT,
):
    """Build a job that runs ``fn(page)`` with a fresh context per call.

    The fresh context guarantees isolation between callers (no shared cookies /
    storage) while the browser process is reused. ``fn`` returns the result.
    """
    def _job(browser):
        kwargs = {}
        if user_agent:
            kwargs["user_agent"] = user_agent
        if viewport:
            kwargs["viewport"] = viewport
        ctx = browser.new_context(**kwargs)
        try:
            if init_script:
                ctx.add_init_script(init_script)
            page = ctx.new_page()
            return fn(page)
        finally:
            ctx.close()

    return _job


def browser_page(
    fn: Callable,
    *,
    user_agent: Optional[str] = None,
    viewport: Optional[dict] = None,
    init_script: Optional[str] = None,
    timeout: float = _DEFAULT_JOB_TIMEOUT,
    cancel_event: Optional[threading.Event] = None,
):
    """Run ``fn(page)`` on a fresh context over the shared browser.

    Thin wrapper combining :func:`new_page_job` + :func:`browser_run`.
    """
    return browser_run(
        new_page_job(fn, user_agent=user_agent, viewport=viewport,
                     init_script=init_script),
        timeout=timeout,
        cancel_event=cancel_event,
    )


# ---------------------------------------------------------------------------
# Persistent warm pages
# ---------------------------------------------------------------------------
# A fresh-context-per-call layout is perfect for isolation but terrible for
# Cloudflare-gated sites: every call starts with cold cookies and pays a full
# ``page.goto(...)`` warmup (multi seconds on miruro.tv). A *warm page* is one
# long-lived context+page kept alive on the worker between jobs — CF cookies
# stay hot and subsequent pipe calls skip navigation entirely.
#
# All access happens inside jobs on the single worker thread, so the registry
# below needs no lock of its own.

_WARM_PAGES: Dict[str, dict] = {}
_WARM_DEFAULT_MAX_AGE = 1200.0  # re-navigate after 20 min to keep cookies hot


def _drop_warm_page(key: str):
    entry = _WARM_PAGES.pop(key, None)
    if entry is None:
        return
    ctx = entry.get("ctx")
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass


def browser_warm_page(
    fn: Callable,
    *,
    key: str,
    url: str,
    user_agent: Optional[str] = None,
    goto_wait: str = "networkidle",
    goto_timeout: float = 25000.0,
    max_age: float = _WARM_DEFAULT_MAX_AGE,
    timeout: float = _DEFAULT_JOB_TIMEOUT,
    cancel_event: Optional[threading.Event] = None,
):
    """Run ``fn(page, fresh)`` on a persistent per-key page over the browser.

    ``fresh`` is True when the page was just created for this call — use it to
    perform one-time setup (route handlers, init scripts). The page is created
    + navigated to ``url`` on first use (or when older than ``max_age``), then
    reused with hot cookies in between. When ``fn`` raises, the warm page is
    destroyed so the next call starts from a clean context.
    """
    def _job(browser):
        entry = _WARM_PAGES.get(key)
        page = None
        fresh = False
        stale = True
        if entry is not None:
            p = entry.get("page")
            try:
                if p is not None and not p.is_closed():
                    page = p
                    age = time.monotonic() - entry.get("ts", 0.0)
                    stale = age > max_age
            except Exception:
                page = None
        if page is None:
            _drop_warm_page(key)
            ctx = browser.new_context(user_agent=user_agent) if user_agent \
                else browser.new_context()
            page = ctx.new_page()
            _WARM_PAGES[key] = {"page": page, "ctx": ctx,
                                "ts": time.monotonic()}
            fresh = True
            stale = False  # just created; caller navigates below exactly once

        try:
            if fresh or stale:
                t0 = time.monotonic()
                page.goto(url, wait_until=goto_wait, timeout=goto_timeout)
                log_timing("browser:warm_goto", time.monotonic() - t0)
                _WARM_PAGES[key]["ts"] = time.monotonic()
            return fn(page, fresh)
        except Exception:
            # Broken page/state: drop it so the next job gets a clean slate.
            _drop_warm_page(key)
            raise

    return browser_run(_job, timeout=timeout, cancel_event=cancel_event)