"""The 'last dictation' panel: review, edit, re-clean or re-insert what Flow produced."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..llm import OllamaError
from ..styles import STYLE_LABELS, style_prompt
from .icons import mic_icon

STYLESHEET = """
QWidget { font-size: 10pt; }
QLabel[hint="true"] { color: palette(placeholder-text); font-size: 9pt; }
QPlainTextEdit { font-size: 11pt; padding: 6px; }
QPushButton { padding: 5px 12px; }
"""


class FixupPanel(QWidget):
    """Opened with the fix-up shortcut (default Ctrl+Win+E) after a dictation."""

    _recleaned = Signal(str, str)  # text, error

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Last dictation")
        self.setWindowIcon(mic_icon())
        self.resize(640, 320)
        self.setStyleSheet(STYLESHEET)
        self._recleaned.connect(self._on_recleaned)

        self.info = QLabel()
        self.info.setProperty("hint", True)
        self.editor = QPlainTextEdit()
        self.status = QLabel()
        self.status.setProperty("hint", True)

        self.style_choice = QComboBox()
        for key, label in STYLE_LABELS.items():
            if key != "none":
                self.style_choice.addItem(label, key)
        self.reclean_button = QPushButton("Clean again")
        self.reclean_button.clicked.connect(self._reclean)

        sources = QHBoxLayout()
        for text, getter in (("Exactly as spoken", lambda: self.app.last.get("raw", "")),
                             ("Rules only", lambda: self.app.last.get("tidied", "")),
                             ("AI version", lambda: self.app.last.get("final", ""))):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, g=getter: self._show_version(g()))
            sources.addWidget(button)
        sources.addStretch()
        sources.addWidget(QLabel("Style"))
        sources.addWidget(self.style_choice)
        sources.addWidget(self.reclean_button)

        actions = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        insert = QPushButton("Insert where I was typing")
        insert.setDefault(True)
        insert.clicked.connect(self._insert)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions.addWidget(self.status, 1)
        actions.addWidget(copy)
        actions.addWidget(insert)
        actions.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addWidget(self.editor, 1)
        layout.addLayout(sources)
        layout.addLayout(actions)

    # ------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        last = self.app.last
        if not last:
            self.info.setText("No dictation yet. Hold the dictate shortcut and speak first.")
            self.editor.setPlainText("")
            return
        bits = [f"into {last.get('app') or 'unknown app'}", f"style {last.get('style', '?')}"]
        if last.get("language"):
            bits.append(f"language {last['language']}")
        if last.get("llm_rejected"):
            bits.append("AI cleanup was rejected, so the rules version was inserted")
        if last.get("timing"):
            bits.append(last["timing"])
        self.info.setText(" · ".join(bits))
        self.editor.setPlainText(last.get("final", ""))
        self.status.setText("")
        index = self.style_choice.findData(str(last.get("style", "")).split(" ")[0])
        if index >= 0:
            self.style_choice.setCurrentIndex(index)

    def _show_version(self, text: str) -> None:
        self.editor.setPlainText(text)
        self.status.setText("")

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.editor.toPlainText())
        self.status.setText("Copied.")

    def _insert(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            return
        self.hide()
        self.app.insert_into_previous_window(text, self.app.last.get("hwnd", 0))

    def _reclean(self) -> None:
        raw = self.app.last.get("raw", "")
        if not raw:
            return
        style = self.style_choice.currentData()
        self.reclean_button.setEnabled(False)
        self.status.setText("Cleaning…")
        cfg, llm = self.app.cfg, self.app.llm
        tidied = self.app.last.get("tidied", raw)
        language = self.app.last.get("language", "")

        def work() -> None:
            try:
                text = llm.cleanup(raw, style_prompt(style, cfg.style_prompts),
                                   self.app.dictionary.vocabulary(), language=language, fallback=tidied)
                self._recleaned.emit(text, "")
            except OllamaError as exc:
                self._recleaned.emit("", str(exc))

        threading.Thread(target=work, daemon=True, name="flow-reclean").start()

    def _on_recleaned(self, text: str, error: str) -> None:
        self.reclean_button.setEnabled(True)
        if error:
            self.status.setText(error)
            return
        rejected = text == self.app.last.get("tidied", "")
        self.editor.setPlainText(text)
        self.status.setText("AI cleanup rejected again - showing the rules version."
                            if rejected else "Cleaned.")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
