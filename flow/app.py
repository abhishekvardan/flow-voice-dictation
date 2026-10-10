"""Application wiring: hotkeys -> recording -> transcription -> cleanup -> insertion."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import winreg
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config
from .audio import SAMPLE_RATE, Recorder, Sounds, is_silent
from .config import Config, data_dir
from .context import WindowContext, active_window
from .db import Database
from .dictionary import Dictionary
from .history import History
from .hotkeys import HotkeyEngine
from . import languages
from .inserter import Inserter
from .llm import OllamaClient, OllamaError
from .pipeline import process
from .stt import Transcriber, model_for_language
from .timing import Timeline
from .ui.icons import mic_icon
from .ui.overlay import Overlay
from . import winkeys
from .winkeys import KeyboardHook, run_on_hook_capture

log = logging.getLogger(__name__)

TRAY_LANGUAGES = ["en", "hi", "mr", "ta", "te", "bn", "es", "fr", "de", "ja", "zh"]
WARM_AFTER_SECONDS = 120  # re-warm if the model has been idle long enough to be evicted
REVEAL_DELAY_MS = 150  # don't flash the overlay for accidental taps
MIN_AUDIO_SECONDS = 0.3


@dataclass
class Session:
    id: int
    mode: str
    handsfree: bool
    ctx: WindowContext
    started: float = field(default_factory=time.monotonic)
    revealed: bool = False
    timeline: Timeline = field(default_factory=Timeline)


class Signals(QObject):
    hk_start = Signal(str, bool)
    hk_mode = Signal(str, bool)
    hk_stop = Signal()
    hk_cancel = Signal(bool)
    job_done = Signal(object)
    job_failed = Signal(str)
    status_changed = Signal()
    combo_captured = Signal(str)
    action = Signal(str)
    warning = Signal(str)


class FlowApp(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.cfg: Config = config.load()
        self.db = Database(data_dir() / "flow.db")
        self.dictionary = Dictionary(self.db)
        self.history = History(self.db)
        self.history.prune(self.cfg.history_retention_days)

        self.recorder = Recorder()
        self.sounds = Sounds()
        self.sounds.enabled = self.cfg.sounds
        self.transcriber = Transcriber()
        self.llm = OllamaClient(self.cfg.ollama_url, self.cfg.ollama_model, self.cfg.llm_timeout)
        self.inserter = Inserter()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flow-job")

        self.whisper_status = "Speech model: loading…"
        self.ollama_status = "Ollama: connecting…"
        self.paused = False
        self.debug_latency = self.cfg.debug_latency or os.environ.get("FLOW_DEBUG") == "1"
        self._session: Session | None = None
        self._session_counter = 0
        self._pending_jobs = 0
        self._capture_cb: Callable[[str], None] | None = None
        self._last_warning = ("", 0.0)
        self._last_llm_use = 0.0
        self._warming = False
        self.settings_window = None
        self.fixup_panel = None
        self.last: dict = {}

        self.signals = Signals()
        s = self.signals
        s.hk_start.connect(self._on_start)
        s.hk_mode.connect(self._on_mode)
        s.hk_stop.connect(self._on_stop)
        s.hk_cancel.connect(self._on_cancel)
        s.job_done.connect(self._on_job_done)
        s.job_failed.connect(self._on_job_failed)
        s.status_changed.connect(self._refresh_tray)
        s.combo_captured.connect(self._on_combo_captured)
        s.warning.connect(self._show_warning)
        s.action.connect(self._on_action)

        self.engine = HotkeyEngine(
            on_start=s.hk_start.emit,
            on_stop=s.hk_stop.emit,
            on_cancel=s.hk_cancel.emit,
            on_mode_change=s.hk_mode.emit,
            on_action=s.action.emit,
        )
        self._apply_hotkeys()
        self.hook = KeyboardHook(self.engine)

        self.overlay = Overlay(lambda: self.recorder.level)
        self.overlay.stop_clicked.connect(self._ui_stop)
        self.overlay.cancel_clicked.connect(self._ui_cancel)

        self._limit_timer = QTimer(self)
        self._limit_timer.setInterval(250)
        self._limit_timer.timeout.connect(self._check_limit)

        self._build_tray()

    # Lifecycle ----------------------------------------------------------------------------------
    def start(self) -> None:
        self.hook.start()
        self.tray.show()
        threading.Thread(target=self._load_whisper, daemon=True, name="flow-load-whisper").start()
        threading.Thread(target=self._check_ollama, daemon=True, name="flow-load-ollama").start()
        log.info("Flow started. Dictate: %s | Hands-free: %s | Command: %s",
                 self.cfg.hotkey_dictate, self.cfg.hotkey_handsfree, self.cfg.hotkey_command)

    def quit(self) -> None:
        self.hook.stop()
        self.recorder.cancel()
        self.tray.hide()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.qapp.quit()

    def _load_whisper(self) -> None:
        self.whisper_status = f"Speech model: loading {model_for_language(self.cfg)}…"
        self.signals.status_changed.emit()
        try:
            info = self.transcriber.load(self.cfg)
            self.whisper_status = f"Speech model: {info}"
        except Exception as exc:
            log.exception("Whisper load failed")
            self.whisper_status = "Speech model: failed to load"
            self._warn(f"Speech model failed to load: {exc}")
        self.signals.status_changed.emit()

    def _check_ollama(self) -> None:
        try:
            models = self.llm.list_models()
            wanted = self.llm.model
            if wanted not in models and f"{wanted}:latest" not in models:
                self.ollama_status = f"Ollama: model '{wanted}' not installed"
                self._warn(f"Ollama model '{wanted}' is not installed. Run: ollama pull {wanted}")
            else:
                self.ollama_status = f"Ollama: warming up {wanted}…"
                self.signals.status_changed.emit()
                self.llm.warmup()
                self.ollama_status = f"Ollama: {wanted}"
        except OllamaError as exc:
            self.ollama_status = "Ollama: not reachable"
            if self.cfg.cleanup_enabled:
                self._warn(f"{exc}. Dictation will paste raw transcripts.")
        self.signals.status_changed.emit()

    # Config -------------------------------------------------------------------------------------
    def _apply_hotkeys(self) -> None:
        self.engine.configure(
            self.cfg.hotkey_dictate, self.cfg.hotkey_handsfree, self.cfg.hotkey_command,
            self.cfg.double_tap_handsfree,
            actions={"fixup": self.cfg.hotkey_fixup},
        )

    def apply_config(self, new: Config) -> None:
        old, self.cfg = self.cfg, new
        config.save(new)
        self._apply_hotkeys()
        self.sounds.enabled = new.sounds
        if self._cleanup_action.isChecked() != new.cleanup_enabled:
            self._cleanup_action.setChecked(new.cleanup_enabled)
        for action in self._language_group.actions():
            code = "auto" if action.text().startswith("Detect") else action.text().split("(")[-1].rstrip(")")
            action.setChecked(code == new.language)
        self.debug_latency = new.debug_latency or os.environ.get("FLOW_DEBUG") == "1"
        self.llm.configure(new.ollama_url, new.ollama_model, new.llm_timeout)
        if (old.whisper_model, old.whisper_device, old.whisper_compute_type, old.language,
                str(old.language_models)) != (
            new.whisper_model, new.whisper_device, new.whisper_compute_type, new.language,
            str(new.language_models)
        ):
            threading.Thread(target=self._load_whisper, daemon=True).start()
        if (old.ollama_url, old.ollama_model) != (new.ollama_url, new.ollama_model):
            threading.Thread(target=self._check_ollama, daemon=True).start()
        if old.launch_at_login != new.launch_at_login:
            try:
                set_launch_at_login(new.launch_at_login)
            except OSError:
                log.exception("Could not update launch-at-login")

    def begin_combo_capture(self, callback: Callable[[str], None]) -> None:
        if self._capture_cb is not None:
            self._capture_cb("")
        self._capture_cb = callback
        run_on_hook_capture(self.hook, self.signals.combo_captured.emit)

    def cancel_combo_capture(self) -> None:
        self.hook.capture = None
        callback, self._capture_cb = self._capture_cb, None
        if callback:
            callback("")

    def _on_combo_captured(self, combo: str) -> None:
        callback, self._capture_cb = self._capture_cb, None
        if callback:
            callback(combo)

    # Recording ----------------------------------------------------------------------------------
    def _on_start(self, mode: str, handsfree: bool) -> None:
        if self._session is not None:
            self.recorder.cancel()
        self._session_counter += 1
        timeline = Timeline()
        timeline.mark("rec_start")
        session = Session(self._session_counter, mode, handsfree, active_window(), timeline=timeline)
        try:
            self.recorder.start(self.cfg.input_device, self.cfg.max_recording_seconds)
            timeline.mark("mic_open")
        except Exception as exc:
            log.exception("Could not open microphone")
            self.engine.external_stop()
            self._session = None
            self.sounds.play("error")
            self.overlay.show_message(f"Microphone unavailable: {exc}")
            return
        self._session = session
        self._limit_timer.start()
        self._warm_llm()
        if handsfree:
            self._reveal(session.id)
        else:
            QTimer.singleShot(REVEAL_DELAY_MS, lambda sid=session.id: self._reveal(sid))

    def _warm_llm(self) -> None:
        """Loads the cleanup model in the background while recording, hiding Ollama's load time."""
        if not self.cfg.cleanup_enabled or self._warming:
            return
        if time.monotonic() - self._last_llm_use < WARM_AFTER_SECONDS:
            return  # still resident in Ollama
        self._warming = True

        def work() -> None:
            try:
                self.llm.warmup()
                self._last_llm_use = time.monotonic()
                log.info("Warmed %s while recording", self.llm.model)
            except OllamaError as exc:
                log.info("Could not warm Ollama: %s", exc)
            finally:
                self._warming = False

        threading.Thread(target=work, daemon=True, name="flow-warm").start()

    def _reveal(self, session_id: int) -> None:
        session = self._session
        if session is None or session.id != session_id or session.revealed:
            return
        session.revealed = True
        self.sounds.play("start")
        self.overlay.show_recording(session.mode, session.handsfree)
        self._set_icon("command" if session.mode == "command" else "recording")

    def _on_mode(self, mode: str, handsfree: bool) -> None:
        session = self._session
        if session is None:
            return
        session.mode, session.handsfree = mode, handsfree
        if not session.revealed:
            self._reveal(session.id)
        else:
            self.overlay.set_mode(mode, handsfree)
            self._set_icon("command" if mode == "command" else "recording")

    def _on_stop(self) -> None:
        session, self._session = self._session, None
        self._limit_timer.stop()
        if session is None:
            return
        session.timeline.mark("rec_stop")
        audio = self.recorder.stop(session.timeline)
        duration = len(audio) / SAMPLE_RATE
        silent = duration < MIN_AUDIO_SECONDS or is_silent(audio)
        session.timeline.mark("audio_ready")
        if silent:
            if duration >= 0.8:
                self.overlay.show_message("No audio detected. Check your microphone.", ms=2000)
            else:
                self._settle_ui()
            return
        self.sounds.play("stop")
        self._pending_jobs += 1
        self.overlay.show_processing()
        self._set_icon("processing")
        self.executor.submit(self._run_job, session, audio, duration, self.cfg)

    def _on_cancel(self, was_tap: bool) -> None:
        session, self._session = self._session, None
        self._limit_timer.stop()
        self.recorder.cancel()
        if session is not None and session.revealed and not was_tap:
            self.overlay.show_message("Cancelled", error=False, ms=900)
            self._set_icon("idle")
        else:
            self._settle_ui()

    def _ui_stop(self) -> None:
        self.engine.external_stop()
        self._on_stop()

    def _ui_cancel(self) -> None:
        self.engine.external_stop()
        self._on_cancel(False)

    def _check_limit(self) -> None:
        if self._session is not None and self.recorder.limit_reached:
            log.info("Recording limit reached; stopping")
            self._ui_stop()

    # Processing (worker thread) -----------------------------------------------------------------
    def _run_job(self, session: Session, audio, duration: float, cfg: Config) -> None:
        timeline = session.timeline
        timeline.mark("job_start")
        ctx = session.ctx
        try:
            result = process(
                audio, mode=session.mode, ctx=ctx, cfg=cfg, transcriber=self.transcriber, llm=self.llm,
                dictionary=self.dictionary, capture_selection=self.inserter.capture_selection,
                timeline=timeline,
            )
            log.info("Transcribed %.1fs audio in %.0f ms: %r", duration, timeline.ms("stt_start", "stt_done") or 0, result.raw)
            if result.empty:
                self.signals.job_done.emit({"empty": True})
                return
            llm_ms = timeline.ms("llm_start", "llm_done") or 0
            if result.llm_used:
                self._last_llm_use = time.monotonic()
            log.info("Inserting into %s (%s, llm %.0f ms): %r", ctx.process or "?", result.style, llm_ms, result.final)
            self.inserter.insert(result.final, cfg.paste_mode, timeline=timeline)
            log.info("Latency breakdown (%s, %s):\n%s", session.mode, result.style, timeline.report())
            if cfg.history_enabled:
                self.history.add(
                    mode=session.mode, app=ctx.process, style=result.style, raw=result.raw,
                    final=result.final.rstrip(), duration=duration,
                    stt_ms=int(timeline.ms("stt_start", "stt_done") or 0), llm_ms=int(llm_ms),
                )
            self.last = {
                "raw": result.raw, "tidied": result.tidied, "final": result.final.rstrip(),
                "style": result.style, "language": result.language, "app": ctx.process,
                "hwnd": ctx.hwnd, "llm_rejected": result.llm_rejected, "timing": timeline.compact(),
            }
            self.signals.job_done.emit({"final": result.final, "warning": result.warning,
                                        "timing": timeline.compact()})
        except OllamaError as exc:
            self.signals.job_failed.emit(str(exc))
        except Exception as exc:
            log.exception("Dictation failed")
            self.signals.job_failed.emit(f"Dictation failed: {exc}")

    def _on_job_done(self, result: dict) -> None:
        self._pending_jobs = max(0, self._pending_jobs - 1)
        if result.get("warning"):
            self._warn(result["warning"])
            if self._session is None:
                self.overlay.show_message(result["warning"])
        elif result.get("empty") and self._session is None and self._pending_jobs == 0:
            self.overlay.show_message("No speech detected", error=False, ms=1400)
        elif self.debug_latency and result.get("timing") and self._session is None and self._pending_jobs == 0:
            self.overlay.show_message(result["timing"], error=False, ms=5000)
        self._settle_ui()

    def _on_job_failed(self, message: str) -> None:
        self._pending_jobs = max(0, self._pending_jobs - 1)
        self.sounds.play("error")
        if self._session is None:
            self.overlay.show_message(message, ms=3500)
        self._settle_ui()

    def _settle_ui(self) -> None:
        """Brings overlay and tray icon in line with the current state."""
        if self._session is not None:
            return
        if self._pending_jobs:
            if self.overlay.state != "message":
                self.overlay.show_processing()
            self._set_icon("processing")
            return
        if self.overlay.state in ("recording", "processing"):
            self.overlay.hide_overlay()
        self._set_icon("paused" if self.paused else "idle")

    # Tray ---------------------------------------------------------------------------------------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(mic_icon("idle"), self)
        menu = QMenu()
        self._tray_menu = menu
        self._whisper_action = menu.addAction(self.whisper_status)
        self._whisper_action.setEnabled(False)
        self._ollama_action = menu.addAction(self.ollama_status)
        self._ollama_action.setEnabled(False)
        menu.addSeparator()
        self._language_menu = menu.addMenu("Language")
        self._language_group = QActionGroup(menu)
        self._language_group.setExclusive(True)
        for code in ["auto"] + TRAY_LANGUAGES:
            label = "Detect automatically" if code == "auto" else f"{languages.name(code)} ({code})"
            action = QAction(label, menu, checkable=True)
            action.setChecked(self.cfg.language == code)
            action.triggered.connect(lambda _checked=False, c=code: self.set_language(c))
            self._language_group.addAction(action)
            self._language_menu.addAction(action)
        self._cleanup_action = QAction("AI cleanup (off = raw dictation, fastest)", menu, checkable=True)
        self._cleanup_action.setChecked(self.cfg.cleanup_enabled)
        self._cleanup_action.toggled.connect(self.set_cleanup_enabled)
        menu.addAction(self._cleanup_action)
        self._pause_action = QAction("Pause Flow", menu, checkable=True)
        self._pause_action.toggled.connect(self.set_paused)
        menu.addAction(self._pause_action)
        self._recent_menu = menu.addMenu("Recent dictations")
        self._recent_menu.aboutToShow.connect(self._fill_recent)
        menu.addAction("Last dictation…", self.open_fixup)
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit Flow", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self._refresh_tray()

    def _refresh_tray(self) -> None:
        self._whisper_action.setText(self.whisper_status)
        self._ollama_action.setText(self.ollama_status)
        combo = self.cfg.hotkey_dictate.replace("+", " + ")
        state = "paused" if self.paused else f"hold {combo} to dictate"
        self.tray.setToolTip(f"Flow – {state}")
        if self.settings_window is not None:
            self.settings_window.refresh_status()

    def _fill_recent(self) -> None:
        self._recent_menu.clear()
        entries = self.history.recent(8)
        if not entries:
            self._recent_menu.addAction("No dictations yet").setEnabled(False)
            return
        for entry in entries:
            label = entry.final.replace("\n", " ")
            label = label if len(label) <= 60 else label[:57] + "…"
            action = self._recent_menu.addAction(label)
            action.setToolTip("Click to copy")
            action.triggered.connect(lambda _=False, text=entry.final: QGuiApplication.clipboard().setText(text))

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_settings()

    def _set_icon(self, state: str) -> None:
        if state == "idle" and self.paused:
            state = "paused"
        self.tray.setIcon(mic_icon(state))

    def set_language(self, code: str) -> None:
        if code == self.cfg.language:
            return
        cfg = self.cfg.copy()
        cfg.language = code
        self.apply_config(cfg)

    def set_cleanup_enabled(self, enabled: bool) -> None:
        if enabled == self.cfg.cleanup_enabled:
            return
        cfg = self.cfg.copy()
        cfg.cleanup_enabled = enabled
        self.apply_config(cfg)
        if self.settings_window is not None:
            self.settings_window.cleanup_enabled.setChecked(enabled)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.engine.enabled = not paused
        if paused and self._session is not None:
            self._ui_cancel()
        if self._pause_action.isChecked() != paused:
            self._pause_action.setChecked(paused)
        self._set_icon("paused" if paused else "idle")
        self._refresh_tray()

    def _warn(self, message: str) -> None:
        """Thread-safe tray warning."""
        self.signals.warning.emit(message)

    def _show_warning(self, message: str) -> None:
        # Throttled so repeated failures don't spam notifications.
        last, when = self._last_warning
        if message == last and time.monotonic() - when < 300:
            return
        self._last_warning = (message, time.monotonic())
        log.warning(message)
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage("Flow", message, QSystemTrayIcon.Warning, 6000)

    def _on_action(self, name: str) -> None:
        if name == "fixup":
            self.open_fixup()

    def open_fixup(self) -> None:
        from .ui.fixup import FixupPanel

        if self.fixup_panel is None:
            self.fixup_panel = FixupPanel(self)
        self.fixup_panel.refresh()
        self.fixup_panel.show()
        self.fixup_panel.raise_()
        self.fixup_panel.activateWindow()

    def insert_into_previous_window(self, text: str, hwnd: int) -> None:
        """Gives focus back to the app you dictated into, then pastes."""
        def work() -> None:
            try:
                if hwnd:
                    winkeys.focus_window(hwnd)
                    time.sleep(0.15)
                self.inserter.insert(text, self.cfg.paste_mode)
            except Exception as exc:
                log.exception("Could not insert from the fix-up panel")
                self.signals.job_failed.emit(f"Could not insert: {exc}")

        threading.Thread(target=work, daemon=True, name="flow-fixup-insert").start()

    def open_settings(self) -> None:
        from .ui.settings import SettingsWindow

        if self.settings_window is None:
            self.settings_window = SettingsWindow(self)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()


def set_launch_at_login(enabled: bool) -> None:
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            script = Path(__file__).resolve().parent.parent / "run.pyw"
            winreg.SetValueEx(key, "Flow", 0, winreg.REG_SZ, f'"{pythonw}" "{script}"')
        else:
            try:
                winreg.DeleteValue(key, "Flow")
            except FileNotFoundError:
                pass
