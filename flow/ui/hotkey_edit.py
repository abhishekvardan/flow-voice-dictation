"""A button that records a global key combination when clicked."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from ..hotkeys import pretty_combo


class HotkeyEdit(QPushButton):
    def __init__(self, app, combo: str):
        super().__init__()
        self._app = app
        self.combo = combo
        self._capturing = False
        self.setMinimumWidth(240)
        self.setCheckable(True)
        self.clicked.connect(self._begin)
        self._render()

    def _render(self) -> None:
        self.setChecked(False)
        self.setText(pretty_combo(self.combo) or "Not set")

    def set_combo(self, combo: str) -> None:
        self.combo = combo
        self._render()

    def _begin(self) -> None:
        if self._capturing:
            self.setChecked(True)
            return
        self._capturing = True
        self.setChecked(True)
        self.setText("Press your shortcut…  (Esc cancels)")
        self._app.begin_combo_capture(self._done)

    def _done(self, combo: str) -> None:
        self._capturing = False
        if combo:
            self.combo = combo
        self._render()
