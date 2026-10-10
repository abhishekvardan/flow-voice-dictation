"""Settings window: General, Shortcuts, Models, Styles, Dictionary, Snippets, History."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from ..audio import input_devices
from ..stt import MODEL_SIZES, downloaded_models, models_dir
from ..config import Config
from ..llm import OllamaClient, OllamaError
from ..styles import BUILTIN_STYLES, STYLE_LABELS, default_rules, style_prompt
from .hotkey_edit import HotkeyEdit
from .icons import mic_icon
from .theme import STYLESHEET as DARK_THEME

WHISPER_MODELS = [
    "auto", "tiny", "base", "small", "medium", "large-v3-turbo", "distil-large-v3",
    "tiny.en", "base.en", "small.en", "medium.en",
]
LANGUAGES = ["auto", "en", "hi", "es", "fr", "de", "it", "pt", "nl", "ru", "ja", "ko", "zh", "ar", "ta", "te", "bn", "mr"]
STYLE_KEYS = list(STYLE_LABELS)

STYLESHEET = """
QWidget { font-size: 10pt; }
QGroupBox { font-weight: 600; margin-top: 14px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QLabel[hint="true"] { color: palette(placeholder-text); font-size: 9pt; }
QPushButton { padding: 5px 12px; }
QPushButton:checked { background: #4f46e5; color: white; }
QTabWidget::pane { border: none; }
"""


def _cache_bytes() -> int:
    return sum(f.stat().st_size for f in models_dir().rglob("*") if f.is_file())


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("hint", True)
    return label


def _select_combo(combo: QComboBox, value: str, data: bool = False) -> None:
    index = combo.findData(value) if data else combo.findText(value)
    if index >= 0:
        combo.setCurrentIndex(index)
    elif combo.isEditable():
        combo.setEditText(value)


def _style_combo(value: str) -> QComboBox:
    combo = QComboBox()
    for key in STYLE_KEYS:
        combo.addItem(STYLE_LABELS[key], key)
    _select_combo(combo, value, data=True)
    return combo


class SettingsWindow(QWidget):
    _models_loaded = Signal(list, str)
    _download_done = Signal(str)
    _vocab_imported = Signal(str)
    _test_finished = Signal(str)

    def __init__(self, app, embedded: bool = False):
        super().__init__()
        self.app = app
        self.embedded = embedded
        self.cfg: Config = app.cfg.copy()
        self._prompts: dict[str, str] = dict(self.cfg.style_prompts)
        self.setWindowTitle("Flow Settings")
        self.setWindowIcon(mic_icon())
        self.resize(820, 620)
        self.setStyleSheet(DARK_THEME + STYLESHEET)
        self._models_loaded.connect(self._on_models_loaded)
        self._test_finished.connect(self._on_test_finished)
        self._download_done.connect(self._on_download_done)
        self._download_timer = QTimer(self)
        self._download_timer.timeout.connect(self._poll_download)
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._update_meter)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._shortcuts_tab(), "Shortcuts")
        self.tabs.addTab(self._models_tab(), "Models")
        self.tabs.addTab(self._styles_tab(), "Styles")
        self.tabs.addTab(self._dictionary_tab(), "Dictionary")
        self.tabs.addTab(self._snippets_tab(), "Snippets")
        self.tabs.addTab(self._skills_tab(), "Skills")
        self.tabs.addTab(self._stats_tab(), "Stats")
        self.tabs.addTab(self._history_tab(), "History")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._saved_label = QLabel("")
        root = QVBoxLayout(self)
        root.addWidget(self.tabs)
        if not embedded:  # standalone window keeps its own buttons
            save = QPushButton("Save")
            save.setDefault(True)
            save.clicked.connect(self._save)
            close = QPushButton("Close")
            close.clicked.connect(self.close)
            buttons = QHBoxLayout()
            buttons.addWidget(self._saved_label)
            buttons.addStretch()
            buttons.addWidget(save)
            buttons.addWidget(close)
            root.addLayout(buttons)

        self.refresh_status()

    # General ------------------------------------------------------------------------------------
    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.mic = QComboBox()
        self.mic.addItem("System default", "")
        for name in input_devices():
            self.mic.addItem(name, name)
        _select_combo(self.mic, self.cfg.input_device, data=True)
        form.addRow("Microphone", self.mic)

        self.paste_mode = QComboBox()
        self.paste_mode.addItem("Paste (fast, restores your clipboard)", "paste")
        self.paste_mode.addItem("Type characters (for apps that block paste)", "type")
        _select_combo(self.paste_mode, self.cfg.paste_mode, data=True)
        form.addRow("Insert text by", self.paste_mode)

        self.trailing_space = QCheckBox("Add a space after each dictation")
        self.trailing_space.setChecked(self.cfg.trailing_space)
        form.addRow("", self.trailing_space)

        self.sounds = QCheckBox("Play sounds when recording starts and stops")
        self.sounds.setChecked(self.cfg.sounds)
        form.addRow("", self.sounds)

        meter_row = QHBoxLayout()
        self.mic_meter = QProgressBar()
        self.mic_meter.setRange(0, 100)
        self.mic_meter.setTextVisible(False)
        self.mic_test = QPushButton("Test microphone")
        self.mic_test.setCheckable(True)
        self.mic_test.toggled.connect(self._toggle_mic_test)
        meter_row.addWidget(self.mic_meter, 1)
        meter_row.addWidget(self.mic_test)
        form.addRow("Input level", meter_row)

        self.auto_stop_silence = QDoubleSpinBox()
        self.auto_stop_silence.setRange(0.0, 30.0)
        self.auto_stop_silence.setSingleStep(0.5)
        self.auto_stop_silence.setSuffix(" s")
        self.auto_stop_silence.setSpecialValueText("Off")
        self.auto_stop_silence.setValue(self.cfg.auto_stop_silence)
        form.addRow("Hands-free: stop after silence", self.auto_stop_silence)

        self.command_mode_output = QComboBox()
        self.command_mode_output.addItem("Replace the selected text", "replace")
        self.command_mode_output.addItem("Show it in the last-dictation panel", "panel")
        _select_combo(self.command_mode_output, self.cfg.command_mode_output, data=True)
        form.addRow("Command mode result", self.command_mode_output)

        self.max_seconds = QSpinBox()
        self.max_seconds.setRange(30, 1800)
        self.max_seconds.setSuffix(" s")
        self.max_seconds.setValue(self.cfg.max_recording_seconds)
        form.addRow("Max recording length", self.max_seconds)

        self.history_enabled = QCheckBox("Save dictation history")
        self.history_enabled.setChecked(self.cfg.history_enabled)
        form.addRow("", self.history_enabled)

        self.retention = QSpinBox()
        self.retention.setRange(0, 3650)
        self.retention.setSpecialValueText("Forever")
        self.retention.setSuffix(" days")
        self.retention.setValue(self.cfg.history_retention_days)
        form.addRow("Keep history for", self.retention)

        self.launch_at_login = QCheckBox("Start Flow when I sign in to Windows")
        self.launch_at_login.setChecked(self.cfg.launch_at_login)
        form.addRow("", self.launch_at_login)

        backup_row = QHBoxLayout()
        export_button = QPushButton("Export settings…")
        import_button = QPushButton("Import settings…")
        export_button.clicked.connect(self._export_settings)
        import_button.clicked.connect(self._import_settings)
        backup_row.addWidget(export_button)
        backup_row.addWidget(import_button)
        backup_row.addStretch()
        form.addRow("Backup", backup_row)

        self.debug_latency = QCheckBox("Show latency breakdown after each dictation (debug)")
        self.debug_latency.setChecked(self.cfg.debug_latency)
        form.addRow("", self.debug_latency)
        form.addRow("", _hint("Full per-stage timings are always written to %APPDATA%\\Flow\\flow.log."))
        return page

    # Shortcuts ----------------------------------------------------------------------------------
    def _shortcuts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.hk_dictate = HotkeyEdit(self.app, self.cfg.hotkey_dictate)
        self.hk_handsfree = HotkeyEdit(self.app, self.cfg.hotkey_handsfree)
        self.hk_command = HotkeyEdit(self.app, self.cfg.hotkey_command)
        self.hk_fixup = HotkeyEdit(self.app, self.cfg.hotkey_fixup)
        form.addRow("Push to talk", self.hk_dictate)
        form.addRow("", _hint("Hold to record, release to transcribe and paste."))
        form.addRow("Hands-free", self.hk_handsfree)
        form.addRow("", _hint("Press once to start recording; press any Flow shortcut again to stop."))
        self.double_tap = QCheckBox("Double-tap push-to-talk to start hands-free")
        self.double_tap.setChecked(self.cfg.double_tap_handsfree)
        form.addRow("", self.double_tap)
        form.addRow("Command mode", self.hk_command)
        form.addRow("", _hint(
            "Select text, hold this shortcut and say what to do (\"make this more formal\", "
            "\"translate to Hindi\"). With nothing selected, the result is inserted at the cursor."
        ))
        form.addRow("Last dictation", self.hk_fixup)
        form.addRow("", _hint(
            "Opens the last result to review, edit, re-clean with another style, or insert again."))
        layout.addLayout(form)
        layout.addWidget(_hint("Press Esc while recording to cancel. Click a shortcut, then press the new key combination."))
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset_shortcuts)
        row = QHBoxLayout()
        row.addWidget(reset)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        return page

    def _export_settings(self) -> None:
        import json
        from dataclasses import asdict

        path, _ = QFileDialog.getSaveFileName(self, "Export settings", "flow-settings.json",
                                              "JSON (*.json)")
        if path:
            self._save()  # export what is on screen, not a stale copy
            Path(path).write_text(json.dumps(asdict(self.app.cfg), indent=2), encoding="utf-8")
            self._saved_label.setText(f"Exported to {path}")

    def _import_settings(self) -> None:
        import json
        from dataclasses import fields

        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        cfg = self.app.cfg.copy()
        known = {f.name for f in fields(cfg)}
        for key, value in data.items():
            if key in known:
                setattr(cfg, key, value)
        self.app.apply_config(cfg)
        QMessageBox.information(self, "Settings imported",
                                "Imported. Reopen this window to see every value.")
        self.close()

    def _toggle_mic_test(self, on: bool) -> None:
        """Live input level, so a dead or muted microphone is obvious before dictating."""
        if on:
            if self.app.recorder.active:
                self.mic_test.setChecked(False)
                return
            try:
                self.app.recorder.start(self.mic.currentData(), 60)
            except Exception as exc:
                self.mic_test.setChecked(False)
                self.mic_meter.setFormat(str(exc))
                return
            self._meter_timer.start(50)
            self.mic_test.setText("Stop test")
        else:
            self._meter_timer.stop()
            self.app.recorder.cancel()
            self.mic_meter.setValue(0)
            self.mic_test.setText("Test microphone")

    def _update_meter(self) -> None:
        import math

        level = self.app.recorder.level
        self.mic_meter.setValue(int(min(1.0, math.sqrt(level) * 2.6) * 100))

    def _reset_shortcuts(self) -> None:
        defaults = Config()
        self.hk_fixup.set_combo(defaults.hotkey_fixup)
        self.hk_dictate.set_combo(defaults.hotkey_dictate)
        self.hk_handsfree.set_combo(defaults.hotkey_handsfree)
        self.hk_command.set_combo(defaults.hotkey_command)
        self.double_tap.setChecked(defaults.double_tap_handsfree)

    # Models -------------------------------------------------------------------------------------
    def _models_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        whisper = QGroupBox("Speech-to-text (faster-whisper, runs locally)")
        wform = QFormLayout(whisper)
        self.whisper_model = QComboBox()
        self.whisper_model.setEditable(True)
        self.whisper_model.addItems(WHISPER_MODELS)
        _select_combo(self.whisper_model, self.cfg.whisper_model)
        wform.addRow("Model", self.whisper_model)
        wform.addRow("", _hint("auto = small on an NVIDIA GPU, base on CPU. large-v3-turbo is most accurate (GPU only, ~1.6 GB). "
                               "Models download on first use."))
        self.whisper_device = QComboBox()
        self.whisper_device.addItems(["auto", "cuda", "cpu"])
        _select_combo(self.whisper_device, self.cfg.whisper_device)
        wform.addRow("Device", self.whisper_device)
        self.compute_type = QComboBox()
        self.compute_type.addItems(["auto", "int8", "int8_float16", "float16", "float32"])
        _select_combo(self.compute_type, self.cfg.whisper_compute_type)
        wform.addRow("Precision", self.compute_type)
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.addItems(LANGUAGES)
        _select_combo(self.language, self.cfg.language)
        wform.addRow("Language", self.language)
        download_row = QHBoxLayout()
        self.download_button = QPushButton("Download / preload this model")
        self.download_button.clicked.connect(self._download_model)
        self.download_status = QLabel()
        self.download_status.setProperty("hint", True)
        download_row.addWidget(self.download_button)
        download_row.addWidget(self.download_status, 1)
        wform.addRow("", download_row)

        self.language_models = QTableWidget(0, 2)
        self.language_models.setHorizontalHeaderLabels(["Language code", "Whisper model"])
        self.language_models.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.language_models.setColumnWidth(0, 120)
        self.language_models.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.language_models.verticalHeader().setVisible(False)
        self.language_models.setMaximumHeight(120)
        for code, model in (self.cfg.language_models or {}).items():
            self._add_language_model_row(code, model)
        wform.addRow("Model per language", self.language_models)
        profile_row = QHBoxLayout()
        for text, slot in (("Add", lambda: self._add_language_model_row("", "large-v3-turbo")),
                           ("Remove selected", self._remove_language_model_rows)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            profile_row.addWidget(button)
        profile_row.addStretch()
        wform.addRow("", profile_row)
        wform.addRow("", _hint(
            "Used when you pin a language (tray menu or the Language box above), since automatic detection "
            "only knows the language after transcribing. large-v3-turbo is much better for Hindi, Telugu "
            "and Tamil than small."))

        self.romanize_languages = QLineEdit(self.cfg.romanize_languages)
        self.romanize_languages.setPlaceholderText("hi,mr   (leave empty to keep Devanagari)")
        wform.addRow("Write in Roman script", self.romanize_languages)
        wform.addRow("", _hint(
            "Converts Hindi/Marathi output to Hinglish spelling (मैं सोचता हूँ -> main sochta hoon) "
            "by rules, with no model involved."))

        self.streaming_stt = QCheckBox("Transcribe while I speak (shorter wait after long dictations)")
        self.streaming_stt.setChecked(self.cfg.streaming_stt)
        wform.addRow("", self.streaming_stt)
        wform.addRow("", _hint(
            "Pieces of speech between pauses are transcribed in the background, so releasing the "
            "shortcut only has the last few seconds left to do."))

        self.whisper_status = QLabel()
        wform.addRow("Status", self.whisper_status)
        layout.addWidget(whisper)

        ollama = QGroupBox("AI cleanup (Ollama)")
        oform = QFormLayout(ollama)
        self.cleanup_enabled = QCheckBox("Clean up dictation with AI (remove filler words, fix punctuation, apply style)")
        self.cleanup_enabled.setChecked(self.cfg.cleanup_enabled)
        oform.addRow("", self.cleanup_enabled)
        self.local_only = QCheckBox("Local only: refuse cloud models and remote Ollama servers")
        self.local_only.setChecked(self.cfg.local_only)
        oform.addRow("", self.local_only)
        oform.addRow("", _hint(
            "Some Ollama entries are a few hundred bytes: a pointer to a model that runs in the cloud. "
            "With this on, Flow refuses them and keeps using rules-only cleanup instead."))
        self.ollama_url = QLineEdit(self.cfg.ollama_url)
        oform.addRow("Server URL", self.ollama_url)
        model_row = QHBoxLayout()
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        self.ollama_model.setEditText(self.cfg.ollama_model)
        self.ollama_model.setMinimumWidth(260)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_models)
        model_row.addWidget(self.ollama_model, 1)
        model_row.addWidget(refresh)
        oform.addRow("Model", model_row)
        self.llm_timeout = QSpinBox()
        self.llm_timeout.setRange(3, 300)
        self.llm_timeout.setSuffix(" s")
        self.llm_timeout.setValue(int(self.cfg.llm_timeout))
        oform.addRow("Timeout", self.llm_timeout)
        self.spoken_punctuation = QCheckBox('Turn spoken "comma", "period" and "new paragraph" into symbols')
        self.spoken_punctuation.setChecked(self.cfg.spoken_punctuation)
        oform.addRow("", self.spoken_punctuation)
        oform.addRow("", _hint(
            "Applied by rules, with no model involved. These rules also fix capitalization, spacing and "
            "stutters on every dictation, so you still get tidy text when AI cleanup is off or rejected."))
        self.cleanup_languages = QLineEdit(self.cfg.cleanup_languages)
        self.cleanup_languages.setPlaceholderText("en,es,fr  (or: all)")
        oform.addRow("Clean up only", self.cleanup_languages)
        oform.addRow("", _hint(
            "Languages the cleanup model handles well, as Whisper codes. Anything else is inserted exactly as "
            "spoken, which is faster and avoids mistranslation. Small models translate Hindi, Tamil and similar "
            "into English, so they are not listed by default; type 'all' to always clean up."))
        self.ollama_status = QLabel()
        oform.addRow("Status", self.ollama_status)
        test_row = QHBoxLayout()
        self.test_button = QPushButton("Test cleanup")
        self.test_button.clicked.connect(self._test_cleanup)
        test_row.addWidget(self.test_button)
        test_row.addStretch()
        oform.addRow("", test_row)
        self.test_output = QPlainTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setMaximumHeight(90)
        self.test_output.setPlaceholderText("Runs a sample transcript through the selected model.")
        oform.addRow("", self.test_output)
        layout.addWidget(ollama)
        layout.addStretch()
        self._refresh_models()
        return page

    def _add_language_model_row(self, code: str, model: str) -> None:
        row = self.language_models.rowCount()
        self.language_models.insertRow(row)
        self.language_models.setItem(row, 0, QTableWidgetItem(code))
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(WHISPER_MODELS)
        _select_combo(combo, model)
        self.language_models.setCellWidget(row, 1, combo)

    def _remove_language_model_rows(self) -> None:
        for row in sorted({i.row() for i in self.language_models.selectedIndexes()}, reverse=True):
            self.language_models.removeRow(row)

    def _collect_language_models(self) -> dict:
        profiles = {}
        for row in range(self.language_models.rowCount()):
            item = self.language_models.item(row, 0)
            code = (item.text().strip().lower() if item else "")
            model = self.language_models.cellWidget(row, 1).currentText().strip()
            if code and model:
                profiles[code] = model
        return profiles

    def _download_model(self) -> None:
        name = self.whisper_model.currentText().strip()
        if not name or name == "auto":
            self.download_status.setText("Pick a specific model first (auto resolves at load time).")
            return
        if name in downloaded_models():
            self.download_status.setText(f"{name} is already downloaded.")
            return
        size = MODEL_SIZES.get(name, "unknown size")
        self.download_status.setText(f"Downloading {name} ({size})… you can keep using Flow.")
        self.download_button.setEnabled(False)
        cfg = self.app.cfg.copy()
        cfg.whisper_model = name
        self._download_started = time.monotonic()
        self._download_start_bytes = _cache_bytes()
        self._downloading = name

        def work() -> None:
            try:
                self.app.transcriber.load(cfg, name)
                self._download_done.emit(f"{name} is ready.")
            except Exception as exc:
                self._download_done.emit(f"Download failed: {exc}")

        threading.Thread(target=work, daemon=True, name="flow-model-download").start()
        self._download_timer.start(2000)

    def _poll_download(self) -> None:
        """Shows real progress by watching the model cache grow (no download hooks needed)."""
        grown = (_cache_bytes() - self._download_start_bytes) / 1e6
        elapsed = time.monotonic() - self._download_started
        self.download_status.setText(
            f"Downloading {self._downloading} ({MODEL_SIZES.get(self._downloading, '?')})… "
            f"{grown:,.0f} MB in {elapsed:.0f}s")

    def _on_download_done(self, message: str) -> None:
        self._download_timer.stop()
        self.download_button.setEnabled(True)
        self.download_status.setText(message)

    def _client(self) -> OllamaClient:
        return OllamaClient(self.ollama_url.text().strip(), self.ollama_model.currentText().strip(),
                            float(self.llm_timeout.value()))

    def _refresh_models(self) -> None:
        client = self._client()

        def work():
            try:
                self._models_loaded.emit(client.list_models(), "")
            except OllamaError as exc:
                self._models_loaded.emit([], str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_models_loaded(self, models: list, error: str) -> None:
        current = self.ollama_model.currentText()
        self.ollama_model.clear()
        self.ollama_model.addItems(models)
        self.ollama_model.setEditText(current)
        if error:
            self.ollama_status.setText(error)

    def _test_cleanup(self) -> None:
        client = self._client()
        self.test_button.setEnabled(False)
        self.test_output.setPlainText("Running…")
        sample = "um so i think we should uh we should probably ship the the new build on friday you know"

        def work():
            try:
                result = client.cleanup(sample, style_prompt("formal", self._prompts), [])
                self._test_finished.emit(f"Input:  {sample}\nOutput: {result}")
            except OllamaError as exc:
                self._test_finished.emit(f"Error: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _on_test_finished(self, text: str) -> None:
        self.test_button.setEnabled(True)
        self.test_output.setPlainText(text)

    def refresh_status(self) -> None:
        self.whisper_status.setText(self.app.whisper_status.removeprefix("Speech model: "))
        self.ollama_status.setText(self.app.ollama_status.removeprefix("Ollama: "))

    # Styles -------------------------------------------------------------------------------------
    def _styles_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_hint(
            "Flow adapts the writing style to the app you dictate into. Rules are checked top to bottom; "
            "the first match wins. 'Window title contains' is useful for web apps like Gmail or Slack in a browser."
        ))
        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("Default style"))
        self.default_style = _style_combo(self.cfg.default_style)
        default_row.addWidget(self.default_style)
        default_row.addStretch()
        layout.addLayout(default_row)

        self.rules = QTableWidget(0, 3)
        self.rules.setHorizontalHeaderLabels(["Match on", "App / title", "Style"])
        self.rules.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.rules.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rules.verticalHeader().setVisible(False)
        for rule in self.cfg.style_rules:
            self._add_rule_row(rule)
        layout.addWidget(self.rules, 1)

        row = QHBoxLayout()
        for text, slot in (("Add rule", lambda: self._add_rule_row({"kind": "process", "match": "", "style": "casual"})),
                           ("Remove selected", self._remove_rules),
                           ("Reset to defaults", self._reset_rules)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

        prompts = QGroupBox("Style instructions (sent to the model)")
        playout = QVBoxLayout(prompts)
        top = QHBoxLayout()
        self.prompt_style = QComboBox()
        for key in STYLE_KEYS:
            if key != "none":
                self.prompt_style.addItem(STYLE_LABELS[key], key)
        self.prompt_style.currentIndexChanged.connect(self._load_prompt)
        reset_prompt = QPushButton("Reset to built-in")
        reset_prompt.clicked.connect(self._reset_prompt)
        top.addWidget(self.prompt_style)
        top.addStretch()
        top.addWidget(reset_prompt)
        playout.addLayout(top)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMaximumHeight(90)
        self.prompt_edit.textChanged.connect(self._store_prompt)
        playout.addWidget(self.prompt_edit)
        layout.addWidget(prompts)
        self._prompt_key = None
        self._load_prompt()
        return page

    def _add_rule_row(self, rule: dict) -> None:
        row = self.rules.rowCount()
        self.rules.insertRow(row)
        kind = QComboBox()
        kind.addItem("App (exe name)", "process")
        kind.addItem("Window title contains", "title")
        _select_combo(kind, rule.get("kind", "process"), data=True)
        self.rules.setCellWidget(row, 0, kind)
        self.rules.setItem(row, 1, QTableWidgetItem(rule.get("match", "")))
        self.rules.setCellWidget(row, 2, _style_combo(rule.get("style", "casual")))

    def _remove_rules(self) -> None:
        for row in sorted({index.row() for index in self.rules.selectedIndexes()}, reverse=True):
            self.rules.removeRow(row)

    def _reset_rules(self) -> None:
        self.rules.setRowCount(0)
        for rule in default_rules():
            self._add_rule_row(rule)

    def _collect_rules(self) -> list[dict]:
        rules = []
        for row in range(self.rules.rowCount()):
            item = self.rules.item(row, 1)
            match = item.text().strip() if item else ""
            if match:
                rules.append({
                    "kind": self.rules.cellWidget(row, 0).currentData(),
                    "match": match,
                    "style": self.rules.cellWidget(row, 2).currentData(),
                })
        return rules

    def _load_prompt(self) -> None:
        self._prompt_key = None
        key = self.prompt_style.currentData()
        self.prompt_edit.setPlainText(style_prompt(key, self._prompts))
        self._prompt_key = key

    def _store_prompt(self) -> None:
        key = self._prompt_key
        if key is None:
            return
        text = self.prompt_edit.toPlainText().strip()
        if text and text != BUILTIN_STYLES.get(key, ""):
            self._prompts[key] = text
        else:
            self._prompts.pop(key, None)

    def _reset_prompt(self) -> None:
        key = self.prompt_style.currentData()
        self._prompts.pop(key, None)
        self._load_prompt()

    # Dictionary ---------------------------------------------------------------------------------
    def _dictionary_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        dictionary = self.app.dictionary

        vocab_box = QGroupBox("Vocabulary")
        vlayout = QVBoxLayout(vocab_box)
        vlayout.addWidget(_hint("Names, jargon and acronyms Flow should recognize and spell exactly (e.g. Kubernetes, Abhishek, GPT-5)."))
        self.vocab_list = QListWidget()
        self.vocab_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        vlayout.addWidget(self.vocab_list, 1)
        add_row = QHBoxLayout()
        self.vocab_input = QLineEdit()
        self.vocab_input.setPlaceholderText("Add a word or phrase")
        add = QPushButton("Add")
        remove = QPushButton("Remove")
        add_row.addWidget(self.vocab_input, 1)
        add_row.addWidget(add)
        add_row.addWidget(remove)
        vlayout.addLayout(add_row)

        def refresh_vocab():
            self.vocab_list.clear()
            self.vocab_list.addItems(dictionary.vocabulary())

        def add_word():
            dictionary.add_word(self.vocab_input.text())
            self.vocab_input.clear()
            refresh_vocab()

        def remove_words():
            for item in self.vocab_list.selectedItems():
                dictionary.remove_word(item.text())
            refresh_vocab()

        import_row = QHBoxLayout()
        import_button = QPushButton("Import from a project folder…")
        self.vocab_status = QLabel()
        self.vocab_status.setProperty("hint", True)
        import_row.addWidget(import_button)
        import_row.addWidget(self.vocab_status, 1)
        vlayout.addLayout(import_row)

        def import_project():
            folder = QFileDialog.getExistingDirectory(self, "Pick a code folder")
            if not folder:
                return
            self.vocab_status.setText("Scanning…")
            import_button.setEnabled(False)

            def work():
                from ..codewords import harvest_vocabulary

                try:
                    words = harvest_vocabulary(folder)
                    for word in words:
                        dictionary.add_word(word)
                    self._vocab_imported.emit(f"Added {len(words)} names from {folder}.")
                except Exception as exc:
                    self._vocab_imported.emit(f"Import failed: {exc}")

            threading.Thread(target=work, daemon=True, name="flow-vocab-import").start()

        def imported(message):
            import_button.setEnabled(True)
            self.vocab_status.setText(message)
            refresh_vocab()

        import_button.clicked.connect(import_project)
        self._vocab_imported.connect(imported)

        add.clicked.connect(add_word)
        self.vocab_input.returnPressed.connect(add_word)
        remove.clicked.connect(remove_words)
        refresh_vocab()

        repl_box = QGroupBox("Replacements")
        rlayout = QVBoxLayout(repl_box)
        rlayout.addWidget(_hint("Always replace what Whisper hears with what you want (e.g. \"wisper flow\" → \"Wispr Flow\")."))
        self.repl_table = QTableWidget(0, 2)
        self.repl_table.setHorizontalHeaderLabels(["When I say", "Write"])
        self.repl_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.repl_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.repl_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.repl_table.verticalHeader().setVisible(False)
        rlayout.addWidget(self.repl_table, 1)
        form_row = QHBoxLayout()
        self.repl_from = QLineEdit()
        self.repl_from.setPlaceholderText("When I say…")
        self.repl_to = QLineEdit()
        self.repl_to.setPlaceholderText("Write…")
        add_repl = QPushButton("Add")
        remove_repl = QPushButton("Remove")
        form_row.addWidget(self.repl_from)
        form_row.addWidget(self.repl_to)
        form_row.addWidget(add_repl)
        form_row.addWidget(remove_repl)
        rlayout.addLayout(form_row)

        def refresh_repl():
            rules = dictionary.replacements()
            self.repl_table.setRowCount(len(rules))
            for row, rule in enumerate(rules):
                first = QTableWidgetItem(rule.pattern)
                first.setData(Qt.UserRole, rule.id)
                self.repl_table.setItem(row, 0, first)
                self.repl_table.setItem(row, 1, QTableWidgetItem(rule.replacement))

        def add_rule():
            dictionary.add_replacement(self.repl_from.text(), self.repl_to.text())
            self.repl_from.clear()
            self.repl_to.clear()
            refresh_repl()

        def remove_rule():
            for row in {index.row() for index in self.repl_table.selectedIndexes()}:
                dictionary.remove_replacement(self.repl_table.item(row, 0).data(Qt.UserRole))
            refresh_repl()

        add_repl.clicked.connect(add_rule)
        self.repl_to.returnPressed.connect(add_rule)
        remove_repl.clicked.connect(remove_rule)
        refresh_repl()

        layout.addWidget(vocab_box, 1)
        layout.addWidget(repl_box, 1)
        return page

    # Snippets -----------------------------------------------------------------------------------
    def _snippets_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        dictionary = self.app.dictionary
        layout.addWidget(_hint(
            "Say a trigger phrase and Flow inserts the saved text. Say it on its own (or \"insert my calendar link\") "
            "to insert just the snippet, or mention it inside a longer dictation."
        ))
        self.snip_table = QTableWidget(0, 2)
        self.snip_table.setHorizontalHeaderLabels(["Trigger phrase", "Expands to"])
        self.snip_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.snip_table.setColumnWidth(0, 220)
        self.snip_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.snip_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.snip_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.snip_table.verticalHeader().setVisible(False)
        layout.addWidget(self.snip_table, 1)

        self.snip_trigger = QLineEdit()
        self.snip_trigger.setPlaceholderText("Trigger phrase, e.g. my calendar link")
        self.snip_expansion = QPlainTextEdit()
        self.snip_expansion.setPlaceholderText("Text to insert")
        self.snip_expansion.setMaximumHeight(110)
        layout.addWidget(self.snip_trigger)
        layout.addWidget(self.snip_expansion)
        row = QHBoxLayout()
        save = QPushButton("Save snippet")
        remove = QPushButton("Remove selected")
        new = QPushButton("New")
        row.addWidget(save)
        row.addWidget(new)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)

        def refresh():
            snippets = dictionary.snippets()
            self.snip_table.setRowCount(len(snippets))
            for i, snippet in enumerate(snippets):
                trigger = QTableWidgetItem(snippet.trigger)
                trigger.setData(Qt.UserRole, snippet.id)
                trigger.setData(Qt.UserRole + 1, snippet.expansion)
                self.snip_table.setItem(i, 0, trigger)
                self.snip_table.setItem(i, 1, QTableWidgetItem(snippet.expansion.replace("\n", " ⏎ ")))

        def on_select():
            items = self.snip_table.selectedItems()
            if items:
                first = self.snip_table.item(items[0].row(), 0)
                self.snip_trigger.setText(first.text())
                self.snip_expansion.setPlainText(first.data(Qt.UserRole + 1))

        def save_snippet():
            trigger = self.snip_trigger.text().strip()
            expansion = self.snip_expansion.toPlainText()
            if not trigger or not expansion.strip():
                return
            dictionary.set_snippet(trigger, expansion)
            refresh()

        def clear_editor():
            self.snip_table.clearSelection()
            self.snip_trigger.clear()
            self.snip_expansion.clear()
            self.snip_trigger.setFocus()

        def remove_snippet():
            items = self.snip_table.selectedItems()
            if items:
                dictionary.remove_snippet(self.snip_table.item(items[0].row(), 0).data(Qt.UserRole))
                clear_editor()
                refresh()

        self.snip_table.itemSelectionChanged.connect(on_select)
        save.clicked.connect(save_snippet)
        new.clicked.connect(clear_editor)
        remove.clicked.connect(remove_snippet)
        refresh()
        return page

    # Skills -------------------------------------------------------------------------------------
    def _skills_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        skills = self.app.skills
        layout.addWidget(_hint(
            'Say a skill name, then what you want: "commit message: fixed the login redirect bug". '
            "The instruction below reshapes that dictation. Skills use the AI model, so they need Ollama."))
        self.skill_table = QTableWidget(0, 2)
        self.skill_table.setHorizontalHeaderLabels(["Say this", "Instruction"])
        self.skill_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.skill_table.setColumnWidth(0, 180)
        self.skill_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.skill_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.skill_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.skill_table.verticalHeader().setVisible(False)
        layout.addWidget(self.skill_table, 1)

        self.skill_name = QLineEdit()
        self.skill_name.setPlaceholderText("Skill name, e.g. commit message")
        self.skill_instruction = QPlainTextEdit()
        self.skill_instruction.setPlaceholderText("What should Flow do with the dictation?")
        self.skill_instruction.setMaximumHeight(110)
        layout.addWidget(self.skill_name)
        layout.addWidget(self.skill_instruction)

        row = QHBoxLayout()
        save = QPushButton("Save skill")
        new = QPushButton("New")
        remove = QPushButton("Remove selected")
        for button in (save, new, remove):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

        def refresh():
            items = skills.all()
            self.skill_table.setRowCount(len(items))
            for i, skill in enumerate(items):
                name = QTableWidgetItem(skill.name)
                name.setData(Qt.UserRole, skill.id)
                name.setData(Qt.UserRole + 1, skill.instruction)
                self.skill_table.setItem(i, 0, name)
                self.skill_table.setItem(i, 1, QTableWidgetItem(skill.instruction.replace("\n", " ")))

        def on_select():
            items = self.skill_table.selectedItems()
            if items:
                first = self.skill_table.item(items[0].row(), 0)
                self.skill_name.setText(first.text())
                self.skill_instruction.setPlainText(first.data(Qt.UserRole + 1))

        def save_skill():
            skills.save(self.skill_name.text(), self.skill_instruction.toPlainText())
            refresh()

        def clear_editor():
            self.skill_table.clearSelection()
            self.skill_name.clear()
            self.skill_instruction.clear()
            self.skill_name.setFocus()

        def remove_skill():
            items = self.skill_table.selectedItems()
            if items:
                skills.remove(self.skill_table.item(items[0].row(), 0).data(Qt.UserRole))
                clear_editor()
                refresh()

        self.skill_table.itemSelectionChanged.connect(on_select)
        save.clicked.connect(save_skill)
        new.clicked.connect(clear_editor)
        remove.clicked.connect(remove_skill)
        refresh()
        return page

    # Stats --------------------------------------------------------------------------------------
    def _stats_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.stats_totals = QLabel()
        self.stats_totals.setTextFormat(Qt.RichText)
        layout.addWidget(self.stats_totals)
        self.stats_tables = QHBoxLayout()
        layout.addLayout(self.stats_tables, 1)
        self.stats_breakdowns: dict[str, QTableWidget] = {}
        for column, heading in (("app", "App"), ("style", "Style"), ("mode", "Mode")):
            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels([heading, "Dictations", "Words"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.verticalHeader().setVisible(False)
            self.stats_breakdowns[column] = table
            self.stats_tables.addWidget(table)
        self.stats_days = QTableWidget(0, 2)
        self.stats_days.setHorizontalHeaderLabels(["Day", "Dictations"])
        self.stats_days.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.stats_days.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stats_days.verticalHeader().setVisible(False)
        self.stats_days.setMaximumHeight(170)
        layout.addWidget(self.stats_days)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_stats)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _refresh_stats(self) -> None:
        history = self.app.history
        s = history.summary()
        minutes = s["seconds"] / 60
        self.stats_totals.setText(
            f"<b>{s['dictations']:,}</b> dictations · <b>{s['words']:,}</b> words · "
            f"<b>{minutes:,.0f}</b> minutes spoken · <b>{s['wpm']:.0f}</b> words per minute<br>"
            f"average speech recognition <b>{s['avg_stt_ms']:,.0f} ms</b> · "
            f"average AI cleanup <b>{s['avg_llm_ms']:,.0f} ms</b>")
        for column, table in self.stats_breakdowns.items():
            rows = history.by_column(column)
            table.setRowCount(len(rows))
            for i, (key, count, words) in enumerate(rows):
                table.setItem(i, 0, QTableWidgetItem(str(key)))
                table.setItem(i, 1, QTableWidgetItem(f"{count:,}"))
                table.setItem(i, 2, QTableWidgetItem(f"{words:,}"))
        days = history.per_day()
        self.stats_days.setRowCount(len(days))
        for i, (day, count) in enumerate(days):
            self.stats_days.setItem(i, 0, QTableWidgetItem(day))
            self.stats_days.setItem(i, 1, QTableWidgetItem("█" * min(40, count) + f" {count}"))

    # History ------------------------------------------------------------------------------------
    def _history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.stats_label = QLabel()
        layout.addWidget(self.stats_label)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search history")
        self.history_search.textChanged.connect(self._refresh_history)
        layout.addWidget(self.history_search)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["When", "App", "Style", "Text"])
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.history_table.setColumnWidth(0, 130)
        self.history_table.setColumnWidth(1, 130)
        self.history_table.setColumnWidth(2, 80)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setWordWrap(True)
        self.history_table.itemDoubleClicked.connect(lambda _item: self._copy_history(raw=False))
        layout.addWidget(self.history_table, 1)

        row = QHBoxLayout()
        for text, slot in (("Copy", lambda: self._copy_history(raw=False)),
                           ("Copy original transcript", lambda: self._copy_history(raw=True)),
                           ("Delete", self._delete_history),
                           ("Clear all", self._clear_history)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _refresh_history(self) -> None:
        entries = self.app.history.search(self.history_search.text())
        self._history_entries = entries
        self.history_table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            when = datetime.fromtimestamp(entry.created_at).strftime("%d %b %H:%M")
            values = [when, entry.app or "", entry.style or "", entry.final]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 3:
                    item.setToolTip(f"Original: {entry.raw}\nSpeech {entry.stt_ms} ms · AI {entry.llm_ms} ms")
                self.history_table.setItem(i, col, item)
        words, wpm = self.app.history.stats()
        self.stats_label.setText(f"<b>{words:,}</b> words dictated · <b>{wpm:.0f}</b> words per minute on average")

    def _selected_entries(self):
        rows = sorted({index.row() for index in self.history_table.selectedIndexes()})
        entries = getattr(self, "_history_entries", [])
        return [entries[row] for row in rows if row < len(entries)]

    def _copy_history(self, raw: bool) -> None:
        entries = self._selected_entries()
        if entries:
            QGuiApplication.clipboard().setText("\n".join(e.raw if raw else e.final for e in entries))

    def _delete_history(self) -> None:
        for entry in self._selected_entries():
            self.app.history.delete(entry.id)
        self._refresh_history()

    def _clear_history(self) -> None:
        if QMessageBox.question(self, "Clear history", "Delete all dictation history?") == QMessageBox.Yes:
            self.app.history.clear()
            self._refresh_history()

    # Save / lifecycle ---------------------------------------------------------------------------
    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.tabText(index) == "History":
            self._refresh_history()
        elif self.tabs.tabText(index) == "Stats":
            self._refresh_stats()

    def _save(self) -> None:
        cfg = self.app.cfg.copy()
        cfg.input_device = self.mic.currentData()
        cfg.paste_mode = self.paste_mode.currentData()
        cfg.trailing_space = self.trailing_space.isChecked()
        cfg.sounds = self.sounds.isChecked()
        cfg.max_recording_seconds = self.max_seconds.value()
        cfg.auto_stop_silence = float(self.auto_stop_silence.value())
        cfg.command_mode_output = self.command_mode_output.currentData()
        cfg.history_enabled = self.history_enabled.isChecked()
        cfg.history_retention_days = self.retention.value()
        cfg.launch_at_login = self.launch_at_login.isChecked()
        cfg.debug_latency = self.debug_latency.isChecked()

        cfg.hotkey_dictate = self.hk_dictate.combo
        cfg.hotkey_handsfree = self.hk_handsfree.combo
        cfg.hotkey_command = self.hk_command.combo
        cfg.hotkey_fixup = self.hk_fixup.combo
        cfg.double_tap_handsfree = self.double_tap.isChecked()

        cfg.whisper_model = self.whisper_model.currentText().strip() or "auto"
        cfg.whisper_device = self.whisper_device.currentText()
        cfg.whisper_compute_type = self.compute_type.currentText()
        cfg.language = self.language.currentText().strip() or "auto"
        cfg.streaming_stt = self.streaming_stt.isChecked()
        cfg.language_models = self._collect_language_models()
        cfg.romanize_languages = self.romanize_languages.text().strip()
        cfg.cleanup_enabled = self.cleanup_enabled.isChecked()
        cfg.cleanup_languages = self.cleanup_languages.text().strip() or "all"
        cfg.local_only = self.local_only.isChecked()
        cfg.spoken_punctuation = self.spoken_punctuation.isChecked()
        cfg.ollama_url = self.ollama_url.text().strip() or "http://localhost:11434"
        cfg.ollama_model = self.ollama_model.currentText().strip() or "qwen2.5:1.5b"
        cfg.llm_timeout = float(self.llm_timeout.value())

        cfg.default_style = self.default_style.currentData()
        cfg.style_rules = self._collect_rules()
        cfg.style_prompts = dict(self._prompts)

        self.app.apply_config(cfg)
        self._saved_label.setText("Saved.")

    def closeEvent(self, event) -> None:
        if self.mic_test.isChecked():
            self.mic_test.setChecked(False)
        self.app.cancel_combo_capture()
        self._saved_label.setText("")
        super().closeEvent(event)
