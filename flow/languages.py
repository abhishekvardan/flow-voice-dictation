"""Language names, scripts and the per-language cleanup policy."""

from __future__ import annotations

import unicodedata

# Whisper language code -> name used in the cleanup prompt.
NAMES = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian", "ja": "Japanese",
    "ko": "Korean", "zh": "Chinese", "ar": "Arabic", "ta": "Tamil", "te": "Telugu",
    "bn": "Bengali", "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
    "pa": "Punjabi", "ur": "Urdu", "tr": "Turkish", "pl": "Polish", "uk": "Ukrainian",
    "vi": "Vietnamese", "th": "Thai", "id": "Indonesian", "sv": "Swedish", "da": "Danish",
    "nb": "Norwegian", "fi": "Finnish", "cs": "Czech", "el": "Greek", "he": "Hebrew",
    "ro": "Romanian", "hu": "Hungarian", "ca": "Catalan", "fa": "Persian", "sw": "Swahili",
}

# Languages a small local model cleans up reliably (measured for qwen2.5:1.5b and llama3.2 3B:
# Indian languages are either translated into English or take 5-11 s, so they default to raw).
DEFAULT_CLEANUP_LANGUAGES = "en,es,fr,de,it,pt,nl"


def name(code: str) -> str:
    return NAMES.get((code or "").lower(), code or "the same language")


def cleanup_allowed(code: str, setting: str) -> bool:
    """Is AI cleanup allowed for this detected language?"""
    setting = (setting or "").strip().lower()
    if setting in ("all", "*"):
        return True
    if not code:
        return True  # unknown language: let the other guards decide
    allowed = {part.strip() for part in setting.split(",") if part.strip()}
    return code.lower() in allowed


def in_list(code: str, setting: str) -> bool:
    """Is this language code listed in a comma-separated setting?"""
    codes = {part.strip().lower() for part in (setting or "").split(",") if part.strip()}
    return bool(code) and code.lower() in codes


def script_of(text: str) -> str:
    """Dominant writing system of a string, e.g. 'LATIN', 'DEVANAGARI', 'HAN'."""
    counts: dict[str, int] = {}
    for char in text:
        if not char.isalpha():
            continue
        try:
            script = unicodedata.name(char).split()[0]
        except ValueError:
            continue
        if script in ("CJK", "HIRAGANA", "KATAKANA"):
            script = "HAN"
        counts[script] = counts.get(script, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def same_script(raw: str, cleaned: str) -> bool:
    """Catches translation and transliteration: the reply must keep the writing system."""
    a, b = script_of(raw), script_of(cleaned)
    return not a or not b or a == b
