"""Speech-to-text with faster-whisper: GPU when available, CPU fallback, per-language models."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Config, data_dir

log = logging.getLogger(__name__)

SAMPLE_WARMUP = 16000
MAX_LOADED = 2  # keeping several Whisper models resident would exhaust a small GPU

CPU_SLOW_MODELS = {"small", "medium", "large-v3", "large-v3-turbo", "large-v2", "distil-large-v3"}

# Rough download sizes, shown in Settings so a slow connection is not a surprise.
MODEL_SIZES = {
    "tiny": "75 MB", "tiny.en": "75 MB", "base": "145 MB", "base.en": "145 MB",
    "small": "480 MB", "small.en": "480 MB", "medium": "1.5 GB", "medium.en": "1.5 GB",
    "large-v3-turbo": "1.6 GB", "distil-large-v3": "1.5 GB", "large-v3": "3.1 GB",
}


def _add_cuda_dll_dirs() -> None:
    """Expose DLLs from the nvidia-cublas-cu12 / nvidia-cudnn-cu12 wheels, if installed."""
    for base in map(Path, sys.path):
        nvidia = base / "nvidia"
        if not nvidia.is_dir():
            continue
        for bin_dir in nvidia.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:
                continue
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def cuda_available() -> bool:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return False
        for dll in ("cublas64_12.dll", "cudnn64_9.dll"):
            ctypes.WinDLL(dll)
        return True
    except Exception as exc:
        log.info("CUDA not usable for Whisper: %s", exc)
        return False


def resolve_model_name(name: str, device: str) -> str:
    """'auto' picks the most accurate model that is still fast on the detected hardware."""
    if name in ("", "auto"):
        return "small" if device == "cuda" else "base"
    return name


def model_for_language(cfg: Config) -> str:
    """The configured model, overridden by a per-language profile when the language is fixed.

    Profiles only apply to an explicitly chosen language: with automatic detection the language is
    not known until after transcription, which is what would choose the model.
    """
    language = (cfg.language or "auto").lower()
    if language not in ("", "auto"):
        override = (cfg.language_models or {}).get(language)
        if override:
            return override
    return cfg.whisper_model


def models_dir() -> Path:
    return data_dir() / "models"


def downloaded_models() -> set[str]:
    """Model names already in the local cache (so Settings can say what needs downloading)."""
    found = set()
    for path in models_dir().glob("models--*--faster-whisper-*"):
        if any(path.glob("snapshots/*/model.bin")):
            found.add(path.name.split("faster-whisper-")[-1])
    for path in models_dir().glob("models--*--distil-whisper-*"):
        if any(path.glob("snapshots/*/model.bin")):
            found.add("distil-" + path.name.split("distil-whisper-")[-1])
    return found


@dataclass
class Loaded:
    model: object
    device: str
    compute_type: str
    name: str

    @property
    def info(self) -> str:
        return f"{self.name} on {self.device} ({self.compute_type})"


class Transcriber:
    def __init__(self):
        self._loaded: dict[tuple, Loaded] = {}
        self._lock = threading.Lock()
        self._current: Loaded | None = None
        self.error = ""
        _add_cuda_dll_dirs()

    @property
    def ready(self) -> bool:
        return self._current is not None

    @property
    def device(self) -> str:
        return self._current.device if self._current else "cpu"

    @property
    def device_info(self) -> str:
        return self._current.info if self._current else ""

    def load(self, cfg: Config, name: str | None = None) -> str:
        """Loads (or reuses) a model. Returns a status string like 'small on cuda (int8_float16)'."""
        requested = name or model_for_language(cfg)
        with self._lock:
            for key, entry in self._loaded.items():
                if key[0] == requested and key[1:] == (cfg.whisper_device, cfg.whisper_compute_type):
                    self._current = entry
                    return entry.info
            entry = self._load_locked(cfg, requested)
            self._current = entry
            return entry.info

    def _load_locked(self, cfg: Config, requested: str) -> Loaded:
        from faster_whisper import WhisperModel

        attempts = []
        if cfg.whisper_device in ("auto", "cuda") and cuda_available():
            ct = cfg.whisper_compute_type if cfg.whisper_compute_type != "auto" else "int8_float16"
            attempts.append(("cuda", ct))
        if cfg.whisper_device in ("auto", "cpu") or not attempts:
            ct = cfg.whisper_compute_type if cfg.whisper_compute_type != "auto" else "int8"
            attempts.append(("cpu", "int8" if ct in ("float16", "int8_float16") else ct))

        last_error: Exception | None = None
        for device, compute_type in attempts:
            model_name = resolve_model_name(requested, device)
            if device == "cpu" and model_name.split(".")[0] in CPU_SLOW_MODELS:
                log.warning("Whisper '%s' on CPU is slow (measured ~9 s per dictation for 'small' on an "
                            "i7-12650H); choose 'auto', 'base' or 'tiny' for CPU-only machines", model_name)
            try:
                log.info("Loading Whisper '%s' on %s (%s)", model_name, device, compute_type)
                model = WhisperModel(
                    model_name, device=device, compute_type=compute_type,
                    download_root=str(models_dir()),
                    cpu_threads=max(1, (os.cpu_count() or 4) - 2),
                )
                segments, _ = model.transcribe(np.zeros(SAMPLE_WARMUP, np.float32),
                                               language="en", beam_size=1)
                list(segments)
            except Exception as exc:
                log.warning("Whisper failed on %s: %s", device, exc)
                last_error = exc
                continue
            entry = Loaded(model, device, compute_type, model_name)
            self._loaded[(requested, cfg.whisper_device, cfg.whisper_compute_type)] = entry
            self._evict_locked()
            self.error = ""
            log.info("Whisper ready: %s", entry.info)
            return entry
        self.error = str(last_error)
        raise RuntimeError(f"Could not load Whisper model: {last_error}")

    def _evict_locked(self) -> None:
        while len(self._loaded) > MAX_LOADED:
            key, entry = next(iter(self._loaded.items()))
            if entry is self._current:
                self._loaded[key] = self._loaded.pop(key)  # keep the active one, try the next
                continue
            log.info("Unloading Whisper '%s' to free memory", entry.info)
            self._loaded.pop(key)

    def transcribe(self, audio: np.ndarray, cfg: Config, vocabulary: list[str],
                   timeline=None, language: str | None = None) -> tuple[str, str]:
        """Returns (text, detected language code)."""
        wanted = model_for_language(cfg)
        if self._current is None or self._current.name != resolve_model_name(wanted, self.device):
            self.load(cfg, wanted)
        with self._lock:
            entry = self._current
            beam_size = cfg.whisper_beam_size or (5 if entry.device == "cuda" else 2)
            if timeline is not None:
                timeline.mark("stt_start")
                timeline.info["STT device"] = entry.info
                timeline.info["STT beam size"] = beam_size
                timeline.info["Audio length"] = f"{len(audio) / 16000:.1f} s"
            prompt = None
            if vocabulary:
                prompt = "Glossary: " + ", ".join(vocabulary[:80]) + "."
            # transcribe() eagerly runs VAD, feature extraction and language detection;
            # the returned generator then decodes segment by segment.
            segments, info = entry.model.transcribe(
                audio,
                language=language or (None if cfg.language in ("", "auto") else cfg.language),
                beam_size=beam_size,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 700},
                initial_prompt=prompt,
                condition_on_previous_text=False,
                without_timestamps=True,
                language_detection_segments=cfg.language_detection_segments,
            )
            language = info.language or ""
            if timeline is not None:
                timeline.mark("stt_prepared")
                timeline.info["Language"] = f"{language} ({info.language_probability:.2f})"
            texts = []
            for segment in segments:
                if not texts and timeline is not None:
                    timeline.mark("stt_first")
                texts.append(segment.text.strip())
            text = " ".join(texts).strip()
            if timeline is not None:
                timeline.mark("stt_done")
        return _drop_hallucinations(text), language


_HALLUCINATIONS = {
    "thank you.", "thanks for watching!", "thank you for watching.", "you", "bye.",
    "thanks for watching.", "subtitles by the amara.org community",
}


def _drop_hallucinations(text: str) -> str:
    return "" if text.strip().lower() in _HALLUCINATIONS else text
