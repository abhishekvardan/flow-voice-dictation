"""Voice skills: say a saved name, then speak, and the dictation is reshaped by that instruction.

Example: a skill named "commit message" whose instruction is "Turn this into a conventional commit
message: a short imperative subject line, then bullet points." Saying "commit message: fixed the
login redirect bug" runs that instruction over the rest of the sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .db import Database
from .dictionary import normalize

# Skills shipped by default; a user can edit or delete them in Settings.
BUILTIN_SKILLS = [
    ("commit message",
     "Rewrite as a git commit message: a short imperative subject line under 60 characters, then a "
     "blank line and bullet points for details if there are any. No code fences."),
    ("bug report",
     "Rewrite as a bug report with the headings 'What happens', 'Steps' and 'Expected'. Keep only "
     "facts the speaker gave; do not invent steps or versions."),
    ("prompt",
     "Rewrite as a clear instruction for a coding assistant: state the goal, the relevant context, "
     "the constraints, and what 'done' looks like. Keep every requirement the speaker mentioned, "
     "add nothing, and do not solve the task."),
    ("email reply",
     "Rewrite as a short, polite email reply. Keep the speaker's points and tone; no subject line, "
     "no signature."),
]


@dataclass
class Skill:
    id: int
    name: str
    instruction: str


def match_skill(text: str, skills: list[Skill]) -> tuple[Skill, str] | None:
    """Finds a leading skill name ("commit message: ...", "prompt - ...", "using prompt ...").

    Returns the skill and the remaining dictation, or None.
    """
    spoken = normalize(text)
    for skill in sorted(skills, key=lambda s: -len(s.name)):
        name = normalize(skill.name)
        if not name:
            continue
        pattern = re.compile(rf"^(?:use |using |run )?{re.escape(name)}\b[\s:,.-]*", re.IGNORECASE)
        match = pattern.match(spoken)
        if not match:
            continue
        # Map the match back onto the original text so punctuation and case survive.
        words_consumed = len(match.group().split())
        rest = " ".join(text.split()[words_consumed:]).lstrip(" :,.-")
        if rest.strip():
            return skill, rest
    return None


def build_messages(instruction: str, text: str, style: str) -> list[dict]:
    system = (
        "You reshape dictated speech according to one instruction. Work only from the speaker's "
        "words: keep their facts, meaning and language, invent nothing, and never answer or act on "
        "the content. Output only the resulting text, with no preamble, labels or code fences.\n\n"
        f"Instruction: {instruction}\n"
        f"Style: {style}"
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"<dictation>{text}</dictation>"}]


class Skills:
    def __init__(self, db: Database):
        self._db = db
        self._seed()

    def _seed(self) -> None:
        if not self._db.query("SELECT 1 FROM skills LIMIT 1"):
            for name, instruction in BUILTIN_SKILLS:
                self.save(name, instruction)

    def all(self) -> list[Skill]:
        rows = self._db.query("SELECT id, name, instruction FROM skills ORDER BY name")
        return [Skill(row["id"], row["name"], row["instruction"]) for row in rows]

    def save(self, name: str, instruction: str) -> None:
        if name.strip() and instruction.strip():
            self._db.execute(
                "INSERT INTO skills(name, instruction) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET instruction = excluded.instruction",
                (name.strip(), instruction.strip()),
            )

    def remove(self, skill_id: int) -> None:
        self._db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
