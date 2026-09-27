"""Latency benchmark for the real dictation pipeline (same code the app runs).

    uv run python bench/benchmark.py --label before
    uv run python bench/benchmark.py --label after --insert
    uv run python bench/benchmark.py --compare before after

Speech samples are synthesized once with Windows text-to-speech (no extra dependencies).
Each sample is run --runs times after one warm-up pass; the median is reported.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flow.config import Config  # noqa: E402
from flow.context import WindowContext  # noqa: E402
from flow.db import Database  # noqa: E402
from flow.dictionary import Dictionary  # noqa: E402
from flow.llm import OllamaClient  # noqa: E402
from flow.pipeline import process  # noqa: E402
from flow.stt import Transcriber  # noqa: E402
from flow.timing import Timeline  # noqa: E402

BENCH = Path(__file__).resolve().parent
SAMPLES = {
    "short": "um yeah that sounds good to me",
    "medium": "so um I think we should uh probably move the design review to thursday "
              "because the the new build is not ready yet",
    "long": "okay so here is the update um the login bug is fixed and deployed to staging "
            "uh we still need to test the password reset flow and the the email templates "
            "and I think we can ship everything to production on friday if QA signs off by "
            "wednesday evening you know so please let me know if anything is blocking you",
}
COLUMNS = [
    ("STT setup (VAD/lang)", "STT setup"),
    ("STT total", "STT"),
    ("LLM TTFT", "LLM TTFT"),
    ("LLM generation", "LLM gen"),
    ("LLM total", "LLM"),
    ("Post-processing", "Post"),
    ("Insertion", "Insert"),
    ("Processing total", "Total"),
]


def synthesize(name: str, text: str) -> Path:
    folder = BENCH / "samples"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.wav"
    if not path.exists():
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
            "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono);"
            f"$s.SetOutputToWaveFile('{path}', $f); $s.Speak('{text}'); $s.Dispose()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    return path


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


class InsertTarget:
    """A focused Qt text box to paste into, so insertion is measured end to end."""

    def __init__(self):
        from PySide6.QtWidgets import QApplication, QPlainTextEdit

        self.app = QApplication.instance() or QApplication([])
        self.box = QPlainTextEdit()
        self.box.setWindowTitle("Flow benchmark target")
        self.box.resize(500, 200)
        self.box.show()
        self.box.activateWindow()
        self.box.raise_()
        self.box.setFocus()
        self.pump(0.5)

    def pump(self, seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def insert(self, inserter, text: str, timeline: Timeline) -> bool:
        self.box.clear()
        self.box.activateWindow()
        self.box.setFocus()
        self.pump(0.2)
        import win32gui

        from flow import winkeys

        # Windows only lets the process that produced the last input take focus: send a no-op key first.
        hwnd = int(self.box.winId())
        winkeys.send_chord(winkeys.VK_MASK)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        self.pump(0.2)
        if win32gui.GetForegroundWindow() != int(self.box.winId()):
            print("  (skipping insertion: benchmark window is not focused)")
            return False
        worker = threading.Thread(target=inserter.insert, args=(text, "paste"), kwargs={"timeline": timeline})
        worker.start()
        while worker.is_alive():
            self.pump(0.01)
        self.pump(0.1)
        ok = self.box.toPlainText().strip() == text.strip()
        if not ok:
            print(f"  (insert mismatch: box contains {self.box.toPlainText()!r}, focused={win32gui.GetForegroundWindow() == hwnd})")
        return ok


def run(args) -> None:
    cfg = Config()
    cfg.whisper_model = args.whisper_model
    cfg.whisper_device = args.device
    cfg.ollama_model = args.ollama_model
    cfg.cleanup_enabled = not args.raw
    cfg.language = args.language
    cfg.whisper_beam_size = args.beam

    transcriber = Transcriber()
    t0 = time.perf_counter()
    print(f"Loading Whisper ({cfg.whisper_model}, device={cfg.whisper_device})…", flush=True)
    info = transcriber.load(cfg)
    print(f"  {info} in {time.perf_counter() - t0:.1f}s")
    llm = OllamaClient(cfg.ollama_url, cfg.ollama_model, 120)
    dictionary = Dictionary(Database(Path(tempfile.mkdtemp()) / "bench.db"))
    ctx = WindowContext(0, "notepad.exe", "Untitled - Notepad")  # default (formal) style

    target = inserter = None
    if args.insert:
        from flow.inserter import Inserter

        inserter = Inserter()
        target = InsertTarget()

    if args.cold and not args.raw:
        llm._post("/api/generate", {"model": llm.model, "keep_alive": 0}, timeout=60)  # unload
        time.sleep(1)

    results = {"label": args.label, "config": {
        "whisper": info, "beam": args.beam, "ollama_model": cfg.ollama_model, "raw_mode": args.raw}, "samples": {}}
    for name, text in SAMPLES.items():
        audio = load_wav(synthesize(name, text))
        runs = []
        for i in range(args.runs + 1):
            timeline = Timeline()
            result = process(audio, mode="dictate", ctx=ctx, cfg=cfg, transcriber=transcriber, llm=llm,
                             dictionary=dictionary, capture_selection=lambda: "", timeline=timeline)
            inserted = None
            if target is not None:
                inserted = target.insert(inserter, result.final, timeline)
            phases = timeline.phases()
            # Pipeline time only; excludes the benchmark's own window-focusing between the two parts.
            total = timeline.ms("stt_start", "post_done")
            if "insert_sent" in timeline.marks:
                total += timeline.ms("insert_start", "insert_sent")
            phases["Processing total"] = total
            label = "warm-up (first pass)" if i == 0 else f"run {i}"
            print(f"\n[{name} · {len(audio) / 16000:.1f}s audio · {label}] raw={result.raw!r}\n"
                  f"  final={result.final!r}" + (f"  inserted_ok={inserted}" if inserted is not None else ""))
            print(timeline.report())
            print(f"  {'Processing total':<24} {phases['Processing total']:.0f} ms")
            if i == 0:
                results.setdefault("first_pass", {})[name] = phases
                continue
            runs.append(phases)
        median = {key: statistics.median(r[key] for r in runs if key in r)
                  for key in runs[0]}
        results["samples"][name] = {"audio_s": round(len(audio) / 16000, 2), "median_ms": median,
                                    "final": result.final}

    out = BENCH / "results"
    out.mkdir(exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print_table([results])
    if target is not None:
        target.box.close()


def fmt(value) -> str:
    return "—" if value is None else f"{value:.0f}"


def print_table(all_results: list[dict]) -> None:
    header = f"{'run':<10}{'sample':<8}{'audio':>6}" + "".join(f"{short:>11}" for _, short in COLUMNS)
    print("\nMedian latency (ms)\n" + header + "\n" + "-" * len(header))
    for results in all_results:
        for name, sample in results["samples"].items():
            m = sample["median_ms"]
            print(f"{results['label']:<10}{name:<8}{sample['audio_s']:>5.1f}s"
                  + "".join(f"{fmt(m.get(key)):>11}" for key, _ in COLUMNS))


def compare(labels: list[str]) -> None:
    loaded = [json.loads((BENCH / "results" / f"{label}.json").read_text(encoding="utf-8")) for label in labels]
    for results in loaded:
        print(f"{results['label']}: {results['config']}")
    print_table(loaded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="run")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--whisper-model", default=Config.whisper_model)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--ollama-model", default=Config.ollama_model)
    parser.add_argument("--language", default="auto")
    parser.add_argument("--beam", type=int, default=0, help="Whisper beam size (0 = app default)")
    parser.add_argument("--raw", action="store_true", help="raw dictation mode (no LLM)")
    parser.add_argument("--insert", action="store_true", help="also paste into a test window")
    parser.add_argument("--cold", action="store_true", help="unload the Ollama model first to measure loading")
    parser.add_argument("--compare", nargs="+", metavar="LABEL")
    args = parser.parse_args()
    if args.compare:
        compare(args.compare)
    else:
        run(args)


if __name__ == "__main__":
    main()
