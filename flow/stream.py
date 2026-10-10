"""Transcribe while the user is still speaking.

Whisper can only start once audio exists, so the cost of a long dictation is paid after the hotkey
is released - 1.3 s for 17 s of speech, 2.8 s for 50 s. This moves most of that work into the time
the user spends talking: whenever they pause, the audio since the last cut is transcribed in the
background, and releasing the key only transcribes the short tail.

Cuts are made at pauses, not at fixed intervals, so no chunk ends mid-word.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol

import numpy as np

from .config import Config

log = logging.getLogger(__name__)

POLL_SECONDS = 0.15
CUT_SILENCE = 0.45     # a pause this long is a safe place to cut
MIN_CHUNK_SECONDS = 2.0   # below this, a chunk costs more than it saves
MAX_CHUNK_SECONDS = 10.0  # cut anyway, so the tail at release stays short
QUIET_SEARCH_SECONDS = 1.5  # when forced to cut, look here for the quietest moment
QUIET_WINDOW = 1600  # 100 ms at 16 kHz


def quietest_cut(audio: np.ndarray) -> int:
    """Index of the quietest 100 ms window near the end: the least bad place to cut mid-speech."""
    span = min(len(audio), int(QUIET_SEARCH_SECONDS * 16000))
    if span < 2 * QUIET_WINDOW:
        return len(audio)
    tail = audio[len(audio) - span:]
    windows = tail[: len(tail) // QUIET_WINDOW * QUIET_WINDOW].reshape(-1, QUIET_WINDOW)
    energies = np.sqrt(np.mean(windows * windows, axis=1))
    quietest = int(np.argmin(energies))
    return len(audio) - span + (quietest + 1) * QUIET_WINDOW


class AudioSource(Protocol):
    silence_seconds: float

    @property
    def frame_count(self) -> int: ...

    def snapshot_from(self, frame: int) -> np.ndarray: ...


class StreamingTranscriber:
    """Runs alongside a recording, transcribing finished pieces as pauses appear."""

    def __init__(self, transcriber, cfg: Config, vocabulary: list[str], source: AudioSource):
        self._transcriber = transcriber
        self._cfg = cfg
        self._vocabulary = vocabulary
        self._source = source
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cursor = 0            # frames already transcribed
        self._pieces: list[str] = []
        self.language = ""
        self.chunks = 0
        self.seconds_ahead = 0.0    # audio transcribed before the user let go

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="flow-stream-stt")
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()

    def finish(self, timeout: float = 30.0) -> tuple[str, str]:
        """Transcribes whatever is left and returns (text, language)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        tail = self._source.snapshot_from(self._cursor)
        if len(tail) > 0.25 * 16000:
            text, language = self._transcribe(tail)
            if text:
                self._pieces.append(text)
            self.language = self.language or language
        with self._lock:
            return " ".join(piece for piece in self._pieces if piece).strip(), self.language

    # ------------------------------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            time.sleep(POLL_SECONDS)
            if self._stop.is_set():
                break
            pending = self._source.frame_count - self._cursor
            pending_seconds = pending / 16000
            at_pause = self._source.silence_seconds >= CUT_SILENCE
            too_long = pending_seconds >= MAX_CHUNK_SECONDS
            if pending_seconds < MIN_CHUNK_SECONDS or not (at_pause or too_long):
                continue
            end = self._source.frame_count
            chunk = self._source.snapshot_from(self._cursor)[: end - self._cursor]
            if len(chunk) == 0:
                continue
            if too_long and not at_pause:
                # Mid-sentence cut: at least land it in the quietest moment available.
                keep = quietest_cut(chunk)
                chunk, end = chunk[:keep], self._cursor + keep
            started = time.perf_counter()
            text, language = self._transcribe(chunk)
            self._cursor = end
            self.chunks += 1
            self.seconds_ahead += len(chunk) / 16000
            self.language = self.language or language
            with self._lock:
                if text:
                    self._pieces.append(text)
            log.debug("Streamed %.1fs chunk in %.0f ms: %r",
                      len(chunk) / 16000, (time.perf_counter() - started) * 1000, text)

    def _transcribe(self, audio: np.ndarray) -> tuple[str, str]:
        try:
            # After the first chunk the language is known: reuse it so later chunks skip detection
            # and cannot drift to another language mid-dictation.
            return self._transcriber.transcribe(audio, self._cfg, self._vocabulary,
                                                language=self.language or None)
        except Exception:
            log.exception("Streaming chunk failed")
            return "", ""
