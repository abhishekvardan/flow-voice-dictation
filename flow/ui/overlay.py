"""The floating pill at the bottom of the screen: live waveform, processing dots, messages."""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

BARS = 18
BG = QColor(17, 17, 20, 240)
BORDER = QColor(255, 255, 255, 38)
DICTATE_COLOR = QColor(245, 245, 247)
COMMAND_COLOR = QColor(167, 139, 250)
ERROR_COLOR = QColor(248, 113, 113)
STOP_COLOR = QColor(239, 68, 68)


class Overlay(QWidget):
    stop_clicked = Signal()
    cancel_clicked = Signal()

    def __init__(self, level_fn: Callable[[], float]):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._level_fn = level_fn
        self._state = "hidden"  # hidden | recording | processing | message
        self._mode = "dictate"
        self._handsfree = False
        self._message = ""
        self._error = False
        self._levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self._smoothed = 0.0
        self._phase = 0.0
        self._anim = QTimer(self)
        self._anim.setInterval(33)
        self._anim.timeout.connect(self._tick)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_overlay)

    # Public API -----------------------------------------------------------------------------
    def show_recording(self, mode: str, handsfree: bool) -> None:
        self._levels = deque([0.0] * BARS, maxlen=BARS)
        self._mode, self._handsfree = mode, handsfree
        self._enter("recording")

    def set_mode(self, mode: str, handsfree: bool) -> None:
        self._mode, self._handsfree = mode, handsfree
        if self._state == "recording":
            self._place()
            self.update()

    def show_processing(self) -> None:
        self._enter("processing")

    def show_message(self, text: str, error: bool = True, ms: int = 2600) -> None:
        self._message, self._error = text, error
        self._enter("message")
        self._hide_timer.start(ms)

    def hide_overlay(self) -> None:
        self._state = "hidden"
        self._anim.stop()
        self._hide_timer.stop()
        self.hide()

    @property
    def state(self) -> str:
        return self._state

    # Internals ------------------------------------------------------------------------------
    def _enter(self, state: str) -> None:
        self._state = state
        if state != "message":
            self._hide_timer.stop()
        self._place()
        if not self._anim.isActive():
            self._anim.start()
        self.show()
        self.raise_()
        self.update()

    def _size(self) -> tuple[int, int]:
        if self._state == "recording":
            return (230 if self._handsfree else 150), 40
        if self._state == "processing":
            return 96, 40
        metrics = self.fontMetrics()
        return min(560, metrics.horizontalAdvance(self._message) + 44), 40

    def _place(self) -> None:
        w, h = self._size()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.setGeometry(geo.center().x() - w // 2, geo.bottom() - h - 56, w, h)

    def _tick(self) -> None:
        self._phase += 0.033
        if self._state == "recording":
            raw = max(0.0, self._level_fn())
            target = min(1.0, math.sqrt(raw) * 2.6)
            self._smoothed = self._smoothed * 0.5 + target * 0.5
            self._levels.append(self._smoothed)
        self.update()

    def paintEvent(self, _event) -> None:
        if self._state == "hidden":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.fillPath(path, BG)
        p.setPen(QPen(BORDER, 1))
        p.drawPath(path)

        if self._state == "recording":
            self._paint_recording(p, rect)
        elif self._state == "processing":
            self._paint_processing(p, rect)
        else:
            self._paint_message(p, rect)
        p.end()

    def _paint_recording(self, p: QPainter, rect: QRectF) -> None:
        color = COMMAND_COLOR if self._mode == "command" else DICTATE_COLOR
        left, right = rect.left() + 18, rect.right() - 18
        if self._handsfree:
            # Cancel (x) on the left, stop (square) on the right.
            cx, cy = rect.left() + 20, rect.center().y()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawEllipse(QRectF(cx - 12, cy - 12, 24, 24))
            p.setPen(QPen(QColor(230, 230, 235), 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx - 4, cy - 4), QPointF(cx + 4, cy + 4))
            p.drawLine(QPointF(cx - 4, cy + 4), QPointF(cx + 4, cy - 4))
            sx = rect.right() - 20
            p.setPen(Qt.NoPen)
            p.setBrush(STOP_COLOR)
            p.drawEllipse(QRectF(sx - 12, cy - 12, 24, 24))
            p.setBrush(QColor(255, 255, 255))
            p.drawRoundedRect(QRectF(sx - 4.5, cy - 4.5, 9, 9), 2, 2)
            left, right = rect.left() + 42, rect.right() - 42

        bar_w, gap = 3.0, 3.0
        total = BARS * bar_w + (BARS - 1) * gap
        x = left + ((right - left) - total) / 2
        cy = rect.center().y()
        max_h = rect.height() - 16
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for i, level in enumerate(self._levels):
            envelope = 0.55 + 0.45 * math.sin(math.pi * (i + 0.5) / BARS)
            jitter = 0.85 + 0.3 * random.random() if level > 0.05 else 1.0
            h = max(3.0, level * envelope * jitter * max_h)
            p.drawRoundedRect(QRectF(x, cy - h / 2, bar_w, h), 1.5, 1.5)
            x += bar_w + gap

    def _paint_processing(self, p: QPainter, rect: QRectF) -> None:
        p.setPen(Qt.NoPen)
        cy = rect.center().y()
        for i in range(3):
            t = (math.sin(self._phase * 6 - i * 0.9) + 1) / 2
            color = QColor(245, 245, 247)
            color.setAlphaF(0.3 + 0.7 * t)
            p.setBrush(color)
            r = 3.0 + 1.2 * t
            cx = rect.center().x() + (i - 1) * 16
            p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

    def _paint_message(self, p: QPainter, rect: QRectF) -> None:
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        p.setFont(font)
        p.setPen(ERROR_COLOR if self._error else DICTATE_COLOR)
        text = self.fontMetrics().elidedText(self._message, Qt.ElideRight, int(rect.width() - 28))
        p.drawText(rect, Qt.AlignCenter, text)

    def mousePressEvent(self, event) -> None:
        if self._state != "recording" or not self._handsfree:
            return
        x = event.position().x()
        if x < 40:
            self.cancel_clicked.emit()
        elif x > self.width() - 40:
            self.stop_clicked.emit()
