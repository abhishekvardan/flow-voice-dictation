from flow.styles import BUILTIN_STYLES, default_rules, resolve_style, style_prompt


def test_resolve_by_process_and_title():
    rules = default_rules()
    assert resolve_style("slack.exe", "general", rules, "formal") == "casual"
    assert resolve_style("Code.exe", "app.py - VS Code", rules, "formal") == "code"
    assert resolve_style("chrome.exe", "Inbox (3) - me@gmail.com - Gmail", rules, "casual") == "formal"
    assert resolve_style("notepad.exe", "Untitled", rules, "formal") == "formal"


def test_first_rule_wins_and_blank_rules_ignored():
    rules = [
        {"kind": "process", "match": "", "style": "code"},
        {"kind": "title", "match": "draft", "style": "very_casual"},
        {"kind": "process", "match": "notepad.exe", "style": "formal"},
    ]
    assert resolve_style("notepad.exe", "Draft.txt", rules, "casual") == "very_casual"


def test_style_prompt_override():
    assert style_prompt("casual") == BUILTIN_STYLES["casual"]
    assert style_prompt("casual", {"casual": "Pirate voice."}) == "Pirate voice."
    assert style_prompt("casual", {"casual": "  "}) == BUILTIN_STYLES["casual"]


def test_whisper_auto_model_depends_on_hardware():
    from flow.stt import resolve_model_name

    assert resolve_model_name("auto", "cuda") == "small"
    assert resolve_model_name("auto", "cpu") == "base"
    assert resolve_model_name("medium", "cpu") == "medium"
