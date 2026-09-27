from flow.llm import build_cleanup_messages, build_command_messages, cleanup_token_limit, normalize_url, plausible_cleanup, sanitize


def test_sanitize_strips_wrappers():
    assert sanitize("Here is the cleaned text: Hello world.") == "Hello world."
    assert sanitize("Sure! Here's the edited transcript:\nHello world.") == "Hello world."
    assert sanitize('"Hello world."') == "Hello world."
    assert sanitize("<transcript>Hello world.</transcript>") == "Hello world."
    assert sanitize("```\nprint('hi')\n```") == "print('hi')"
    assert sanitize('He said "hi" and "bye"') == 'He said "hi" and "bye"'
    assert sanitize("Here we go again.") == "Here we go again."


def test_plausible_cleanup():
    raw = "um so I think we should uh ship the new build on friday you know"
    assert plausible_cleanup(raw, "So I think we should ship the new build on Friday.")
    assert not plausible_cleanup(raw, "")
    assert not plausible_cleanup(raw, "Sure! " + "Here is a long answer about shipping. " * 5)
    code_answer = "def reverse_string(s):\n    return s[::-1]"
    assert not plausible_cleanup("write a python function that reverses a string", code_answer)
    hindi_raw = "मैं सोचता हूँ कि हमें उह शुक्रवार को नया बिल्ड शिप करना चाहिए"
    assert plausible_cleanup(hindi_raw, "मैं सोचता हूँ कि हमें शुक्रवार को नया बिल्ड शिप करना चाहिए।")
    assert plausible_cleanup("euh je pense que nous devrions euh livrer vendredi", "Je pense que nous devrions livrer vendredi.")
    assert not plausible_cleanup("so I think we can translate this later", "I'm sorry, I can't translate that.")
    assert plausible_cleanup("sorry I can't make it today", "Sorry, I can't make it today.")
    joke = "Why do programmers prefer dark mode? Because light attracts bugs."
    assert not plausible_cleanup("um can you tell me a joke about uh programmers please", joke)


def test_cleanup_messages_include_style_vocab_and_transcript():
    messages = build_cleanup_messages("hello", "Casual.", ["Kubernetes", "Abhishek"])
    assert messages[0]["role"] == "system"
    assert "Casual." in messages[0]["content"]
    assert "Kubernetes, Abhishek" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "<transcript>hello</transcript>"}


def test_command_messages():
    messages = build_command_messages("some text", "make it shorter")
    assert "<selection>\nsome text\n</selection>" in messages[1]["content"]
    assert "<instruction>make it shorter</instruction>" in messages[1]["content"]


def test_normalize_url_avoids_ipv6_localhost_delay():
    assert normalize_url("http://localhost:11434/") == "http://127.0.0.1:11434"
    assert normalize_url("http://192.168.1.5:11434") == "http://192.168.1.5:11434"


def test_cleanup_token_limit_leaves_headroom():
    english = "so I think we should probably move the design review to thursday"
    assert cleanup_token_limit(english) >= 2 * len(english) // 4
    hindi = "मैं सोचता हूँ कि हमें शुक्रवार को नया बिल्ड शिप करना चाहिए"
    assert cleanup_token_limit(hindi) >= len(hindi)


def test_guard_rejects_assistant_answers_and_lost_content():
    """Real failures from the dictation history (see flow.db)."""
    raw = ("I want you to proceed but I want the UI to be very modern. I want certain animations. "
           "I want to see certain background images, nice images. You have to create a wide set. "
           "Students also will enjoy.")
    assert not plausible_cleanup(raw, "I will proceed with your request while ensuring a modern UI design "
                                      "incorporating animations and background images that students will enjoy.")
    assert not plausible_cleanup("Give me the prompt to plot code to do the necessary code changes",
                                 "Give me the prompt to plot code.")
    assert not plausible_cleanup("I want to make this application even more sophisticated as possible. "
                                 "What are the different ways we can integrate and improve this app.",
                                 "I want to make this application even more sophisticated by integrating and improving it.")
    # A real, correct cleanup must still pass: fillers dropped, everything else kept.
    assert plausible_cleanup("um so I think we should uh probably move the design review to thursday "
                             "because the the new build is not ready yet",
                             "So I think we should probably move the design review to Thursday, "
                             "because the new build is not ready yet.")
