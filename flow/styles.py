"""Context-aware writing styles: which style applies to which app, and what each style means."""

from __future__ import annotations

BUILTIN_STYLES: dict[str, str] = {
    "formal": (
        "Formal. Proper capitalization and full punctuation, complete sentences, "
        "professional tone. Do not add greetings or sign-offs that were not spoken."
    ),
    "casual": (
        "Casual. Natural conversational tone, normal capitalization, light punctuation. "
        "Contractions are fine."
    ),
    "very_casual": (
        "Very casual, like a text message. All lowercase, minimal punctuation, "
        "no period at the end."
    ),
    "code": (
        "Technical, for a code editor or terminal. Keep code identifiers, file names, "
        "commands, flags and technical terms exactly as intended (for example "
        "'use state' -> useState, 'dot env' -> .env, 'npm run dev' stays as is). "
        "No period at the end of short phrases."
    ),
    "prompt": (
        "An instruction for a coding assistant. Keep every requirement the speaker stated, in their "
        "order; spell code identifiers, file names and commands exactly; no greetings or filler."
    ),
    # "none" means: skip the LLM and insert the raw transcript.
    "none": "",
}

STYLE_LABELS: dict[str, str] = {
    "formal": "Formal",
    "casual": "Casual",
    "very_casual": "Very casual",
    "code": "Code / technical",
    "prompt": "AI prompt (for coding tools)",
    "none": "Raw (no AI cleanup)",
}

# Rules are evaluated top to bottom; first match wins.
# kind "title" matches a substring of the window title, "process" the exe name.
DEFAULT_RULES: list[dict[str, str]] = [
    {"kind": "title", "match": "Gmail", "style": "formal"},
    {"kind": "title", "match": "Outlook", "style": "formal"},
    {"kind": "title", "match": "Slack", "style": "casual"},
    {"kind": "title", "match": "WhatsApp", "style": "very_casual"},
    {"kind": "process", "match": "slack.exe", "style": "casual"},
    {"kind": "process", "match": "discord.exe", "style": "casual"},
    {"kind": "process", "match": "whatsapp.exe", "style": "very_casual"},
    {"kind": "process", "match": "telegram.exe", "style": "casual"},
    {"kind": "process", "match": "teams.exe", "style": "casual"},
    {"kind": "process", "match": "ms-teams.exe", "style": "casual"},
    {"kind": "process", "match": "outlook.exe", "style": "formal"},
    {"kind": "process", "match": "olk.exe", "style": "formal"},
    {"kind": "process", "match": "thunderbird.exe", "style": "formal"},
    {"kind": "process", "match": "winword.exe", "style": "formal"},
    {"kind": "process", "match": "code.exe", "style": "code"},
    {"kind": "process", "match": "cursor.exe", "style": "code"},
    {"kind": "process", "match": "windsurf.exe", "style": "code"},
    {"kind": "process", "match": "windowsterminal.exe", "style": "code"},
    {"kind": "process", "match": "pycharm64.exe", "style": "code"},
    {"kind": "process", "match": "idea64.exe", "style": "code"},
    {"kind": "process", "match": "devenv.exe", "style": "code"},
]


def default_rules() -> list[dict[str, str]]:
    return [dict(rule) for rule in DEFAULT_RULES]


def resolve_style(process: str, title: str, rules: list[dict[str, str]], default: str) -> str:
    process = (process or "").lower()
    title = (title or "").lower()
    for rule in rules:
        match = (rule.get("match") or "").strip().lower()
        style = rule.get("style") or default
        if not match:
            continue
        if rule.get("kind") == "title":
            if match in title:
                return style
        elif match == process:
            return style
    return default


def style_prompt(style: str, overrides: dict[str, str] | None = None) -> str:
    overrides = overrides or {}
    custom = (overrides.get(style) or "").strip()
    if custom:
        return custom
    return BUILTIN_STYLES.get(style, BUILTIN_STYLES["formal"])
