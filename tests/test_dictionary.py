from flow.db import Database
from flow.dictionary import (
    Dictionary, Replacement, Snippet, apply_replacements, expand_snippets, match_snippet,
)
from flow.history import History


def test_replacements_whole_word_case_insensitive():
    rules = [Replacement(1, "wisper flow", "Wispr Flow"), Replacement(2, "k8s", "Kubernetes")]
    assert apply_replacements("I love Wisper  Flow.", rules) == "I love Wispr Flow."
    assert apply_replacements("deploy to k8s now", rules) == "deploy to Kubernetes now"
    assert apply_replacements("whisper flows", rules) == "whisper flows"


def test_snippet_whole_utterance():
    snippets = [Snippet(1, "my calendar link", "https://cal.com/me")]
    assert match_snippet("My calendar link.", snippets).expansion == "https://cal.com/me"
    assert match_snippet("Insert my calendar link", snippets) is not None
    assert match_snippet("send them my calendar link", snippets) is None


def test_snippet_embedded():
    snippets = [Snippet(1, "my calendar link", "https://cal.com/me")]
    text = "Book a slot here: my calendar link. Thanks!"
    assert expand_snippets(text, snippets) == "Book a slot here: https://cal.com/me. Thanks!"


def test_dictionary_and_history_storage(tmp_path):
    db = Database(tmp_path / "flow.db")
    d = Dictionary(db)
    d.add_word("Kubernetes")
    d.add_word("kubernetes")  # duplicate, case-insensitive
    assert d.vocabulary() == ["Kubernetes"]
    d.set_snippet("sig", "Best,\nAbhishek")
    d.set_snippet("SIG", "Cheers")
    assert [(s.trigger, s.expansion) for s in d.snippets()] == [("sig", "Cheers")]
    d.add_replacement("gee pee tee", "GPT")
    assert d.replacements()[0].replacement == "GPT"

    h = History(db)
    h.add(mode="dictate", app="notepad.exe", style="formal", raw="um hello there",
          final="Hello there.", duration=30.0, stt_ms=100, llm_ms=200)
    assert h.search("hello")[0].final == "Hello there."
    words, wpm = h.stats()
    assert words == 2 and round(wpm) == 4
    h.clear()
    assert h.recent() == []


def test_history_stats_and_breakdowns(tmp_path):
    db = Database(tmp_path / "flow.db")
    h = History(db)
    for i, (app, style, mode, final) in enumerate([
        ("code.exe", "code", "dictate", "fix the login bug"),
        ("code.exe", "code", "dictate", "add a test"),
        ("slack.exe", "casual", "dictate", "sounds good to me"),
        ("code.exe", "command", "command", "shorter text"),
    ]):
        h.add(mode=mode, app=app, style=style, raw=final, final=final,
              duration=10.0, stt_ms=500 + i, llm_ms=1000 + i)

    s = h.summary()
    assert s["dictations"] == 4
    assert s["seconds"] == 40.0
    assert round(s["avg_stt_ms"]) == 502
    assert s["words"] == 11  # dictate rows only: 4 + 3 + 4 words

    by_app = dict((row[0], row[1]) for row in h.by_column("app"))
    assert by_app == {"code.exe": 3, "slack.exe": 1}
    assert h.by_column("mode")[0][0] == "dictate"
    assert len(h.per_day()) == 1
