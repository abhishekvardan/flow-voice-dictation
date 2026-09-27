"""Personal dictionary: vocabulary hints, replacement rules and voice snippets."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .db import Database


@dataclass
class Replacement:
    id: int
    pattern: str
    replacement: str


@dataclass
class Snippet:
    id: int
    trigger: str
    expansion: str


def normalize(text: str) -> str:
    text = re.sub(r"[^\w\s']", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _phrase_regex(phrase: str) -> re.Pattern[str] | None:
    words = re.findall(r"[\w']+", phrase)
    if not words:
        return None
    body = r"[\s,.\-]+".join(re.escape(word) for word in words)
    return re.compile(rf"(?<![\w']){body}(?![\w'])", re.IGNORECASE)


def apply_replacements(text: str, replacements: list[Replacement]) -> str:
    for rule in replacements:
        regex = _phrase_regex(rule.pattern)
        if regex:
            text = regex.sub(lambda _m, r=rule.replacement: r, text)
    return text


def match_snippet(text: str, snippets: list[Snippet]) -> Snippet | None:
    """Whole-utterance match: saying just the trigger (optionally 'insert <trigger>')."""
    spoken = normalize(text)
    for prefix in ("insert ", "paste "):
        if spoken.startswith(prefix):
            candidates = (spoken, spoken[len(prefix):])
            break
    else:
        candidates = (spoken,)
    for snippet in snippets:
        if normalize(snippet.trigger) in candidates:
            return snippet
    return None


def expand_snippets(text: str, snippets: list[Snippet]) -> str:
    """Replace triggers embedded inside a longer dictation."""
    for snippet in sorted(snippets, key=lambda s: len(s.trigger), reverse=True):
        regex = _phrase_regex(snippet.trigger)
        if regex:
            text = regex.sub(lambda _m, e=snippet.expansion: e, text)
    return text


class Dictionary:
    def __init__(self, db: Database):
        self._db = db

    # Vocabulary
    def vocabulary(self) -> list[str]:
        return [row["word"] for row in self._db.query("SELECT word FROM vocabulary ORDER BY word")]

    def add_word(self, word: str) -> None:
        word = word.strip()
        if word:
            self._db.execute("INSERT OR IGNORE INTO vocabulary(word) VALUES (?)", (word,))

    def remove_word(self, word: str) -> None:
        self._db.execute("DELETE FROM vocabulary WHERE word = ?", (word,))

    # Replacements
    def replacements(self) -> list[Replacement]:
        rows = self._db.query("SELECT id, pattern, replacement FROM replacements ORDER BY id")
        return [Replacement(row["id"], row["pattern"], row["replacement"]) for row in rows]

    def add_replacement(self, pattern: str, replacement: str) -> None:
        if pattern.strip():
            self._db.execute(
                "INSERT INTO replacements(pattern, replacement) VALUES (?, ?)",
                (pattern.strip(), replacement),
            )

    def remove_replacement(self, rule_id: int) -> None:
        self._db.execute("DELETE FROM replacements WHERE id = ?", (rule_id,))

    # Snippets
    def snippets(self) -> list[Snippet]:
        rows = self._db.query("SELECT id, trigger, expansion FROM snippets ORDER BY trigger")
        return [Snippet(row["id"], row["trigger"], row["expansion"]) for row in rows]

    def set_snippet(self, trigger: str, expansion: str) -> None:
        if trigger.strip():
            self._db.execute(
                "INSERT INTO snippets(trigger, expansion) VALUES (?, ?) "
                "ON CONFLICT(trigger) DO UPDATE SET expansion = excluded.expansion",
                (trigger.strip(), expansion),
            )

    def remove_snippet(self, snippet_id: int) -> None:
        self._db.execute("DELETE FROM snippets WHERE id = ?", (snippet_id,))
