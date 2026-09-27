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


TERMINALS = {
    "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe",
    "wezterm-gui.exe", "alacritty.exe", "mintty.exe",
}


def active_window() -> WindowContext:
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid).name().lower() if pid else ""
        return WindowContext(hwnd, process, title)
    except Exception:
        return WindowContext()
