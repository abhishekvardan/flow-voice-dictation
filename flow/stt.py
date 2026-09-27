"""Speech-to-text with faster-whisper (GPU when available, CPU fallback)."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from pathlib import Path

import numpy as np

from .config import Config, data_dir

log = logging.getLogger(__name__)

SAMPLE_WARMUP = 16000


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


CPU_SLOW_MODELS = {"small", "medium", "large-v3", "large-v3-turbo", "large-v2", "distil-large-v3"}


def resolve_model_name(name: str, device: str) -> str:
    """'auto' picks the most accurate model that is still fast on the detected hardware."""
    if name in ("", "auto"):
        return "small" if device == "cuda" else "base"
    return name


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


class Transcriber:
    def __init__(self):
        self._model = None
        self._key: tuple | None = None
        self._lock = threading.Lock()
        self.device = "cpu"
        self.device_info = ""
        self.error = ""
        _add_cuda_dll_dirs()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self, cfg: Config) -> str:
        """Loads (or reloads) the model if the settings changed. Returns a status string."""
        key = (cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute_type)
        with self._lock:
            if self._model is not None and self._key == key:
                return self.device_info
            from faster_whisper import WhisperModel

            self._model = None
            attempts = []
            if cfg.whisper_device in ("auto", "cuda") and cuda_available():
                ct = cfg.whisper_compute_type if cfg.whisper_compute_type != "auto" else "int8_float16"
                attempts.append(("cuda", ct))
            if cfg.whisper_device in ("auto", "cpu") or not attempts:
                ct = cfg.whisper_compute_type if cfg.whisper_compute_type != "auto" else "int8"
                if ct in ("float16", "int8_float16"):
                    ct = "int8"
                attempts.append(("cpu", ct))

            last_error: Exception | None = None
            for device, compute_type in attempts:
                name = resolve_model_name(cfg.whisper_model, device)
                if device == "cpu" and name.split(".")[0] in CPU_SLOW_MODELS:
                    log.warning("Whisper '%s' on CPU is slow (measured ~9 s per dictation for 'small' on an "
                                "i7-12650H); choose 'auto', 'base' or 'tiny' for CPU-only machines", name)
                try:
                    log.info("Loading Whisper '%s' on %s (%s)", name, device, compute_type)
                    model = WhisperModel(
                        name,
                        device=device,
                        compute_type=compute_type,
                        download_root=str(data_dir() / "models"),
                        cpu_threads=max(1, (os.cpu_count() or 4) - 2),
                    )
                    segments, _ = model.transcribe(
                        np.zeros(SAMPLE_WARMUP, np.float32), language="en", beam_size=1
                    )
                    list(segments)
                except Exception as exc:
                    log.warning("Whisper failed on %s: %s", device, exc)
                    last_error = exc
                    continue
                self._model, self._key = model, key
                self.device = device
                self.device_info = f"{name} on {device} ({compute_type})"
                self.error = ""
                log.info("Whisper ready: %s", self.device_info)
                return self.device_info
            self.error = str(last_error)
            raise RuntimeError(f"Could not load Whisper model: {last_error}")

    def transcribe(self, audio: np.ndarray, cfg: Config, vocabulary: list[str], timeline=None) -> tuple[str, str]:
        """Returns (text, detected language code)."""
        if self._model is None:
            self.load(cfg)
        with self._lock:
            if timeline is not None:
                timeline.mark("stt_start")
                timeline.info["STT device"] = self.device_info
                timeline.info["STT beam size"] = cfg.whisper_beam_size or (5 if self.device == "cuda" else 2)
                timeline.info["Audio length"] = f"{len(audio) / 16000:.1f} s"
            model = self._model
            prompt = None
            if vocabulary:
                prompt = "Glossary: " + ", ".join(vocabulary[:80]) + "."
            # transcribe() eagerly runs VAD, feature extraction and language detection;
            # the returned generator then decodes segment by segment.
            segments, info = model.transcribe(
                audio,
                language=None if cfg.language in ("", "auto") else cfg.language,
                beam_size=cfg.whisper_beam_size or (5 if self.device == "cuda" else 2),
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
