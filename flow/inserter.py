"""Putting text into the focused app (clipboard paste with restore) and reading the selection."""

from __future__ import annotations

import ctypes
import logging
import struct
import threading
import time

import pywintypes
import win32clipboard as wcb
import win32con

from . import winkeys

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32")
_user32.GetClipboardSequenceNumber.restype = ctypes.c_uint

# Formats that are synthesized by Windows or are GDI handles we can't round-trip.
_SKIP_FORMATS = {
    win32con.CF_TEXT, win32con.CF_OEMTEXT, win32con.CF_LOCALE, win32con.CF_BITMAP,
    win32con.CF_METAFILEPICT, win32con.CF_ENHMETAFILE, win32con.CF_PALETTE,
    win32con.CF_OWNERDISPLAY, win32con.CF_DSPTEXT, win32con.CF_DSPBITMAP,
    win32con.CF_DSPMETAFILEPICT, win32con.CF_DSPENHMETAFILE, win32con.CF_HDROP, 17,  # CF_DIBV5
}
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


def _seq() -> int:
    return _user32.GetClipboardSequenceNumber()


class _Clipboard:
    def __enter__(self):
        for _ in range(40):
            try:
                wcb.OpenClipboard()
                return self
            except pywintypes.error:
                time.sleep(0.025)
        raise RuntimeError("Clipboard is busy")

    def __exit__(self, *exc):
        wcb.CloseClipboard()


def snapshot() -> list[tuple[int, bytes | str]]:
    items: list[tuple[int, bytes | str]] = []
    total = 0
    with _Clipboard():
        fmt = 0
        while True:
            fmt = wcb.EnumClipboardFormats(fmt)
            if not fmt:
                break
            if fmt in _SKIP_FORMATS:
                continue
            try:
                data = wcb.GetClipboardData(fmt)
            except (pywintypes.error, TypeError, SystemError):
                continue
            if isinstance(data, (bytes, str)):
                total += len(data)
                if total > _MAX_SNAPSHOT_BYTES:
                    log.info("Clipboard too large to preserve")
                    break
                items.append((fmt, data))
    return items


def restore(items: list[tuple[int, bytes | str]]) -> None:
    with _Clipboard():
        wcb.EmptyClipboard()
        for fmt, data in items:
            try:
                wcb.SetClipboardData(fmt, data)
            except pywintypes.error:
                continue


def _set_text(text: str) -> None:
    with _Clipboard():
        wcb.EmptyClipboard()
        wcb.SetClipboardData(win32con.CF_UNICODETEXT, text)
        # Keep dictated text out of Win+V clipboard history and cloud clipboard.
        zero = struct.pack("<I", 0)
        wcb.SetClipboardData(wcb.RegisterClipboardFormat("ExcludeClipboardContentFromMonitorProcessing"), zero)
        wcb.SetClipboardData(wcb.RegisterClipboardFormat("CanIncludeInClipboardHistory"), zero)
        wcb.SetClipboardData(wcb.RegisterClipboardFormat("CanUploadToCloudClipboard"), zero)


def _get_text() -> str:
    with _Clipboard():
        if wcb.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return wcb.GetClipboardData(win32con.CF_UNICODETEXT)
    return ""


class Inserter:
    def __init__(self, restore_delay: float = 0.4):
        self.restore_delay = restore_delay
        self._lock = threading.Lock()

    def insert(self, text: str, mode: str = "paste", timeline=None) -> None:
        mark = timeline.mark if timeline is not None else (lambda _name: None)
        if not text:
            return
        mark("insert_start")
        winkeys.wait_modifiers_released()
        mark("keys_released")
        if mode == "type":
            winkeys.type_text(text)
            mark("insert_sent")
            return
        with self._lock:
            try:
                saved = snapshot()
            except Exception:
                log.exception("Could not snapshot clipboard")
                saved = None
            _set_text(text)
            ours = _seq()
            winkeys.send_chord(winkeys.VK_CONTROL, ord("V"))
            mark("insert_sent")
            time.sleep(self.restore_delay)
            if saved is not None and _seq() == ours:
                try:
                    restore(saved)
                except Exception:
                    log.exception("Could not restore clipboard")
            mark("clipboard_restored")

    def capture_selection(self) -> str:
        """Copies the current selection via Ctrl+C and restores the clipboard afterwards."""
        winkeys.wait_modifiers_released()
        with self._lock:
            try:
                saved = snapshot()
            except Exception:
                saved = None
            before = _seq()
            winkeys.send_chord(winkeys.VK_CONTROL, ord("C"))
            deadline = time.monotonic() + 0.6
            while time.monotonic() < deadline and _seq() == before:
                time.sleep(0.02)
            if _seq() == before:
                return ""
            time.sleep(0.05)
            try:
                text = _get_text()
            except Exception:
                text = ""
            if saved is not None:
                try:
                    restore(saved)
                except Exception:
                    log.exception("Could not restore clipboard")
            return text
