from flow.textfix import apply_spoken_punctuation, basic_clean, collapse_repeats, strip_fillers


def test_strip_fillers_only_removes_noises():
    assert strip_fillers("um so I think uh we should ship") == " so I think  we should ship"
    # Words that carry meaning stay.
    assert "like" in strip_fillers("it works like a charm")
    assert "Erm" not in strip_fillers("Erm, maybe")


def test_collapse_repeats():
    assert collapse_repeats("the the new build") == "the new build"
    assert collapse_repeats("we could we could move it") == "we could we could move it"  # phrases kept
    assert collapse_repeats("that is very very good") == "that is very good"


def test_spoken_punctuation():
    assert apply_spoken_punctuation("first point comma second point period") == "first point , second point ."
    assert apply_spoken_punctuation("hello new paragraph thanks") == "hello \n\n thanks"
    # Not a command when it is part of a word.
    assert apply_spoken_punctuation("commascript") == "commascript"


def test_basic_clean_end_to_end():
    raw = "um so i think we should uh we should probably move the the meeting to thursday comma if that works"
    assert basic_clean(raw) == (
        "So i think we should we should probably move the meeting to thursday, if that works"
    ).replace("i think", "I think")


def test_basic_clean_handles_non_latin_scripts():
    hindi = "मैं सोचता हूँ कि हमें उह शुक्रवार को नया बिल्ड शिप करना चाहिए"
    cleaned = basic_clean(hindi, latin_script=False)
    assert "उह" not in cleaned  # filler removed
    assert cleaned.startswith("मैं")


def test_basic_clean_is_idempotent_and_safe_on_empty():
    assert basic_clean("") == ""
    once = basic_clean("um hello   world .")
    assert basic_clean(once) == once
