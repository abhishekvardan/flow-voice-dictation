"""Spoken-to-code fixes for editors and terminals, and vocabulary harvested from a project.

All deterministic: no model involved, so dictating code can't invent identifiers.
"""

from __future__ import annotations

import re
from pathlib import Path

# Said -> written. Applied only for the "code" and "prompt" styles.
SPOKEN_CODE = [
    ("dot py", ".py"), ("dot ts", ".ts"), ("dot tsx", ".tsx"), ("dot js", ".js"),
    ("dot jsx", ".jsx"), ("dot json", ".json"), ("dot md", ".md"), ("dot yml", ".yml"),
    ("dot yaml", ".yaml"), ("dot toml", ".toml"), ("dot env", ".env"), ("dot html", ".html"),
    ("dot css", ".css"), ("dot sh", ".sh"), ("dot sql", ".sql"), ("dot txt", ".txt"),
    ("double dash", "--"), ("dash dash", "--"),
    ("open paren", "("), ("close paren", ")"),
    ("open brace", "{"), ("close brace", "}"),
    ("open bracket", "["), ("close bracket", "]"),
    ("backtick", "`"), ("hash tag", "#"), ("at sign", "@"), ("dollar sign", "$"),
    ("percent sign", "%"), ("ampersand", "&"), ("pipe symbol", "|"), ("caret symbol", "^"),
    ("underscore", "_"), ("forward slash", "/"), ("back slash", "\\"), ("slash", "/"),
    ("equals equals", "=="), ("not equals", "!="), ("arrow function", "=>"),
    ("greater than or equal", ">="), ("less than or equal", "<="),
    ("plus plus", "++"), ("minus minus", "--"),
]

_GLUE = re.compile(r"\s*([.\\/_@#$%^&|`(\[{])\s*")
_CLOSERS = re.compile(r"\s+([)\]}])")
_DASH_GLUE = re.compile(r"(--)\s+(\w)")

CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".cs",
                   ".rb", ".php", ".swift", ".c", ".h", ".cpp", ".hpp", ".sql", ".sh", ".ps1"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             "target", ".idea", ".vscode", "vendor", "coverage"}
_IDENTIFIER = re.compile(r"\b(?:def|class|function|func|const|let|var|interface|type|struct|fn)\s+"
                         r"([A-Za-z_][A-Za-z0-9_]{2,})")
_CAMEL_OR_SNAKE = re.compile(r"^(?:[a-z]+(?:[A-Z][a-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+|"
                             r"[a-z]+(?:_[a-z0-9]+)+)$")


def apply_code_words(text: str) -> str:
    """Converts spoken symbol names and tidies spacing around them."""
    for phrase, symbol in SPOKEN_CODE:
        pattern = re.compile(rf"(?<![\w']){re.escape(phrase)}(?![\w'])", re.IGNORECASE)
        # A lambda, so a backslash in the symbol is not read as a regex escape.
        text = pattern.sub(lambda _m, s=symbol: s, text)
    text = _GLUE.sub(r"\1", text)
    text = _CLOSERS.sub(r"\1", text)
    text = _DASH_GLUE.sub(r"\1\2", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def harvest_vocabulary(folder: str | Path, limit: int = 400) -> list[str]:
    """Collects camelCase / snake_case identifiers and file names from a project folder."""
    root = Path(folder)
    counts: dict[str, int] = {}
    files = 0
    for path in root.rglob("*"):
        if files >= 2000:
            break
        if not path.is_file() or path.suffix.lower() not in CODE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files += 1
        counts[path.name] = counts.get(path.name, 0) + 3  # file names are worth knowing
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")[:200_000]
        except OSError:
            continue
        for name in _IDENTIFIER.findall(source):
            if _CAMEL_OR_SNAKE.match(name):
                counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ranked[:limit]]
