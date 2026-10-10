"""Which app is the user dictating into?"""

from __future__ import annotations

from dataclasses import dataclass

import psutil
import win32gui
import win32process


@dataclass
class WindowContext:
    hwnd: int = 0
    process: str = ""
    title: str = ""
    elevated: bool = False  # an admin window: Windows blocks synthetic input from normal apps


TERMINALS = {
    "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe",
    "wezterm-gui.exe", "alacritty.exe", "mintty.exe",
}


def active_window() -> WindowContext:
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = ""
        elevated = False
        if pid:
            try:
                process = psutil.Process(pid).name().lower()
            except psutil.AccessDenied:
                # Only an elevated (or protected) process refuses this to a normal app.
                elevated = True
            except psutil.Error:
                pass
        return WindowContext(hwnd, process, title, elevated)
    except Exception:
        return WindowContext()


def is_elevated() -> bool:
    """Is Flow itself running as administrator?"""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
