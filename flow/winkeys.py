"""Win32 keyboard plumbing: a WH_KEYBOARD_LL hook thread and SendInput helpers."""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from ctypes import wintypes
from typing import Callable

from .hotkeys import MASK, SUPPRESS, ComboCapture, HotkeyEngine

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_QUIT = 0x0012
LLKHF_EXTENDED = 0x01
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
VK_CONTROL, VK_RETURN = 0x11, 0x0D
VK_MASK = 0xE8  # unassigned; used to stop Win/Alt releases from opening Start / menus
VK_PROBE = 0xE9  # unassigned; the watchdog's "is the hook alive?" keystroke
WM_REINSTALL = 0x0400 + 77  # WM_APP + n, posted to the hook thread
WATCHDOG_SECONDS = 30
FLOW_MAGIC = 0x464C4F57  # dwExtraInfo tag on our own injected input

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

_SPECIAL = {
    0x10: "lshift", 0xA0: "lshift", 0xA1: "rshift",
    0x11: "lctrl", 0xA2: "lctrl", 0xA3: "rctrl",
    0x12: "lalt", 0xA4: "lalt", 0xA5: "ralt",
    0x5B: "lwin", 0x5C: "rwin", 0x5D: "menu",
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x13: "pause", 0x14: "capslock",
    0x1B: "esc", 0x20: "space", 0x21: "pageup", 0x22: "pagedown", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down", 0x2C: "printscreen",
    0x2D: "insert", 0x2E: "delete", 0x90: "numlock", 0x91: "scrolllock",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
    0xAD: "volumemute", 0xAE: "volumedown", 0xAF: "volumeup",
    0xB0: "nexttrack", 0xB1: "prevtrack", 0xB3: "playpause",
}


def vk_name(vk: int) -> str:
    if vk in _SPECIAL:
        return _SPECIAL[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    if 0x60 <= vk <= 0x69:
        return f"num{vk - 0x60}"
    if 0x70 <= vk <= 0x87:
        return f"f{vk - 0x6F}"
    return f"vk{vk:02x}"


_NAME_TO_VK: dict[str, int] = {}
for _vk in range(1, 256):
    _NAME_TO_VK.setdefault(vk_name(_vk), _vk)
_NAME_TO_VK.update({"lshift": 0xA0, "lctrl": 0xA2, "lalt": 0xA4})


def is_key_down(name: str) -> bool | None:
    vk = _NAME_TO_VK.get(name)
    if vk is None:
        return None
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=FLOW_MAGIC)
    return inp


def send_inputs(inputs: list[INPUT]) -> None:
    if not inputs:
        return
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        log.warning("SendInput sent %d of %d events (error %d)", sent, len(inputs), ctypes.get_last_error())


def send_chord(*vks: int) -> None:
    downs = [_key(vk) for vk in vks]
    ups = [_key(vk, flags=KEYEVENTF_KEYUP) for vk in reversed(vks)]
    send_inputs(downs + ups)


def type_text(text: str) -> None:
    """Types text as unicode keystrokes (fallback for apps that block paste)."""
    events: list[INPUT] = []
    text = text.replace("\r\n", "\n")
    for char in text:
        if char == "\n":
            events += [_key(VK_RETURN), _key(VK_RETURN, flags=KEYEVENTF_KEYUP)]
            continue
        data = char.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            events += [
                _key(scan=unit, flags=KEYEVENTF_UNICODE),
                _key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            ]
    for i in range(0, len(events), 200):
        send_inputs(events[i:i + 200])
        time.sleep(0.005)


_MODIFIER_VKS = (0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C)


def wait_modifiers_released(timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_VKS):
            return True
        time.sleep(0.01)
    return False


def focus_window(hwnd: int) -> bool:
    """Brings a window to the foreground. Windows only allows this for the process that produced
    the most recent input, so a no-op key is injected first."""
    send_inputs([_key(VK_MASK), _key(VK_MASK, flags=KEYEVENTF_KEYUP)])
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    return user32.GetForegroundWindow() == hwnd


class KeyboardHook:
    """Runs a low-level keyboard hook on its own thread and feeds the HotkeyEngine."""

    def __init__(self, engine: HotkeyEngine, on_reinstall=None):
        self.engine = engine
        self.on_reinstall = on_reinstall
        self.capture: ComboCapture | None = None
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._proc = HOOKPROC(self._callback)
        self._reinject: queue.Queue[tuple[int, int, int] | None] = queue.Queue()
        self._injector = threading.Thread(target=self._inject_loop, daemon=True, name="flow-inject")
        self._hook = None
        self._seen = threading.Event()
        self._stopping = False
        self._reinstalls = 0

    def start(self) -> None:
        self._injector.start()
        self._thread = threading.Thread(target=self._run, daemon=True, name="flow-keyboard-hook")
        self._thread.start()
        self._ready.wait(5)
        threading.Thread(target=self._watchdog, daemon=True, name="flow-hook-watchdog").start()

    def stop(self) -> None:
        self._stopping = True
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._reinject.put(None)

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        if not self._install():
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_REINSTALL:
                self._install()
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)

    def _install(self) -> bool:
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc,
                                              kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            log.error("SetWindowsHookExW failed (error %d)", ctypes.get_last_error())
            return False
        log.info("Keyboard hook installed")
        return True

    def _watchdog(self) -> None:
        """Windows silently removes a low-level hook whose callback times out. Probe for that.

        A synthetic key is injected every WATCHDOG_SECONDS; if the callback does not see it, the
        hook is gone and gets reinstalled on the hook thread.
        """
        while not self._stopping:
            time.sleep(WATCHDOG_SECONDS)
            if self._stopping or not self._thread_id:
                continue
            self._seen.clear()
            send_inputs([_key(VK_PROBE), _key(VK_PROBE, flags=KEYEVENTF_KEYUP)])
            if self._seen.wait(1.0):
                continue
            log.warning("Keyboard hook stopped receiving events; reinstalling")
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            user32.PostThreadMessageW(self._thread_id, WM_REINSTALL, 0, 0)
            self._reinstalls += 1
            if self.on_reinstall:
                self.on_reinstall(self._reinstalls)

    def _callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == 0:
            kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            self._seen.set()  # proof for the watchdog that the hook is still alive
            if kb.vkCode == VK_PROBE:
                return 1
            if kb.dwExtraInfo != FLOW_MAGIC:
                try:
                    if self._handle(kb, w_param):
                        return 1
                except Exception:  # never let an exception escape into the OS hook chain
                    log.exception("Keyboard hook handler failed")
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _handle(self, kb: KBDLLHOOKSTRUCT, w_param: int) -> bool:
        name = vk_name(kb.vkCode)
        down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        capture = self.capture
        if capture is not None:
            capture.feed(name, down)
            return True
        if down:
            self.engine.prune(is_key_down)
            return self.engine.key_down(name)
        flags = self.engine.key_up(name)
        if flags & SUPPRESS:
            return True
        if flags & MASK:
            # Swallow the real release and replay it after a dummy key so Windows doesn't
            # treat it as a lone Win/Alt tap (which would open Start or a menu bar).
            self._reinject.put((kb.vkCode, kb.scanCode, kb.flags & LLKHF_EXTENDED))
            return True
        return False

    def _inject_loop(self) -> None:
        while True:
            item = self._reinject.get()
            if item is None:
                return
            vk, scan, extended = item
            flags = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if extended else 0)
            send_inputs([_key(VK_MASK), _key(VK_MASK, flags=KEYEVENTF_KEYUP), _key(vk, scan, flags)])


def run_on_hook_capture(hook: KeyboardHook, on_done: Callable[[str], None]) -> None:
    def done(combo: str) -> None:
        hook.capture = None
        on_done(combo)

    hook.capture = ComboCapture(done)
