"""System-wide (hardware-level) global hotkeys for AniNova Watch Together.

Zero-dependency implementation that talks to the OS's native global-hotkey
mechanism through ``ctypes`` (stdlib only, no third-party packages):

* Windows : ``RegisterHotKey`` + a ``PeekMessageW`` pump. Hotkeys are
            registered OS-wide (``WM_HOTKEY``) and fire even while the host
            is alt-tabbed into a full-screen game. ``MOD_NOREPEAT`` stops
            auto-repeat spam.
* Linux   : ``XGrabKey`` + ``XNextEvent`` on the X11 display (``libX11``).
            On a captured keypress the event is replayed to the original
            window via ``XAllowEvents(ReplayKeyboard)`` so the focused app
            still receives the key. Wayland sessions cannot grab globally
            and are reported as unsupported.
* macOS   : Carbon ``RegisterEventHotKey`` + ``InstallEventHandler``
            (best-effort; requires the app to be granted Accessibility).

Each backend runs its OS event loop on a dedicated daemon thread so the GUI
thread, the mpv/VLC IPC socket and the Watch Together sync loop are never
blocked. Hotkey presses are dispatched to a caller-provided callback which
must be non-blocking (spawn a worker thread for anything slow).
"""

import ctypes
import os
import re
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Hotkey spec parsing (shared, platform-agnostic)
# ---------------------------------------------------------------------------

_KEY_ALIASES = {
    "left": "left",
    "right": "right",
    "up": "up",
    "down": "down",
    "space": "space",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "insert": "insert",
    "delete": "delete",
}

_FKEY_RE = re.compile(r"^f(\d{1,2})$")


def parse_hotkey(spec: str) -> Tuple[Optional[Set[str]], Optional[str]]:
    """Parse ``"ctrl+alt+p"`` into ``({modifiers}, key)``.

    Modifiers are ``ctrl``/``control``, ``alt``/``option``, ``shift``,
    ``win``/``super``/``meta``/``cmd``. Returns ``(None, None)`` for an
    invalid spec so callers can skip the binding safely.
    """
    if not spec:
        return None, None
    parts = [p.strip().lower() for p in str(spec).split("+") if p.strip()]
    if not parts:
        return None, None
    mods: Set[str] = set()
    for p in parts[:-1]:
        if p in ("ctrl", "control"):
            mods.add("ctrl")
        elif p in ("alt", "option"):
            mods.add("alt")
        elif p == "shift":
            mods.add("shift")
        elif p in ("win", "super", "meta", "cmd", "command"):
            mods.add("win")
        else:
            return None, None
    key = _canonical_key(parts[-1])
    if key is None:
        return None, None
    return mods, key


def _canonical_key(k: str) -> Optional[str]:
    k = k.strip().lower()
    if len(k) == 1 and k.isalnum():
        return k
    if k in _KEY_ALIASES:
        return _KEY_ALIASES[k]
    m = _FKEY_RE.match(k)
    if m and 1 <= int(m.group(1)) <= 24:
        return k
    return None


# ---------------------------------------------------------------------------
# Platform-specific key/modifier encodings
# ---------------------------------------------------------------------------

# Windows virtual key codes.
_WIN_VK = {
    "space": 0x20,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "insert": 0x2D,
    "delete": 0x2E,
}

_WIN_MODS = {"ctrl": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008}

# X11 keysym names (XStringToKeysym).
_X11_KEYSYM = {
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "space": "space",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "insert": "Insert",
    "delete": "Delete",
}

# X11 modifier masks (Xlib).
_X11_MODS = {"ctrl": 0x0004, "shift": 0x0001, "alt": 0x0008, "win": 0x0020}

# macOS Carbon virtual keycodes for the letters we allow.
_MAC_VK = {
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4,
    "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35,
    "q": 12, "r": 15, "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
    "y": 16, "z": 6,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22,
    "7": 26, "8": 28, "9": 25,
    "space": 49,
    "left": 123, "right": 124, "up": 126, "down": 125,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "delete": 117, "insert": 114,
}

# Carbon modifier masks.
_MAC_MODS = {"ctrl": 1 << 12, "alt": 1 << 11, "shift": 1 << 9, "win": 1 << 8}


def _win_vk(key: str) -> Optional[int]:
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    return _WIN_VK.get(key)


def _win_mods(mods: Set[str]) -> int:
    value = 0
    for m in mods:
        value |= _WIN_MODS.get(m, 0)
    return value


def _x11_keysym(key: str) -> str:
    if len(key) == 1:
        return key
    if key in _X11_KEYSYM:
        return _X11_KEYSYM[key]
    m = _FKEY_RE.match(key)
    if m:
        return "F" + m.group(1)
    return key


def _x11_mods(mods: Set[str]) -> int:
    value = 0
    for m in mods:
        value |= _X11_MODS.get(m, 0)
    return value


def _mac_vk(key: str) -> Optional[int]:
    if len(key) == 1 and key.isalpha():
        return _MAC_VK.get(key.lower())
    return _MAC_VK.get(key)


def _mac_mods(mods: Set[str]) -> int:
    value = 0
    for m in mods:
        value |= _MAC_MODS.get(m, 0)
    return value


# ---------------------------------------------------------------------------
# Windows backend
# ---------------------------------------------------------------------------

class _WindowsBackend:
    """RegisterHotKey + PeekMessageW pump on a daemon thread."""

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    MOD_NOREPEAT = 0x4000
    PM_REMOVE = 0x0001

    def __init__(self, bindings: Dict[str, str], callback: Callable[[str], None]):
        self.bindings = dict(bindings)
        self.callback = callback
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ids: Dict[int, str] = {}
        self._error = ""

    def start(self) -> bool:
        if sys.platform != "win32":
            self._error = "Windows backend requires a Windows system"
            return False
        try:
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            # Decode every binding before any OS registration happens.
            for action, spec in self.bindings.items():
                mods, key = parse_hotkey(spec)
                vk = _win_vk(key) if key else None
                if mods is None or vk is None:
                    self._error = f"Invalid hotkey spec: {spec!r}"
                    return False
                self._ids[hash((mods, vk)) & 0xFFFFFFFF] = action
            self._user32 = user32
            self._wintypes = wintypes
            self._thread = threading.Thread(
                target=self._pump, daemon=True, name="global-hotkeys-win"
            )
            self._thread.start()
            return True
        except Exception as exc:
            self._error = f"Windows hotkey backend failed: {exc}"
            return False

    def _register(self) -> None:
        from ctypes import wintypes

        for action, spec in self.bindings.items():
            mods, key = parse_hotkey(spec)
            vk = _win_vk(key) if key else None
            if mods is None or vk is None:
                continue
            hk_id = hash((mods, vk)) & 0xFFFFFFFF
            mod_mask = _win_mods(mods) | self.MOD_NOREPEAT
            # hWnd=NULL registers the hotkey against this (pumping) thread.
            if self._user32.RegisterHotKey(
                None, hk_id, mod_mask, int(vk)
            ) == 0:
                err = ctypes.get_last_error()
                self._error = f"RegisterHotKey failed for {spec!r} (err={err})"

    def _pump(self) -> None:
        try:
            from ctypes import wintypes
        except Exception:
            return
        self._register()
        self._MSG = wintypes.MSG
        while not self._stop.is_set():
            msg = self._MSG()
            while self._user32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, self.PM_REMOVE
            ):
                if msg.message == self.WM_QUIT:
                    return
                if msg.message == self.WM_HOTKEY:
                    action = self._ids.get(int(msg.wParam))
                    if action:
                        self._emit(action)
            time.sleep(0.02)

    def _emit(self, action: str) -> None:
        try:
            cb = self.callback
            if cb:
                cb(action)
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        try:
            for hk_id in list(self._ids):
                self._user32.UnregisterHotKey(None, hk_id)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Linux / X11 backend
# ---------------------------------------------------------------------------

class _X11Backend:
    """XGrabKey + XNextEvent loop on a daemon thread (X11 only).

    A captured keypress is replayed to the focused window via
    ``XAllowEvents(ReplayKeyboard)`` so the app the user is tabbed into still
    receives the key (important for full-screen games / terminals).
    """

    KeyPress = 2
    GrabModeAsync = 0
    ReplayKeyboard = 3
    CurrentTime = 0
    KeyPressMask = 1
    LockMask = 0x0002
    Mod2Mask = 0x0010

    def __init__(self, bindings: Dict[str, str], callback: Callable[[str], None]):
        self.bindings = dict(bindings)
        self.callback = callback
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._key_to_action: Dict[int, str] = {}
        self._lib = None
        self._dpy = None
        self._error = ""

    def start(self) -> bool:
        if not os.environ.get("DISPLAY"):
            self._error = "No X11 DISPLAY available for global hotkeys"
            return False
        try:
            lib = ctypes.CDLL("libX11.so.6")
        except OSError as exc:
            self._error = f"libX11.so.6 not loadable: {exc}"
            return False
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        dpy = lib.XOpenDisplay(None)
        if not dpy:
            self._error = "XOpenDisplay failed (no X11 connection)"
            return False
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XStringToKeysym.restype = ctypes.c_ulong
        lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
        lib.XKeysymToKeycode.restype = ctypes.c_uint
        lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XGrabKey.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_uint,
            ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        lib.XAllowEvents.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong]
        lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.XPending.argtypes = [ctypes.c_void_p]
        lib.XPending.restype = ctypes.c_int
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XUngrabKeyboard.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XUngrabKeyboard.restype = ctypes.c_int
        root = lib.XDefaultRootWindow(dpy)
        self._lib = lib
        self._dpy = dpy
        self._root = root

        grabbed = 0
        for action, spec in self.bindings.items():
            mods, key = parse_hotkey(spec)
            if mods is None or key is None:
                continue
            keysym = lib.XStringToKeysym(_x11_keysym(key).encode("utf-8"))
            keycode = lib.XKeysymToKeycode(dpy, keysym)
            if keycode == 0:
                continue
            self._key_to_action[keycode] = action
            mod_mask = _x11_mods(mods)
            for variant in (mod_mask, mod_mask | self.LockMask | self.Mod2Mask):
                lib.XGrabKey(
                    dpy, int(keycode), variant, root, 1,
                    self.GrabModeAsync, self.GrabModeAsync,
                )
                grabbed += 1
        if not grabbed:
            self._error = "No X11 keygrabs could be registered"
            lib.XCloseDisplay(dpy)
            self._dpy = None
            return False
        lib.XFlush(dpy)
        self._thread = threading.Thread(
            target=self._pump, daemon=True, name="global-hotkeys-x11"
        )
        self._thread.start()
        return True

    def _pump(self) -> None:
        from ctypes import byref

        while not self._stop.is_set():
            if self._dpy:
                while self._lib.XPending(self._dpy):
                    event = _XKeyEvent()
                    self._lib.XNextEvent(self._dpy, byref(event))
                    if event.type != self.KeyPress:
                        continue
                    action = self._key_to_action.get(int(event.keycode))
                    if not action:
                        continue
                    # Replay the key to the focused window so the grabbed key
                    # still reaches the app the host is tabbed into.
                    self._lib.XAllowEvents(self._dpy, self.ReplayKeyboard, self.CurrentTime)
                    self._lib.XFlush(self._dpy)
                    self._emit(action)
            time.sleep(0.02)

    def _emit(self, action: str) -> None:
        try:
            cb = self.callback
            if cb:
                cb(action)
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=1.0)
        if self._lib and self._dpy:
            try:
                self._lib.XUngrabKeyboard(self._dpy, self.CurrentTime)
                self._lib.XCloseDisplay(self._dpy)
            except Exception:
                pass
        self._dpy = None


class _XKeyEvent(ctypes.Structure):
    """mirrors Xlib's XKeyEvent (first member of the XEvent union).

    ``XNextEvent`` writes a **full** ``XEvent`` union (~192 bytes on 64-bit
    X11) into the caller's buffer, so the struct carries extra trailing
    padding to prevent a heap/stack buffer overflow. The named fields keep
    their exact Xlib offsets.
    """

    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("x_root", ctypes.c_int),
        ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("keycode", ctypes.c_uint),
        ("same_screen", ctypes.c_int),
        ("_pad", ctypes.c_ubyte * 128),
    ]


# ---------------------------------------------------------------------------
# macOS (Carbon) backend — best effort
# ---------------------------------------------------------------------------

class _MacosBackend:
    """Carbon RegisterEventHotKey + InstallEventHandler.

    Requires the app to run an event loop (pywebview does) and, on modern
    macOS, Accessibility permission for the terminal/app. Any failure degrades
    to ``start() -> False`` with a clear reason."""

    kEventClassKeyboard = 0x6B657962  # 'keyb'
    kEventHotKeyPressed = 5
    kEventParamDirectObject = 0x2D2D2D2D  # '----'
    typeEventHotKeyID = 0x686B6964  # 'hkid'

    def __init__(self, bindings: Dict[str, str], callback: Callable[[str], None]):
        self.bindings = dict(bindings)
        self.callback = callback
        self._carbon = None
        self._refs = {}
        self._handlers = []
        self._active = False
        self._error = ""

    def start(self) -> bool:
        if sys.platform != "darwin":
            self._error = "macOS backend requires macOS"
            return False
        try:
            carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
            self._carbon = carbon
            carbon.RegisterEventHotKey.restype = ctypes.c_int
            carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
            carbon.InstallEventHandler.restype = ctypes.c_int
            carbon.GetEventParameter.restype = ctypes.c_int

            target = carbon.GetApplicationEventTarget()
            if not target:
                self._error = "GetApplicationEventTarget failed"
                return False

            Handler = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
            )

            def make_handler(action: str) -> Handler:
                def handler(next_handler, the_event, user_data):
                    try:
                        self.callback(action)
                    except Exception:
                        pass
                    return 0

                return Handler(handler)

            spec = _EventTypeSpec(self.kEventClassKeyboard, self.kEventHotKeyPressed)
            for action, hotkey in self.bindings.items():
                mods, key = parse_hotkey(hotkey)
                vk = _mac_vk(key) if key else None
                if mods is None or vk is None:
                    continue
                hk_id = hash(action) & 0xFFFFFFFF
                hkid = _EventHotKeyID(0x414E4E56, hk_id)  # 'ANNV' signature
                handler = make_handler(action)
                handler_ref = ctypes.c_void_p()
                carbon.InstallEventHandler(
                    target, handler, 1, ctypes.byref(spec), None,
                    ctypes.byref(handler_ref),
                )
                hotkey_ref = ctypes.c_void_p()
                status = carbon.RegisterEventHotKey(
                    int(vk), _mac_mods(mods), hkid, target, 0,
                    ctypes.byref(hotkey_ref),
                )
                if status != 0:
                    self._error = f"RegisterEventHotKey failed for {hotkey!r} (status={status})"
                    continue
                self._handlers.append(handler)
                self._refs[action] = hotkey_ref
            self._active = bool(self._refs)
            return self._active
        except Exception as exc:
            self._error = f"macOS hotkey backend failed: {exc}"
            return False

    def stop(self) -> None:
        self._active = False
        if self._carbon:
            try:
                self._carbon.UnregisterEventHotKey = self._carbon.UnregisterEventHotKey
            except Exception:
                pass
            for ref in list(self._refs.values()):
                try:
                    self._carbon.UnregisterEventHotKey(ctypes.byref(ref))
                except Exception:
                    pass
            self._refs.clear()
            self._handlers.clear()


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint), ("eventKind", ctypes.c_uint)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint), ("id", ctypes.c_uint)]


# ---------------------------------------------------------------------------
# Fallback backend (unsupported platform / session)
# ---------------------------------------------------------------------------

class _UnsupportedBackend:
    def __init__(self, reason: str):
        self._error = reason
        self._active = False

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Public manager
# ---------------------------------------------------------------------------

class GlobalHotkeyManager:
    """Tracks global hotkeys and dispatches presses to ``callback(action)``.

    ``bindings`` maps an action name (e.g. ``"play_pause"``) to a hotkey spec
    (e.g. ``"ctrl+alt+p"``). ``callback`` is invoked on a daemon thread and
    must be non-blocking.

    Startup is **asynchronous**: ``start()`` only runs cheap local checks
    (platform / session env vars, never touching the OS) and then hands the
    real backend setup — X11 display connection + key grabs, Windows
    ``RegisterHotKey``, macOS Carbon — to a fully detached daemon thread.
    The calling thread (normally the GUI/bridge thread, e.g. the "Host Room"
    click) never performs a blocking OS call, so the UI stays responsive even
    when the X server is slow or unreachable. Poll ``status()`` for the live
    ``starting``/``active``/``inactive`` state.
    """

    def __init__(self, bindings: Dict[str, str], callback: Callable[[str], None]):
        self.bindings = dict(bindings)
        self.callback = callback
        self._lock = threading.Lock()
        self._backend = None
        self._pending_backend = None
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._state = "inactive"  # "starting" | "active" | "inactive"
        self.active = False
        self.error = ""

    def _precheck(self) -> str:
        """Cheap, purely-local failure checks; never touches the OS."""
        if sys.platform in ("win32", "darwin"):
            return ""
        if sys.platform.startswith("linux"):
            session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
            if os.environ.get("WAYLAND_DISPLAY") or session == "wayland":
                return ("Wayland session detected; global hotkeys need X11 "
                        "(XGrabKey). Log into an X11 session or set DISPLAY.")
            if not os.environ.get("DISPLAY"):
                return "No X11 DISPLAY available for global hotkeys"
        return ""

    def start(self) -> bool:
        """Initiate global-hotkey startup on a detached daemon thread.

        Returns True when the listener has been (or is being) started; the
        final backend state is reported asynchronously via ``status()``.
        Never blocks on the caller.
        """
        with self._lock:
            if self._state == "active":
                return True
            if self._state == "starting":
                return True
            reason = self._precheck()
            if reason:
                self.error = reason
                self._state = "inactive"
                return False
            backend = _build_backend(self.bindings, self.callback)
            if backend is None:
                self.error = f"Global hotkeys unsupported on {sys.platform}"
                self._state = "inactive"
                return False
            self._pending_backend = backend
            self._cancel.clear()
            self._state = "starting"
            self.active = False
            self.error = ""
        thread = threading.Thread(
            target=self._start_worker, args=(backend,),
            daemon=True, name="global-hotkeys-init",
        )
        self._thread = thread
        thread.start()
        return True

    def _start_worker(self, backend) -> None:
        """Run the backend's (potentially blocking) setup on this thread."""
        try:
            ok = backend.start()
            with self._lock:
                if self._cancel.is_set():
                    try:
                        backend.stop()
                    except Exception:
                        pass
                    return
                if ok:
                    self._backend = backend
                    self.active = True
                    self.error = ""
                    self._state = "active"
                else:
                    self.error = (getattr(backend, "_error", "") or
                                  "backend failed to start")
                    self._state = "inactive"
        except Exception as exc:
            with self._lock:
                self.error = f"global hotkeys init failed: {exc}"
                self._state = "inactive"
        finally:
            with self._lock:
                self._pending_backend = None

    def status(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "starting": self._state == "starting",
            "error": self.error or "",
        }

    def stop(self) -> None:
        with self._lock:
            self._cancel.set()
            self._state = "inactive"
            self.active = False
            backend = self._backend
            self._backend = None
        if backend is not None:
            try:
                backend.stop()
            except Exception:
                pass

    def __repr__(self) -> str:
        if self._state == "active":
            return "<GlobalHotkeyManager active>"
        if self._state == "starting":
            return "<GlobalHotkeyManager starting...>"
        return f"<GlobalHotkeyManager inactive: {self.error}>"


def _build_backend(bindings, callback):
    if sys.platform == "win32":
        return _WindowsBackend(bindings, callback)
    if sys.platform == "darwin":
        return _MacosBackend(bindings, callback)
    if sys.platform.startswith("linux"):
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        if os.environ.get("WAYLAND_DISPLAY") or session == "wayland":
            return _UnsupportedBackend(
                "Wayland session detected; global hotkeys need X11 (XGrabKey). "
                "Log into an X11 session or set DISPLAY."
            )
        return _X11Backend(bindings, callback)
    return _UnsupportedBackend(f"Platform {sys.platform!r} not supported")
