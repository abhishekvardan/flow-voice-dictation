"""First-run welcome: what the shortcuts are and what still needs setting up."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..hotkeys import pretty_combo
from ..llm import OllamaError
from .icons import mic_icon


class WelcomeDialog(QDialog):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Welcome to Flow")
        self.setWindowIcon(mic_icon())
        self.setMinimumWidth(560)
        cfg = app.cfg

        title = QLabel("<h2>Flow is running in your system tray</h2>")
        shortcuts = QLabel(
            f"<table cellpadding=4>"
            f"<tr><td><b>{pretty_combo(cfg.hotkey_dictate)}</b></td>"
            f"<td>hold, speak, release - the text is pasted where you were typing</td></tr>"
            f"<tr><td><b>double-tap {pretty_combo(cfg.hotkey_dictate)}</b></td>"
            f"<td>hands-free: press again to stop</td></tr>"
            f"<tr><td><b>{pretty_combo(cfg.hotkey_command)}</b></td>"
            f"<td>select text, hold and say what to change</td></tr>"
            f"<tr><td><b>{pretty_combo(cfg.hotkey_fixup)}</b></td>"
            f"<td>review, edit or re-run the last dictation</td></tr>"
            f"<tr><td><b>Esc</b></td><td>cancel while recording</td></tr></table>"
        )
        shortcuts.setTextFormat(Qt.RichText)
        self.checks = QLabel("Checking your setup…")
        self.checks.setWordWrap(True)

        self.dont_show = QCheckBox("Don't show this again")
        self.dont_show.setChecked(True)

        settings = QPushButton("Open settings")
        settings.clicked.connect(self._open_settings)
        close = QPushButton("Start dictating")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.dont_show)
        buttons.addStretch()
        buttons.addWidget(settings)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(shortcuts)
        layout.addWidget(self.checks)
        layout.addLayout(buttons)
        self.refresh_checks()

    def refresh_checks(self) -> None:
        from ..audio import input_devices

        lines = []
        devices = input_devices()
        lines.append(f"{'OK' if devices else 'PROBLEM'} · microphone: "
                     + (devices[0] if devices else "no input device found"))
        lines.append(f"· speech model: {self.app.whisper_status.removeprefix('Speech model: ')}")
        try:
            models = self.app.llm.list_models()
            wanted = self.app.cfg.ollama_model
            ok = wanted in models or f"{wanted}:latest" in models
            lines.append(f"{'OK' if ok else 'PROBLEM'} · AI cleanup: "
                         + (f"{wanted}" if ok else f"run 'ollama pull {wanted}'"))
        except OllamaError as exc:
            lines.append(f"PROBLEM · AI cleanup: {exc} (dictation still works, with rules-only cleanup)")
        self.checks.setText("<br>".join(lines))

    def _open_settings(self) -> None:
        self.accept()
        self.app.open_settings()

    def accept(self) -> None:
        if self.dont_show.isChecked():
            cfg = self.app.cfg.copy()
            cfg.welcome_shown = True
            self.app.apply_config(cfg)
        super().accept()
