from flow.languages import cleanup_allowed, in_list, name, same_script, script_of
from flow.llm import build_cleanup_messages, plausible_cleanup


def test_language_names():
    assert name("hi") == "Hindi"
    assert name("HI") == "Hindi"
    assert name("") == "the same language"


def test_script_detection():
    assert script_of("hello there") == "LATIN"
    assert script_of("मैं सोचता हूँ") == "DEVANAGARI"
    assert script_of("நான் நினைக்கிறேன்") == "TAMIL"
    assert script_of("123 !!") == ""


def test_same_script_rejects_translation_and_transliteration():
    hindi = "मैं सोचता हूँ कि हमें शुक्रवार को नया बिल्ड शिप करना चाहिए"
    assert same_script(hindi, "मैं सोचता हूँ कि हमें शुक्रवार को नया बिल्ड शिप करना चाहिए।")
    # Measured failure modes of small models:
    assert not same_script(hindi, "I think we should ship the new build on Friday.")
    assert not same_script("main soch raha tha ki hum kal meeting karenge",
                           "तो मुख्य सोच रहा था कि हम कल का मीटिंग पोस्टपोन कर देते हैं")


def test_plausible_cleanup_uses_the_script_guard():
    tamil = "நான் நினைக்கிறேன் நாம வெள்ளிக்கிழமை புதிய பில்ட் ஷிப் பண்ணலாம்"
    assert not plausible_cleanup(tamil, "I am writing about the new ship painting.")


def test_cleanup_language_policy():
    setting = "en,es,fr"
    assert cleanup_allowed("en", setting)
    assert cleanup_allowed("ES", setting)
    assert not cleanup_allowed("hi", setting)
    assert cleanup_allowed("hi", "all")
    assert cleanup_allowed("", setting)  # unknown language: leave it to the other guards


def test_cleanup_prompt_names_the_language():
    messages = build_cleanup_messages("नमस्ते", "Formal.", [], language="hi")
    assert "in Hindi" in messages[0]["content"]
    assert "Hindi" in messages[-1]["content"]
    assert "Language:" not in build_cleanup_messages("hello", "Formal.", [])[-1]["content"]


def test_in_list():
    assert in_list("hi", "hi,mr")
    assert in_list("MR", " hi , mr ")
    assert not in_list("te", "hi,mr")
    assert not in_list("", "hi")
    assert not in_list("hi", "")


def test_per_language_model_profiles():
    from flow.config import Config
    from flow.stt import model_for_language

    cfg = Config()
    cfg.whisper_model = "small"
    cfg.language_models = {"hi": "large-v3-turbo"}
    cfg.language = "auto"
    assert model_for_language(cfg) == "small"      # detection happens after the model is chosen
    cfg.language = "hi"
    assert model_for_language(cfg) == "large-v3-turbo"
    cfg.language = "en"
    assert model_for_language(cfg) == "small"
