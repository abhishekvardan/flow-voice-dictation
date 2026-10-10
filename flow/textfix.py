"""Deterministic transcript cleanup: no model, no network, no risk of invention.

This runs on every dictation before the LLM is consulted. It is also what gets inserted when the
LLM is unavailable, skipped for the language, or rejected by the guards in ``llm.plausible_cleanup``
- so a failed cleanup still produces tidy text instead of a raw transcript.
"""

from __future__ import annotations

import re

# Standalone noises only. Words like "like" or "actually" are left alone: they carry meaning often
# enough that deleting them changes sentences.
FILLERS = {
    "um", "umm", "ummm", "uh", "uhh", "uhhh", "er", "err", "erm", "ah", "ahh", "hmm", "hmmm",
    "mm", "mmm", "mhm", "eh", "uhm",
    # How Whisper writes the same noises when transcribing Indian languages.
    "उह", "उम", "उम्", "अं", "हम्म", "एह",           # Devanagari (Hindi, Marathi)
    "ఉహ్", "ఉమ్", "అం", "హమ్",                        # Telugu
    "உம்", "அம்",                                     # Tamil
}

# Spoken punctuation commands, longest first so "new paragraph" wins over "new".
SPOKEN_PUNCTUATION = [
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("question mark", "?"),
    ("exclamation point", "!"),
    ("exclamation mark", "!"),
    ("full stop", "."),
    ("semicolon", ";"),
    ("period", "."),
    ("comma", ","),
    ("colon", ":"),
]

_FILLER_RE = re.compile(
    r"(?<![\w'])(?:" + "|".join(sorted(FILLERS, key=len, reverse=True)) + r")(?![\w'])[,.]?",
    re.IGNORECASE,
)
_REPEAT_RE = re.compile(r"(?<![\w'])(\w+)(\s+\1)+(?![\w'])", re.IGNORECASE)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
_MULTI_PUNCT = re.compile(r"([,.;:!?])\1+")
_SENTENCE_START = re.compile(r"(^|[.!?]\s+|\n+)([a-z])")


def strip_fillers(text: str) -> str:
    return _FILLER_RE.sub("", text)


def collapse_repeats(text: str) -> str:
    """"the the new build" -> "the new build" (stutters Whisper transcribes literally)."""
    return _REPEAT_RE.sub(lambda m: m.group(1), text)


def apply_spoken_punctuation(text: str) -> str:
    for phrase, mark in SPOKEN_PUNCTUATION:
        pattern = re.compile(rf"(?<![\w']){re.escape(phrase)}(?![\w'])", re.IGNORECASE)
        text = pattern.sub(mark, text)
    return text


def tidy_whitespace(text: str) -> str:
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _MULTI_PUNCT.sub(r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"([,.;:!?])(?=[^\s\d,.;:!?)\]\"'])", r"\1 ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def capitalize_sentences(text: str) -> str:
    text = _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    return re.sub(r"(?<![\w'])i(?![\w'])", "I", text)


def basic_clean(text: str, spoken_punctuation: bool = True, latin_script: bool = True) -> str:
    """Tidy a transcript using rules alone. Safe to run on any language."""
    if not text.strip():
        return ""
    cleaned = collapse_repeats(strip_fillers(text))
    if spoken_punctuation:
        cleaned = apply_spoken_punctuation(cleaned)
    cleaned = tidy_whitespace(cleaned)
    if latin_script:
        # Capitalization and "I" only make sense in scripts that have letter case.
        cleaned = capitalize_sentences(cleaned)
    return cleaned.strip()
