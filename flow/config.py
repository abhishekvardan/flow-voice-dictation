"""User configuration, persisted as JSON in %APPDATA%\\Flow\\config.json."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .languages import DEFAULT_CLEANUP_LANGUAGES
from .styles import default_rules

log = logging.getLogger(__name__)

APP_NAME = "Flow"


def data_dir() -> Path:
    base = os.environ.get("FLOW_HOME") or os.path.join(
        os.environ.get("APPDATA", str(Path.home())), APP_NAME
    )
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Config:
    # Shortcuts
    hotkey_dictate: str = "ctrl+windows"
    hotkey_handsfree: str = "ctrl+windows+space"
    hotkey_command: str = "ctrl+windows+alt"
    hotkey_fixup: str = "ctrl+windows+e"  # open the last dictation to review, edit or re-run
    double_tap_handsfree: bool = True

    # Audio
    input_device: str = ""  # empty = system default
    sounds: bool = True
    max_recording_seconds: int = 360

    # Speech-to-text (faster-whisper)
    whisper_model: str = "auto"  # auto = small on GPU, base on CPU (measured: small is ~9 s on CPU)
    whisper_device: str = "auto"  # auto | cuda | cpu
    whisper_compute_type: str = "auto"
    language: str = "auto"
    language_detection_segments: int = 2  # more segments = steadier detection when language is "auto"
    cleanup_languages: str = DEFAULT_CLEANUP_LANGUAGES  # "all", or codes a small model handles well
    whisper_beam_size: int = 0  # 0 = automatic (5 on GPU, 2 on CPU); 1 = greedy, fastest
    # Per-language Whisper models, used when a language is pinned (not "auto"): {"hi": "large-v3-turbo"}
    language_models: dict[str, str] = field(default_factory=dict)
    # Languages whose Devanagari output should be written in Roman script (Hinglish): "hi,mr"
    romanize_languages: str = ""

    # LLM (Ollama)
    ollama_url: str = "http://localhost:11434"
    # Measured on 16 real dictations: llama3.2 3B produced an acceptable cleanup 12/16 times
    # (median 2.7 s); qwen2.5:1.5b only 5/16 but at ~1.1 s. Quality wins by default.
    ollama_model: str = "llama3.2"
    cleanup_enabled: bool = True
    spoken_punctuation: bool = True  # turn "comma" / "new paragraph" into symbols without the LLM
    llm_timeout: float = 20.0

    # Styles
    default_style: str = "formal"
    style_rules: list[dict] = field(default_factory=default_rules)
    style_prompts: dict[str, str] = field(default_factory=dict)

    # Insertion
    paste_mode: str = "paste"  # paste | type
    trailing_space: bool = True

    # History / app
    history_enabled: bool = True
    history_retention_days: int = 30
    launch_at_login: bool = False
    debug_latency: bool = False  # show a per-dictation latency breakdown on the overlay

    def copy(self) -> "Config":
        return Config(**json.loads(json.dumps(asdict(self))))


def config_path() -> Path:
    return data_dir() / "config.json"


def load() -> Config:
    path = config_path()
    cfg = Config()
    if not path.exists():
        save(cfg)
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.exception("Could not read %s; using defaults", path)
        return cfg
    known = {f.name for f in fields(Config)}
    for key, value in raw.items():
        if key in known:
            setattr(cfg, key, value)
    return cfg


def save(cfg: Config) -> None:
    path = config_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    os.replace(tmp, path)
