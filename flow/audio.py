"""Microphone recording and UI sounds."""

from __future__ import annotations

import io
import logging
import math
import struct
import threading
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from .config import data_dir

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


def input_devices() -> list[str]:
    """Input device names on the default host API (avoids MME/WASAPI/WDM duplicates)."""
    try:
        default_api = sd.query_devices(kind="input")["hostapi"]
        return [
            d["name"]
            for d in sd.query_devices()
            if d["max_input_channels"] > 0 and d["hostapi"] == default_api
        ]
    except Exception:
        log.exception("Could not list audio devices")
        return []


class Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._frames = 0
        self._stream: sd.InputStream | None = None
        self._rate = SAMPLE_RATE
        self._max_frames = 0
        self.level = 0.0
        self.limit_reached = False

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self, device: str = "", max_seconds: int = 360) -> None:
        self.cancel()
        self._chunks, self._frames, self.level, self.limit_reached = [], 0, 0.0, False
        dev = device or None
        try:
            stream = self._open(dev, SAMPLE_RATE)
        except Exception:
            rate = int(sd.query_devices(dev, kind="input")["default_samplerate"])
            log.info("Device rejected %d Hz; recording at %d Hz and resampling", SAMPLE_RATE, rate)
            stream = self._open(dev, rate)
        self._max_frames = max_seconds * self._rate
        self._stream = stream
        stream.start()

    def _open(self, device, rate: int) -> sd.InputStream:
        self._rate = rate
        return sd.InputStream(
            samplerate=rate, channels=1, dtype="float32", device=device,
            blocksize=int(rate * 0.03), callback=self._callback,
        )

    def _callback(self, indata, frames, _time, status) -> None:
        if status:
            log.debug("Audio status: %s", status)
        mono = indata[:, 0].copy()
        with self._lock:
            if self._frames >= self._max_frames:
                self.limit_reached = True
                return
            self._chunks.append(mono)
            self._frames += len(mono)
        self.level = float(np.sqrt(np.mean(mono * mono))) if len(mono) else 0.0

    def stop(self, timeline=None) -> np.ndarray:
        """Stops recording and returns 16 kHz mono float32 audio."""
        self._close()
        if timeline is not None:
            timeline.mark("mic_closed")
            timeline.info["Mic sample rate"] = f"{self._rate} Hz" + (" (resampled)" if self._rate != SAMPLE_RATE else "")
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
            self._chunks = []
        if self._rate != SAMPLE_RATE and len(audio):
            n = int(len(audio) * SAMPLE_RATE / self._rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
            ).astype(np.float32)
        return audio

    def cancel(self) -> None:
        self._close()
        with self._lock:
            self._chunks = []

    def _close(self) -> None:
        stream, self._stream = self._stream, None
        self.level = 0.0
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("Error closing audio stream")


def is_silent(audio: np.ndarray, threshold: float = 0.004) -> bool:
    if len(audio) == 0:
        return True
    # Loudest 50 ms window, so short words in a long quiet recording still count.
    win = SAMPLE_RATE // 20
    usable = len(audio) // win * win
    if usable == 0:
        return float(np.sqrt(np.mean(audio * audio))) < threshold
    rms = np.sqrt(np.mean(audio[:usable].reshape(-1, win) ** 2, axis=1))
    return float(rms.max()) < threshold


# Sounds -----------------------------------------------------------------------------------

def _tone(freqs: list[float], duration: float, volume: float = 0.25) -> bytes:
    rate = 44100
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        step = duration / len(freqs)
        for freq in freqs:
            count = int(rate * step)
            for i in range(count):
                env = min(1.0, i / (rate * 0.005)) * min(1.0, (count - i) / (rate * 0.02))
                sample = volume * env * math.sin(2 * math.pi * freq * i / rate)
                frames += struct.pack("<h", int(sample * 32767))
        wav.writeframes(bytes(frames))
    return buf.getvalue()


class Sounds:
    def __init__(self):
        folder = data_dir() / "sounds"
        folder.mkdir(exist_ok=True)
        specs = {
            "start": ([660.0, 880.0], 0.12),
            "stop": ([880.0, 660.0], 0.12),
            "error": ([300.0, 220.0], 0.2),
        }
        self._files: dict[str, Path] = {}
        for name, (freqs, duration) in specs.items():
            path = folder / f"{name}.wav"
            if not path.exists():
                path.write_bytes(_tone(freqs, duration))
            self._files[name] = path
        self.enabled = True

    def play(self, name: str) -> None:
        if not self.enabled or name not in self._files:
            return
        import winsound

        try:
            winsound.PlaySound(
                str(self._files[name]),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except RuntimeError:
            pass
