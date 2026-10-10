"""Devanagari to informal Latin ("Hinglish") transliteration.

Whisper writes Hindi in Devanagari, but people who mix Hindi and English in chat and code usually
type Roman script: "main soch raha tha ki hum kal meeting karenge". This converts deterministically,
with no model involved, so nothing can be invented or translated.

It aims at how people actually type, not at a reversible scheme: no diacritics, no capital letters
mid-word, inherent 'a' dropped at the end of words (सोचता -> sochta, not sochataa).
"""

from __future__ import annotations

import re

CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}
INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऍ": "e", "ऑ": "o",
}
VOWEL_SIGNS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॅ": "e", "ॉ": "o",
}
VIRAMA = "्"
NUKTA = "़"
ANUSVARA = {"ं": "n", "ँ": "n", "ः": "h"}
DIGITS = {"०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
          "५": "5", "६": "6", "७": "7", "८": "8", "९": "9"}
PUNCTUATION = {"।": ".", "॥": "."}

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text))


def _next_syllable_has_vowel(word: str, i: int) -> bool:
    """Does the cluster starting at i carry its own vowel (or a virama)?"""
    if i >= len(word):
        return False
    if i + 1 < len(word) and word[i] + word[i + 1] in CONSONANTS:
        i += 2
    elif word[i] in CONSONANTS:
        i += 1
    else:
        return False
    if i < len(word) and word[i] == NUKTA:
        i += 1
    return i < len(word) and (word[i] in VOWEL_SIGNS or word[i] == VIRAMA)


def _transliterate_word(word: str) -> str:
    out: list[str] = []
    i = 0
    seen_consonant = False
    while i < len(word):
        char = word[i]
        # Consonant (plus optional nukta) -> consonant + inherent or explicit vowel.
        if char in CONSONANTS or (i + 1 < len(word) and char + word[i + 1] in CONSONANTS):
            if i + 1 < len(word) and char + word[i + 1] in CONSONANTS:
                out.append(CONSONANTS[char + word[i + 1]])
                i += 2
            else:
                out.append(CONSONANTS[char])
                i += 1
            if i < len(word) and word[i] == NUKTA:
                i += 1
            if i < len(word) and word[i] == VIRAMA:
                i += 1  # no vowel at all
                continue
            if i < len(word) and word[i] in VOWEL_SIGNS:
                sign = VOWEL_SIGNS[word[i]]
                i += 1
                # Word-final "ा" is typed as a single 'a' (sochta, karta, raha).
                out.append("a" if sign == "aa" and i >= len(word) else sign)
            elif i < len(word) and word[i] in ANUSVARA:
                out.append("a" + ANUSVARA[word[i]])
                i += 1
            elif i >= len(word):
                pass  # inherent 'a' at the end of a word: nobody types it
            elif seen_consonant and _next_syllable_has_vowel(word, i):
                pass  # schwa deletion: सोचता -> sochta, करना -> karna
            else:
                out.append("a")
            seen_consonant = True
            continue
        if char in INDEPENDENT_VOWELS:
            out.append(INDEPENDENT_VOWELS[char])
        elif char in VOWEL_SIGNS:
            out.append(VOWEL_SIGNS[char])
        elif char in ANUSVARA:
            out.append(ANUSVARA[char])
        elif char in DIGITS:
            out.append(DIGITS[char])
        elif char in PUNCTUATION:
            out.append(PUNCTUATION[char])
        elif char not in (VIRAMA, NUKTA):
            out.append(char)
        i += 1
    word = "".join(out)
    word = re.sub(r"aa+", "aa", word)
    return re.sub(r"(.)\1{2,}", r"\1\1", word)


def romanize(text: str) -> str:
    """Devanagari -> Roman. Latin words, numbers and punctuation pass through untouched."""
    if not has_devanagari(text):
        return text
    return re.sub(r"[ऀ-ॿ]+", lambda m: _transliterate_word(m.group()), text)
