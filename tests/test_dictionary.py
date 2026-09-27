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
