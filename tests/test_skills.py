from pathlib import Path

from flow.codewords import apply_code_words, harvest_vocabulary
from flow.db import Database
from flow.skills import Skill, Skills, match_skill


def test_match_skill_splits_name_from_dictation():
    skills = [Skill(1, "commit message", "..."), Skill(2, "prompt", "...")]
    hit = match_skill("Commit message: fixed the login redirect bug", skills)
    assert hit is not None
    assert (hit[0].name, hit[1]) == ("commit message", "fixed the login redirect bug")

    hit = match_skill("use prompt build a login page with google sign in", skills)
    assert hit[0].name == "prompt"
    assert hit[1] == "build a login page with google sign in"


def test_match_skill_needs_the_name_at_the_start_and_a_body():
    skills = [Skill(1, "commit message", "...")]
    assert match_skill("write the commit message for this", skills) is None
    assert match_skill("commit message", skills) is None  # nothing dictated after it
    assert match_skill("committing changes now please", skills) is None


def test_longest_skill_name_wins():
    skills = [Skill(1, "bug", "..."), Skill(2, "bug report", "...")]
    assert match_skill("bug report the login page crashes", skills)[0].name == "bug report"


def test_spoken_code_words():
    assert apply_code_words("open flow slash app dot py") == "open flow/app.py"
    assert apply_code_words("run npm run dev double dash host") == "run npm run dev --host"
    assert apply_code_words("call handler open paren event close paren") == "call handler(event)"
    assert apply_code_words("value equals equals null") == "value == null"


def test_builtin_skills_are_seeded_once(tmp_path):
    db = Database(tmp_path / "flow.db")
    first = Skills(db)
    names = {s.name for s in first.all()}
    assert {"commit message", "bug report", "prompt", "email reply"} <= names
    Skills(db)  # a second instance must not duplicate them
    assert len(first.all()) == len(names)
    first.save("commit message", "changed instruction")
    assert len(first.all()) == len(names)
    assert [s.instruction for s in first.all() if s.name == "commit message"] == ["changed instruction"]


def test_harvest_vocabulary_finds_identifiers_in_this_repo():
    words = harvest_vocabulary(Path(__file__).resolve().parent.parent / "flow", limit=400)
    assert "basic_clean" in words
    assert "apply_code_words" in words
    assert any(word.endswith(".py") for word in words)
