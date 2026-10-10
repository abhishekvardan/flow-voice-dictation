from flow.hotkeys import MASK, SUPPRESS, ComboCapture, HotkeyEngine, combo_matches, parse_combo, pretty_combo


class Recorder:
    def __init__(self):
        self.events = []

    def engine(self, dictate="ctrl+windows", handsfree="ctrl+windows+space", command="ctrl+windows+alt",
               actions=None):
        engine = HotkeyEngine(
            on_start=lambda mode, hf: self.events.append(("start", mode, hf)),
            on_stop=lambda: self.events.append(("stop",)),
            on_cancel=lambda tap: self.events.append(("cancel", tap)),
            on_mode_change=lambda mode, hf: self.events.append(("mode", mode, hf)),
            on_action=lambda name: self.events.append(("action", name)),
            clock=lambda: 0.0,
        )
        engine.configure(dictate, handsfree, command, actions=actions)
        return engine


def test_parse_and_match():
    assert parse_combo("Ctrl + Win") == frozenset({"ctrl", "windows"})
    assert combo_matches({"lctrl", "lwin"}, parse_combo("ctrl+windows"))
    assert combo_matches({"rctrl", "rwin"}, parse_combo("ctrl+windows"))
    assert not combo_matches({"lctrl", "lwin", "space"}, parse_combo("ctrl+windows"))
    assert combo_matches({"rctrl"}, parse_combo("rctrl"))
    assert not combo_matches({"lctrl"}, parse_combo("rctrl"))
    assert pretty_combo("windows+ctrl+space") == "Ctrl + Win + Space"


def test_hold_to_talk():
    r = Recorder()
    e = r.engine()
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.05)
    assert r.events == [("start", "dictate", False)]
    flags = e.key_up("lwin", 2.0)
    assert r.events[-1] == ("stop",)
    assert flags & MASK  # Win release is masked so Start menu stays closed
    assert not e.key_up("lctrl", 2.1) & MASK
    assert e.recording is None


def test_quick_tap_is_discarded():
    r = Recorder()
    e = r.engine()
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.0)
    e.key_up("lwin", 0.1)
    assert r.events[-1] == ("cancel", True)


def test_double_tap_starts_handsfree_and_press_again_stops():
    r = Recorder()
    e = r.engine()
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.0)
    e.key_up("lwin", 0.1)
    e.key_up("lctrl", 0.12)
    e.key_down("lctrl", 0.25)
    e.key_down("lwin", 0.26)
    assert r.events[-1] == ("start", "dictate", True)
    e.key_up("lwin", 0.35)
    e.key_up("lctrl", 0.36)
    assert e.recording == "handsfree"
    e.key_down("lctrl", 5.0)
    e.key_down("lwin", 5.0)
    assert r.events[-1] == ("stop",)
    # Releasing after stopping must not start anything new.
    e.key_up("lwin", 5.3)
    e.key_up("lctrl", 5.3)
    assert r.events[-1] == ("stop",)


def test_handsfree_combo_swallows_space():
    r = Recorder()
    e = r.engine()
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.0)
    assert e.key_down("space", 0.05) is True
    assert r.events[-1] == ("mode", "dictate", True)
    assert e.key_up("space", 0.2) & SUPPRESS
    e.key_up("lwin", 0.3)
    e.key_up("lctrl", 0.3)
    assert e.recording == "handsfree"


def test_command_mode_upgrade():
    r = Recorder()
    e = r.engine()
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.0)
    e.key_down("lalt", 0.1)
    assert r.events[-1] == ("mode", "command", False)
    e.key_up("lalt", 3.0)
    assert r.events[-1] == ("stop",)


def test_command_mode_direct():
    r = Recorder()
    e = r.engine()
    e.key_down("lctrl", 0.0)
    e.key_down("lalt", 0.0)
    e.key_down("lwin", 0.0)
    assert r.events == [("start", "command", False)]


def test_other_shortcut_cancels():
    r = Recorder()
    e = r.engine()
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.0)
    assert e.key_down("left", 0.3) is False
    assert r.events[-1] == ("cancel", False)
    e.key_up("left", 0.4)
    e.key_up("lwin", 0.5)
    assert r.events[-1] == ("cancel", False)


def test_escape_cancels_and_is_swallowed():
    r = Recorder()
    e = r.engine()
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.0)
    e.key_up("lwin", 0.5)  # stop -> not recording anymore
    r.events.clear()
    e.key_up("lctrl", 0.5)
    e.key_down("lctrl", 1.0)
    e.key_down("lwin", 1.0)
    e.key_down("space", 1.0)  # hands-free
    e.key_up("space", 1.1)
    e.key_up("lwin", 1.1)
    e.key_up("lctrl", 1.1)
    assert e.key_down("esc", 3.0) is True
    assert r.events[-1] == ("cancel", False)
    assert e.key_up("esc", 3.1) & SUPPRESS


def test_plain_win_tap_is_not_masked():
    r = Recorder()
    e = r.engine()
    e.key_down("lwin", 0.0)
    assert e.key_up("lwin", 0.1) == 0
    assert r.events == []


def test_disabled_engine_ignores_combos():
    r = Recorder()
    e = r.engine()
    e.enabled = False
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.0)
    assert r.events == []


def test_single_function_key_hotkey_is_swallowed():
    r = Recorder()
    e = r.engine(dictate="f8", handsfree="", command="")
    assert e.key_down("f8", 0.0) is True
    assert e.key_down("f8", 0.03) is True  # auto-repeat
    assert e.key_up("f8", 1.0) & SUPPRESS
    assert r.events == [("start", "dictate", False), ("stop",)]


def test_prune_drops_stale_keys():
    r = Recorder()
    e = r.engine()
    e.key_down("lwin", 0.0)  # key-up lost (e.g. Win+L)
    e.prune(lambda key: False)
    e.key_down("lctrl", 1.0)
    e.key_down("lwin", 1.0)
    assert r.events == [("start", "dictate", False)]


def test_combo_capture():
    got = []
    cap = ComboCapture(got.append)
    cap.feed("lctrl", True)
    cap.feed("lshift", True)
    cap.feed("d", True)
    cap.feed("d", False)
    cap.feed("lshift", False)
    cap.feed("lctrl", False)
    assert got == ["lctrl+lshift+d"]

    got.clear()
    cap = ComboCapture(got.append)
    cap.feed("esc", True)
    cap.feed("esc", False)
    assert got == [""]


def test_action_hotkey_fires_and_cancels_the_hold_it_started():
    r = Recorder()
    e = r.engine(actions={"fixup": "ctrl+windows+e"})
    e.key_down("lctrl", 0.0)
    e.key_down("lwin", 0.0)
    assert r.events == [("start", "dictate", False)]
    assert e.key_down("e", 0.05) is True  # swallowed: the app must not receive "e"
    assert r.events[-2:] == [("cancel", True), ("action", "fixup")]
    assert e.recording is None
    e.key_up("e", 0.2)
    e.key_up("lwin", 0.25)
    e.key_up("lctrl", 0.26)
    assert r.events[-1] == ("action", "fixup")  # releasing does not start or stop anything


def test_action_hotkey_from_idle():
    r = Recorder()
    e = r.engine(dictate="f8", handsfree="", command="", actions={"fixup": "f9"})
    assert e.key_down("f9", 0.0) is True
    assert r.events == [("action", "fixup")]
