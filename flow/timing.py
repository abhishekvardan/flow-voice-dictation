"""Per-dictation latency timeline.

Marks are perf_counter timestamps recorded as the dictation moves through the pipeline; phases are
the spans between them. "total" is the latency the user feels: from releasing the hotkey until the
paste keystroke has been sent to the focused app.
"""

from __future__ import annotations

import time

# (label, start mark, end mark)
PHASES = [
    ("Recording", "rec_start", "rec_stop"),
    ("Mic open", "rec_start", "mic_open"),
    ("Audio prep", "rec_stop", "audio_ready"),
    ("Queue wait", "audio_ready", "job_start"),
    ("STT setup (VAD/lang)", "stt_start", "stt_prepared"),
    ("STT first segment", "stt_start", "stt_first"),
    ("STT total", "stt_start", "stt_done"),
    ("LLM TTFT", "llm_start", "llm_first_token"),
    ("LLM generation", "llm_first_token", "llm_done"),
    ("LLM total", "llm_start", "llm_done"),
    ("Post-processing", "post_start", "post_done"),
    ("Wait for key release", "insert_start", "keys_released"),
    ("Insertion", "keys_released", "insert_sent"),
    ("Clipboard restore", "insert_sent", "clipboard_restored"),
    ("Total (release → text)", "rec_stop", "insert_sent"),
]


class Timeline:
    def __init__(self) -> None:
        self.marks: dict[str, float] = {}
        self.info: dict[str, object] = {}

    def mark(self, name: str) -> None:
        self.marks[name] = time.perf_counter()

    def ms(self, start: str, end: str) -> float | None:
        if start in self.marks and end in self.marks:
            return (self.marks[end] - self.marks[start]) * 1000
        return None

    def phases(self) -> dict[str, float]:
        out = {}
        for label, start, end in PHASES:
            value = self.ms(start, end)
            if value is not None:
                out[label] = value
        return out

    def report(self) -> str:
        lines = []
        for label, value in self.phases().items():
            text = f"{value / 1000:.2f} s" if label == "Recording" else f"{value:.0f} ms"
            lines.append(f"  {label:<24} {text}")
        for key, value in self.info.items():
            lines.append(f"  {key:<24} {value}")
        return "\n".join(lines)

    def compact(self) -> str:
        """One line for the overlay."""
        p = self.phases()
        parts = []
        for label, short in (("STT total", "STT"), ("LLM TTFT", "TTFT"), ("LLM total", "LLM"),
                             ("Insertion", "Insert"), ("Total (release → text)", "Total")):
            if label in p:
                parts.append(f"{short} {p[label]:.0f}ms")
        return " · ".join(parts)
