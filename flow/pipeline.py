"""Audio → transcript → (optional) LLM → text. Shared by the app and the benchmark."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .config import Config
from .context import TERMINALS, WindowContext
from .dictionary import Dictionary, apply_replacements, expand_snippets, match_snippet
from .languages import cleanup_allowed, in_list, script_of
from .llm import OllamaClient, OllamaError
from .stt import Transcriber
from .styles import resolve_style, style_prompt
from .textfix import basic_clean
from .translit import romanize
from .timing import Timeline

log = logging.getLogger(__name__)


@dataclass
class Result:
    raw: str = ""
    final: str = ""
    style: str = ""
    warning: str = ""
    llm_used: bool = False
    language: str = ""
    tidied: str = ""        # rules-only cleanup; what gets inserted if the LLM is skipped or rejected
    llm_rejected: bool = False
    romanized: bool = False

    @property
    def empty(self) -> bool:
        return not self.raw


def process(
    audio: np.ndarray,
    *,
    mode: str,
    ctx: WindowContext,
    cfg: Config,
    transcriber: Transcriber,
    llm: OllamaClient,
    dictionary: Dictionary,
    capture_selection: Callable[[], str],
    timeline: Timeline,
) -> Result:
    """Everything up to (not including) inserting the text. Raises OllamaError in command mode."""
    vocabulary = dictionary.vocabulary()
    replacements = dictionary.replacements()
    raw, language = transcriber.transcribe(audio, cfg, vocabulary, timeline=timeline)
    timeline.mark("post_start")
    raw = apply_replacements(raw, replacements).strip()
    result = Result(raw=raw, language=language)
    if not raw:
        timeline.mark("post_done")
        return result

    if mode == "command":
        result.style = "command"
        selection = "" if ctx.process in TERMINALS else capture_selection()
        result.llm_used = True
        result.final = llm.command(selection, raw, timeline=timeline)
        timeline.mark("post_start")
        if not result.final:
            raise OllamaError("The model returned an empty response")
        timeline.mark("post_done")
        return result

    snippets = dictionary.snippets()
    snippet = match_snippet(raw, snippets)
    if snippet is not None:
        result.style, result.final = "snippet", snippet.expansion
        timeline.mark("post_done")
        return result

    result.style = resolve_style(ctx.process, ctx.title, cfg.style_rules, cfg.default_style)
    # Rules-only cleanup always runs: it is what gets inserted whenever the LLM cannot be trusted.
    tidied = basic_clean(raw, spoken_punctuation=cfg.spoken_punctuation,
                         latin_script=script_of(raw) in ("", "LATIN"))
    result.tidied = tidied
    final = tidied if result.style != "none" else raw
    allowed = cleanup_allowed(language, cfg.cleanup_languages)
    if cfg.cleanup_enabled and result.style != "none" and len(raw.split()) > 2 and allowed:
        result.llm_used = True
        try:
            final = llm.cleanup(raw, style_prompt(result.style, cfg.style_prompts), vocabulary,
                                timeline=timeline, language=language, fallback=tidied)
            result.llm_rejected = final == tidied
        except OllamaError as exc:
            result.warning = f"{exc}. Inserted the tidied transcript."
            final = tidied
        timeline.mark("post_start")
    elif cfg.cleanup_enabled and not allowed:
        log.info("Skipping AI cleanup for language %r (not in cleanup_languages=%r)", language, cfg.cleanup_languages)
        result.style = f"{result.style} (rules only: {language})"
    final = expand_snippets(apply_replacements(final, replacements), snippets)
    if in_list(language, cfg.romanize_languages):
        final = romanize(final)
        result.tidied = romanize(result.tidied)
        result.romanized = True
    if cfg.trailing_space and not final.endswith((" ", "\n")):
        final += " "
    result.final = final
    timeline.mark("post_done")
    return result
