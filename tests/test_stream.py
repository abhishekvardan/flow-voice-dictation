import time

import numpy as np

from flow.config import Config
from flow.stream import CUT_SILENCE, MIN_CHUNK_SECONDS, StreamingTranscriber


class FakeSource:
    """Stands in for the Recorder: audio grows as the 'speaker' talks."""

    def __init__(self):
        self.audio = np.zeros(0, np.float32)
        self.silence_seconds = 0.0

    def speak(self, seconds: float) -> None:
        self.audio = np.concatenate([self.audio, np.full(int(seconds * 16000), 0.1, np.float32)])
        self.silence_seconds = 0.0

    def pause(self, seconds: float) -> None:
        self.audio = np.concatenate([self.audio, np.zeros(int(seconds * 16000), np.float32)])
        self.silence_seconds = seconds

    @property
    def frame_count(self) -> int:
        return len(self.audio)

    def snapshot_from(self, frame: int) -> np.ndarray:
        return self.audio[max(0, frame):]


class FakeTranscriber:
    """Records what it was asked to transcribe and answers with the chunk length."""

    def __init__(self):
        self.calls: list[float] = []

    def transcribe(self, audio, cfg, vocabulary, timeline=None, language=None):
        self.calls.append(round(len(audio) / 16000, 2))
        self.language_asked = language
        return f"chunk{len(self.calls)}", "en"


def run_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_cuts_at_a_pause_and_only_the_tail_is_left_at_the_end():
    source, fake = FakeSource(), FakeTranscriber()
    streamer = StreamingTranscriber(fake, Config(), [], source)
    streamer.start()

    source.speak(4.0)
    source.pause(CUT_SILENCE + 0.1)
    assert run_until(lambda: streamer.chunks == 1), "a pause after enough speech should cut"
    assert fake.calls[0] >= 4.0

    source.speak(2.5)  # still talking: no new chunk while there is no pause
    assert not run_until(lambda: streamer.chunks == 2, timeout=0.6)

    text, language = streamer.finish()
    assert fake.calls[-1] < 3.0, "only the tail should remain at release"
    assert text == "chunk1 chunk2"
    assert language == "en"


def test_short_bursts_are_not_cut():
    source, fake = FakeSource(), FakeTranscriber()
    streamer = StreamingTranscriber(fake, Config(), [], source)
    streamer.start()
    source.speak(MIN_CHUNK_SECONDS - 1.0)
    source.pause(CUT_SILENCE + 0.2)
    assert not run_until(lambda: streamer.chunks >= 1, timeout=0.6)
    text, _ = streamer.finish()
    assert text == "chunk1"  # done in one piece at the end
    assert len(fake.calls) == 1


def test_language_is_reused_after_the_first_chunk():
    source, fake = FakeSource(), FakeTranscriber()
    streamer = StreamingTranscriber(fake, Config(), [], source)
    streamer.start()
    source.speak(3.0)
    source.pause(CUT_SILENCE + 0.1)
    assert run_until(lambda: streamer.chunks == 1)
    source.speak(3.0)
    source.pause(CUT_SILENCE + 0.1)
    assert run_until(lambda: streamer.chunks == 2)
    streamer.finish()
    assert fake.language_asked == "en"  # detection only happens once


def test_cancel_stops_without_transcribing_more():
    source, fake = FakeSource(), FakeTranscriber()
    streamer = StreamingTranscriber(fake, Config(), [], source)
    streamer.start()
    source.speak(5.0)
    streamer.cancel()
    time.sleep(0.3)
    source.pause(CUT_SILENCE + 0.2)
    time.sleep(0.3)
    assert fake.calls == []
