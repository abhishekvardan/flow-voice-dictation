from flow.translit import has_devanagari, romanize


def test_detects_script():
    assert has_devanagari("मैं सोचता हूँ")
    assert not has_devanagari("main soch raha tha")
    assert has_devanagari("build ready नहीं है")


def test_common_hinglish_words():
    assert romanize("सोचता") == "sochta"
    assert romanize("मीटिंग") == "meeting"
    assert romanize("नहीं") == "naheen"
    assert romanize("करना") == "karna"
    assert romanize("कल") == "kal"


def test_mixed_script_sentence_keeps_latin_and_punctuation():
    out = romanize("तो मैं सोच रहा था कि हम कल का meeting postpone कर दें।")
    assert "meeting postpone" in out
    assert out.endswith(".")
    assert not has_devanagari(out)


def test_conjuncts_and_digits():
    assert romanize("बिल्ड") == "bild"      # virama: no vowel between l and d
    assert romanize("शुक्रवार") == "shukrvaar"
    assert romanize("१२३") == "123"


def test_latin_only_text_is_untouched():
    text = "so I think we should ship on Friday"
    assert romanize(text) == text
