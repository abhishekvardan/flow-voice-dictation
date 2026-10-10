"""The Flow window: a home page with live status, plus every settings page in one place."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..hotkeys import pretty_combo
from .icons import mic_icon
from .settings import LANGUAGES, SettingsWindow
from .theme import STYLESHEET


def _card(title: str, body: str = "") -> tuple[QWidget, QLabel]:
    box = QWidget()
    box.setProperty("card", True)
    layout = QVBoxLayout(box)
    layout.setSpacing(4)
    heading = QLabel(title)
    heading.setProperty("hint", True)
    value = QLabel(body)
    value.setWordWrap(True)
    value.setTextFormat(Qt.RichText)
    layout.addWidget(heading)
    layout.addWidget(value)
    return box, value


class MainWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Flow")
        self.setWindowIcon(mic_icon())
        self.resize(980, 660)
        self.setStyleSheet(STYLESHEET)

        # The settings pages are built once and moved in here, so there is only one copy of them.
        self.settings = SettingsWindow(app, embedded=True)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(170)
        self.stack = QStackedWidget()

        self._add_page("Home", self._home_page())
        tabs = self.settings.tabs
        while tabs.count():
            name, page = tabs.tabText(0), tabs.widget(0)
            tabs.removeTab(0)
            self._add_page(name, page)
        self.nav.currentRowChanged.connect(self._on_page_changed)
        self.nav.setCurrentRow(0)

        self.saved_label = QLabel("")
        self.saved_label.setProperty("hint", True)
        save = QPushButton("Save settings")
        save.setProperty("primary", True)
        save.clicked.connect(self._save)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer = QHBoxLayout()
        footer.addWidget(self.saved_label, 1)
        footer.addWidget(save)
        footer.addWidget(close)

        right = QVBoxLayout()
        right.setContentsMargins(18, 16, 18, 14)
        right.addWidget(self.stack, 1)
        right.addLayout(footer)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.nav)
        container = QWidget()
        container.setLayout(right)
        root.addWidget(container, 1)

    def _add_page(self, name: str, page: QWidget) -> None:
        self.nav.addItem(name)
        self.stack.addWidget(page)

    def _on_page_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(max(0, row))
        name = self.nav.item(row).text() if self.nav.item(row) else ""
        if name == "History":
            self.settings._refresh_history()
        elif name == "Stats":
            self.settings._refresh_stats()
        elif name == "Home":
            self.refresh()

    # Home -----------------------------------------------------------------------------------
    def _home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)

        title = QLabel("Flow")
        title.setProperty("heading", True)
        subtitle = QLabel("Hold the shortcut, speak, let go. Everything runs on this machine.")
        subtitle.setProperty("hint", True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        cards = QGridLayout()
        cards.setSpacing(12)
        self.card_speech, self.card_speech_value = _card("Speech model")
        self.card_ai, self.card_ai_value = _card("AI cleanup")
        self.card_shortcuts, self.card_shortcuts_value = _card("Shortcuts")
        self.card_today, self.card_today_value = _card("Your dictation")
        cards.addWidget(self.card_speech, 0, 0)
        cards.addWidget(self.card_ai, 0, 1)
        cards.addWidget(self.card_shortcuts, 1, 0)
        cards.addWidget(self.card_today, 1, 1)
        layout.addLayout(cards)

        controls = QHBoxLayout()
        self.cleanup_toggle = QCheckBox("AI cleanup")
        self.cleanup_toggle.setChecked(self.app.cfg.cleanup_enabled)
        self.cleanup_toggle.toggled.connect(self.app.set_cleanup_enabled)
        self.pause_toggle = QCheckBox("Pause Flow")
        self.pause_toggle.setChecked(self.app.paused)
        self.pause_toggle.toggled.connect(self.app.set_paused)
        self.language_box = QComboBox()
        self.language_box.addItem("Detect automatically", "auto")
        for code in LANGUAGES:
            if code != "auto":
                self.language_box.addItem(code, code)
        index = self.language_box.findData(self.app.cfg.language)
        self.language_box.setCurrentIndex(max(0, index))
        self.language_box.currentIndexChanged.connect(
            lambda: self.app.set_language(self.language_box.currentData()))
        controls.addWidget(self.cleanup_toggle)
        controls.addWidget(self.pause_toggle)
        controls.addWidget(QLabel("Language"))
        controls.addWidget(self.language_box)
        controls.addStretch()
        layout.addLayout(controls)

        recent_label = QLabel("Recent dictations")
        recent_label.setProperty("hint", True)
        layout.addWidget(recent_label)
        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(
            lambda item: QGuiApplication.clipboard().setText(item.data(Qt.UserRole)))
        layout.addWidget(self.recent, 1)
        hint = QLabel("Double-click an entry to copy it.")
        hint.setProperty("hint", True)
        layout.addWidget(hint)
        return page

    def refresh(self) -> None:
        cfg = self.app.cfg
        self.card_speech_value.setText(
            f"<b>{self.app.whisper_status.removeprefix('Speech model: ')}</b><br>"
            f"{'transcribes while you speak' if cfg.streaming_stt else 'transcribes after you finish'}")
        blocked = f"<br>blocked: {self.app.llm_blocked}" if self.app.llm_blocked else ""
        self.card_ai_value.setText(
            f"<b>{self.app.ollama_status.removeprefix('Ollama: ')}</b><br>"
            f"{'on' if cfg.cleanup_enabled else 'off'} · cleans {cfg.cleanup_languages}{blocked}")
        self.card_shortcuts_value.setText(
            f"<b>{pretty_combo(cfg.hotkey_dictate)}</b> hold to dictate<br>"
            f"<b>{pretty_combo(cfg.hotkey_command)}</b> rewrite selection · "
            f"<b>{pretty_combo(cfg.hotkey_fixup)}</b> last dictation")
        summary = self.app.history.summary()
        self.card_today_value.setText(
            f"<b>{summary['words']:,}</b> words in <b>{summary['dictations']:,}</b> dictations<br>"
            f"{summary['wpm']:.0f} words per minute · "
            f"speech {summary['avg_stt_ms']:,.0f} ms · AI {summary['avg_llm_ms']:,.0f} ms")

        self.recent.clear()
        for entry in self.app.history.recent(12):
            when = datetime.fromtimestamp(entry.created_at).strftime("%d %b %H:%M")
            text = entry.final.replace("\n", " ")
            item_text = f"{when}  ·  {entry.app or '?'}  ·  {text[:90]}"
            self.recent.addItem(item_text)
            self.recent.item(self.recent.count() - 1).setData(Qt.UserRole, entry.final)
        if self.cleanup_toggle.isChecked() != cfg.cleanup_enabled:
            self.cleanup_toggle.setChecked(cfg.cleanup_enabled)
        if self.pause_toggle.isChecked() != self.app.paused:
            self.pause_toggle.setChecked(self.app.paused)

    def show_page(self, name: str) -> None:
        for row in range(self.nav.count()):
            if self.nav.item(row).text().lower() == name.lower():
                self.nav.setCurrentRow(row)
                return

    def refresh_status(self) -> None:
        """Called by the app when model status changes."""
        self.settings.refresh_status()
        if self.nav.currentRow() == 0:
            self.refresh()

    def _save(self) -> None:
        self.settings._save()
        self.saved_label.setText("Saved.")
        self.refresh()

    def closeEvent(self, event) -> None:
        self.app.cancel_combo_capture()
        if self.settings.mic_test.isChecked():
            self.settings.mic_test.setChecked(False)
        self.saved_label.setText("")
        super().closeEvent(event)
