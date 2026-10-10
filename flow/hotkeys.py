"""Global hotkey state machine (pure logic, fed by the low-level keyboard hook).

Behaviour, mirroring Wispr Flow:
- Hold the dictate combo to record; releasing any key of the combo stops and transcribes.
- A quick tap (shorter than ``tap_threshold``) is discarded; two taps in a row start hands-free mode.
- The hands-free combo also starts hands-free mode; pressing a combo again stops it.
- While holding dictate, adding keys to form the command combo switches to command mode.
- Esc cancels any recording. Pressing an unrelated key while holding cancels (the user is using
  a different shortcut such as Ctrl+Win+Left).
"""

from __future__ import annotations

import threading
import time
from typing import Callable

SUPPRESS = 1
MASK = 2

GENERIC = {
    "lctrl": "ctrl", "rctrl": "ctrl",
    "lalt": "alt", "ralt": "alt",
    "lshift": "shift", "rshift": "shift",
    "lwin": "windows", "rwin": "windows",
}
MODIFIERS = {"ctrl", "alt", "shift", "windows"}
ALIASES = {
    "win": "windows", "super": "windows", "meta": "windows", "cmd": "windows",
    "control": "ctrl", "escape": "esc", "option": "alt", "return": "enter",
    "left ctrl": "lctrl", "right ctrl": "rctrl", "left alt": "lalt", "right alt": "ralt",
    "altgr": "ralt", "left shift": "lshift", "right shift": "rshift",
    "left windows": "lwin", "right windows": "rwin",
}
_ORDER = ["ctrl", "lctrl", "rctrl", "alt", "lalt", "ralt", "shift", "lshift", "rshift",
          "windows", "lwin", "rwin"]


def generic(key: str) -> str:
    return GENERIC.get(key, key)


def is_modifier(key: str) -> bool:
    return generic(key) in MODIFIERS


def parse_combo(text: str) -> frozenset[str]:
    keys = []
    for part in (text or "").lower().split("+"):
        part = part.strip()
        if part:
            keys.append(ALIASES.get(part, part))
    return frozenset(keys)


def format_combo(keys) -> str:
    keys = set(keys)
    ordered = [k for k in _ORDER if k in keys] + sorted(k for k in keys if k not in _ORDER)
    return "+".join(ordered)


def combo_matches(pressed: set[str], combo: frozenset[str]) -> bool:
    """True if exactly the combo's keys are held. Generic tokens match either side."""
    if not combo or len(pressed) != len(combo):
        return False
    remaining = set(pressed)
    # Side-specific tokens first so "rctrl+ctrl" style combos resolve deterministically.
    for token in sorted(combo, key=lambda t: t in GENERIC.values()):
        found = next((k for k in remaining if k == token or generic(k) == token), None)
        if found is None:
            return False
        remaining.discard(found)
    return True


def _in_combo(key: str, combo: frozenset[str]) -> bool:
    return key in combo or generic(key) in combo


class HotkeyEngine:
    def __init__(
        self,
        on_start: Callable[[str, bool], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[bool], None],
        on_mode_change: Callable[[str, bool], None],
        on_action: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_cancel = on_cancel
        self._on_mode_change = on_mode_change
        self._on_action = on_action or (lambda _name: None)
        self._actions: dict[str, frozenset[str]] = {}
        self._clock = clock
        self._lock = threading.RLock()
        self.enabled = True
        self.tap_threshold = 0.25
        self.double_tap_window = 0.4
        self.double_tap = True
        self._combos: dict[str, frozenset[str]] = {}
        self._pressed: set[str] = set()
        self._suppressed: set[str] = set()
        self._recording: str | None = None  # None | "hold" | "handsfree"
        self._mode: str | None = None  # "dictate" | "command"
        self._active: frozenset[str] = frozenset()
        self._start_t = 0.0
        self._need_release = False
        self._last_tap: float | None = None
        self._touched = False

    # Configuration -------------------------------------------------------------------------
    def configure(self, dictate: str, handsfree: str, command: str, double_tap: bool = True,
                  actions: dict[str, str] | None = None) -> None:
        with self._lock:
            self._actions = {
                name: parse_combo(combo) for name, combo in (actions or {}).items() if parse_combo(combo)
            }
            self._combos = {
                name: combo
                for name, combo in (
                    ("dictate", parse_combo(dictate)),
                    ("handsfree", parse_combo(handsfree)),
                    ("command", parse_combo(command)),
                )
                if combo
            }
            self.double_tap = double_tap

    @property
    def recording(self) -> str | None:
        return self._recording

    def external_stop(self) -> None:
        """The app ended the recording by other means (UI button, time limit, error)."""
        with self._lock:
            self._recording = None
            self._mode = None
            self._need_release = bool(self._pressed)

    def prune(self, is_down: Callable[[str], bool | None]) -> None:
        """Drop keys whose key-up we missed (e.g. after the lock screen)."""
        with self._lock:
            for key in list(self._pressed):
                if is_down(key) is False:
                    self._pressed.discard(key)
                    self._suppressed.discard(key)

    # Events --------------------------------------------------------------------------------
    def key_down(self, key: str, t: float | None = None) -> bool:
        """Returns True if the event should be swallowed."""
        with self._lock:
            t = self._clock() if t is None else t
            if key in self._pressed:  # auto-repeat
                return key in self._suppressed
            self._pressed.add(key)
            if not self.enabled or not self._combos:
                return False

            if self._recording is not None and key == "esc":
                self._finish(cancel=True, tap=False)
                self._need_release = True
                return self._swallow(key)

            if self._recording == "handsfree":
                if not self._need_release and self._match() is not None:
                    self._touched = True
                    self._finish(cancel=False)
                    self._need_release = True
                    return self._swallow_if_trigger(key)
                return False

            if self._recording == "hold":
                action = self._match_action()
                if action is not None:
                    # e.g. dictate is Ctrl+Win and the action is Ctrl+Win+E: the hold already
                    # started, so drop it silently and run the action instead.
                    self._finish(cancel=True, tap=True)
                    self._need_release = True
                    self._on_action(action)
                    return self._swallow_if_trigger(key)
                match = self._match()
                if match == "command" and self._mode == "dictate":
                    self._mode = "command"
                    self._active = self._combos["command"]
                    self._touched = True
                    self._on_mode_change("command", False)
                    return self._swallow_if_trigger(key)
                if match == "handsfree":
                    self._recording = "handsfree"
                    self._need_release = True
                    self._touched = True
                    self._on_mode_change(self._mode or "dictate", True)
                    return self._swallow_if_trigger(key)
                self._finish(cancel=True, tap=False)
                self._need_release = True
                return False

            # Idle
            if self._need_release:
                return False
            action = self._match_action()
            if action is not None:
                self._touched = True
                self._need_release = True
                self._on_action(action)
                return self._swallow_if_trigger(key)
            match = self._match()
            if match is None:
                return False
            self._touched = True
            if match == "handsfree":
                self._begin("dictate", handsfree=True, t=t)
                self._need_release = True
            elif (
                match == "dictate"
                and self.double_tap
                and self._last_tap is not None
                and t - self._last_tap <= self.double_tap_window
            ):
                self._last_tap = None
                self._begin("dictate", handsfree=True, t=t)
                self._need_release = True
            else:
                self._begin(match, handsfree=False, t=t)
            return self._swallow_if_trigger(key)

    def key_up(self, key: str, t: float | None = None) -> int:
        """Returns a bit set of SUPPRESS / MASK."""
        with self._lock:
            t = self._clock() if t is None else t
            flags = SUPPRESS if key in self._suppressed else 0
            self._suppressed.discard(key)
            self._pressed.discard(key)

            if self._recording == "hold" and _in_combo(key, self._active):
                if t - self._start_t < self.tap_threshold:
                    was_dictate = self._mode == "dictate"
                    self._finish(cancel=True, tap=True)
                    self._last_tap = t if was_dictate else None
                else:
                    self._finish(cancel=False)
                self._need_release = True

            if not flags and self._touched and generic(key) in ("windows", "alt"):
                flags |= MASK
            if not self._pressed:
                self._need_release = False
                self._touched = False
            return flags

    # Internals -----------------------------------------------------------------------------
    def _match(self) -> str | None:
        # Most specific first.
        for name in sorted(self._combos, key=lambda n: -len(self._combos[n])):
            if combo_matches(self._pressed, self._combos[name]):
                return name
        return None

    def _match_action(self) -> str | None:
        for name in sorted(self._actions, key=lambda n: -len(self._actions[n])):
            if combo_matches(self._pressed, self._actions[name]):
                return name
        return None

    def _begin(self, mode: str, handsfree: bool, t: float) -> None:
        self._recording = "handsfree" if handsfree else "hold"
        self._mode = mode
        self._active = self._combos.get(mode, frozenset())
        self._start_t = t
        self._on_start(mode, handsfree)

    def _finish(self, cancel: bool, tap: bool = False) -> None:
        self._recording = None
        self._mode = None
        if cancel:
            self._on_cancel(tap)
        else:
            self._on_stop()

    def _swallow(self, key: str) -> bool:
        self._suppressed.add(key)
        return True

    def _swallow_if_trigger(self, key: str) -> bool:
        # Modifiers pass through (they are masked on release instead); other keys such as
        # Space or F8 must not reach the focused app.
        if is_modifier(key):
            return False
        return self._swallow(key)


class ComboCapture:
    """Records a key combination for the settings UI: the largest set held before release."""

    def __init__(self, on_done: Callable[[str], None]):
        self._on_done = on_done
        self._held: set[str] = set()
        self._peak: set[str] = set()
        self._done = False

    def feed(self, key: str, down: bool) -> None:
        if self._done:
            return
        if down:
            self._held.add(key)
            if len(self._held) >= len(self._peak):
                self._peak = set(self._held)
            return
        self._held.discard(key)
        if not self._held and self._peak:
            self._done = True
            self._on_done("" if self._peak == {"esc"} else format_combo(self._peak))


_PRETTY = {
    "ctrl": "Ctrl", "lctrl": "Left Ctrl", "rctrl": "Right Ctrl",
    "alt": "Alt", "lalt": "Left Alt", "ralt": "Right Alt",
    "shift": "Shift", "lshift": "Left Shift", "rshift": "Right Shift",
    "windows": "Win", "lwin": "Left Win", "rwin": "Right Win",
    "esc": "Esc", "space": "Space", "enter": "Enter", "capslock": "Caps Lock",
    "scrolllock": "Scroll Lock", "pageup": "Page Up", "pagedown": "Page Down",
}


def pretty_combo(text: str) -> str:
    keys = parse_combo(text)
    return " + ".join(_PRETTY.get(k, k.upper() if len(k) <= 3 else k.title()) for k in format_combo(keys).split("+") if k)
