"""The floating panel: live waveform, the words as they are recognized, progress and errors.

It never takes focus, so whatever you were typing into stays active.
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QWidget

BARS = 14
RADIUS = 18
PANEL = QColor(17, 17, 20, 243)
PANEL_EDGE = QColor(255, 255, 255, 26)
HIGHLIGHT = QColor(255, 255, 255, 16)
TEXT = QColor(236, 236, 240)
DIM = QColor(150, 152, 160)
ACCENT = QColor(235, 236, 240)
COMMAND_ACCENT = QColor(167, 139, 250)
ERROR = QColor(248, 113, 113)
STOP = QColor(239, 68, 68)

MIN_WIDTH = 260
MAX_WIDTH = 560
BASE_HEIGHT = 44
LINE_HEIGHT = 18
MAX_LINES = 3


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
        self._status = ""       # "notepad.exe · formal"
        self._partial = ""      # words recognized so far, while still speaking
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
    def show_recording(self, mode: str, handsfree: bool, status: str = "") -> None:
        self._levels = deque([0.0] * BARS, maxlen=BARS)
        self._mode, self._handsfree, self._status = mode, handsfree, status
        self._partial = ""
        self._enter("recording")

    def set_mode(self, mode: str, handsfree: bool) -> None:
        self._mode, self._handsfree = mode, handsfree
        if self._state == "recording":
            self._place()
            self.update()

    def set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            if self._state in ("recording", "processing"):
                self._place()
                self.update()

    def set_partial(self, text: str) -> None:
        """The words recognized so far: shown live while the user is still speaking."""
        text = " ".join(text.split())
        if text != self._partial:
            self._partial = text
            if self._state == "recording":
                self._place()
                self.update()

    def show_processing(self, status: str = "") -> None:
        self._status = status or self._status
        self._enter("processing")  # the recognized text stays visible, dimmed, while cleanup runs

    def show_message(self, text: str, error: bool = True, ms: int = 2600) -> None:
        self._message, self._error = text, error
        self._enter("message")
        self._hide_timer.start(ms)

    def hide_overlay(self) -> None:
        self._state = "hidden"
        self._partial = ""
        self._anim.stop()
        self._hide_timer.stop()
        self.hide()

    @property
    def state(self) -> str:
        return self._state

    # Layout ---------------------------------------------------------------------------------
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

    def _body_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(10.5)
        return font

    def _wrapped_lines(self, text: str, width: int) -> list[str]:
        if not text:
            return []
        metrics = QFontMetrics(self._body_font())
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if metrics.horizontalAdvance(candidate) <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        # Keep the most recent words visible, like a caption.
        if len(lines) > MAX_LINES:
            lines = lines[-MAX_LINES:]
        return lines

    def _size(self) -> tuple[int, int]:
        metrics = QFontMetrics(self._body_font())
        if self._state == "message":
            width = min(MAX_WIDTH, max(MIN_WIDTH, metrics.horizontalAdvance(self._message) + 44))
            return width, BASE_HEIGHT
        width = MIN_WIDTH
        if self._status:
            width = max(width, 150 + metrics.horizontalAdvance(self._status))
        if self._partial:
            width = MAX_WIDTH
        if self._handsfree:
            width = max(width, 320)
        width = min(MAX_WIDTH, width)
        showing_text = self._state in ("recording", "processing")
        lines = self._wrapped_lines(self._partial, width - 36) if showing_text else []
        return width, BASE_HEIGHT + (len(lines) * LINE_HEIGHT + 8 if lines else 0)

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

    # Painting -------------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        if self._state == "hidden":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        p.fillPath(path, PANEL)
        # A hairline of light along the top edge reads as a raised surface.
        p.setPen(QPen(HIGHLIGHT, 1))
        p.drawLine(QPointF(rect.left() + RADIUS, rect.top() + 1),
                   QPointF(rect.right() - RADIUS, rect.top() + 1))
        p.setPen(QPen(PANEL_EDGE, 1))
        p.drawPath(path)

        top = QRectF(rect.left(), rect.top(), rect.width(), BASE_HEIGHT)
        if self._state == "recording":
            self._paint_recording(p, top)
            self._paint_partial(p, rect)
        elif self._state == "processing":
            self._paint_processing(p, top)
            self._paint_partial(p, rect, dim=True)
        else:
            self._paint_message(p, rect)
        p.end()

    def _accent(self) -> QColor:
        return COMMAND_ACCENT if self._mode == "command" else ACCENT

    def _paint_recording(self, p: QPainter, rect: QRectF) -> None:
        left = rect.left() + 16
        right = rect.right() - 16
        if self._handsfree:
            cy = rect.center().y()
            cx = rect.left() + 22
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawEllipse(QRectF(cx - 12, cy - 12, 24, 24))
            p.setPen(QPen(QColor(225, 226, 232), 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx - 4, cy - 4), QPointF(cx + 4, cy + 4))
            p.drawLine(QPointF(cx - 4, cy + 4), QPointF(cx + 4, cy - 4))
            sx = rect.right() - 22
            p.setPen(Qt.NoPen)
            p.setBrush(STOP)
            p.drawEllipse(QRectF(sx - 12, cy - 12, 24, 24))
            p.setBrush(QColor(255, 255, 255))
            p.drawRoundedRect(QRectF(sx - 4.5, cy - 4.5, 9, 9), 2, 2)
            left, right = rect.left() + 44, rect.right() - 44

        bar_w, gap = 3.0, 4.0
        x = left
        cy = rect.center().y()
        max_h = BASE_HEIGHT - 20
        p.setPen(Qt.NoPen)
        p.setBrush(self._accent())
        for i, level in enumerate(self._levels):
            envelope = 0.55 + 0.45 * math.sin(math.pi * (i + 0.5) / BARS)
            jitter = 0.85 + 0.3 * random.random() if level > 0.05 else 1.0
            h = max(3.0, level * envelope * jitter * max_h)
            p.drawRoundedRect(QRectF(x, cy - h / 2, bar_w, h), 1.5, 1.5)
            x += bar_w + gap

        label = self._status or ("Command" if self._mode == "command" else "Listening")
        self._paint_label(p, QRectF(x + 10, rect.top(), right - x - 10, BASE_HEIGHT), label)

    def _paint_label(self, p: QPainter, rect: QRectF, text: str) -> None:
        font = self._body_font()
        font.setPointSizeF(9.0)
        p.setFont(font)
        p.setPen(DIM)
        elided = QFontMetrics(font).elidedText(text, Qt.ElideRight, int(rect.width()))
        p.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

    def _paint_partial(self, p: QPainter, rect: QRectF, dim: bool = False) -> None:
        lines = self._wrapped_lines(self._partial, int(rect.width()) - 36)
        if not lines:
            return
        p.setFont(self._body_font())
        p.setPen(DIM if dim else TEXT)
        y = rect.top() + BASE_HEIGHT - 6
        for line in lines:
            p.drawText(QRectF(rect.left() + 18, y, rect.width() - 36, LINE_HEIGHT),
                       Qt.AlignVCenter | Qt.AlignLeft, line)
            y += LINE_HEIGHT

    def _paint_processing(self, p: QPainter, rect: QRectF) -> None:
        p.setPen(Qt.NoPen)
        cy = rect.center().y()
        x = rect.left() + 22
        for i in range(3):
            t = (math.sin(self._phase * 6 - i * 0.9) + 1) / 2
            color = QColor(self._accent())
            color.setAlphaF(0.35 + 0.65 * t)
            p.setBrush(color)
            r = 3.0 + 1.3 * t
            p.drawEllipse(QRectF(x + i * 14 - r, cy - r, 2 * r, 2 * r))
        label = f"Cleaning up · {self._status}" if self._status else "Cleaning up"
        self._paint_label(p, QRectF(x + 54, rect.top(), rect.width() - x - 60, BASE_HEIGHT), label)

    def _paint_message(self, p: QPainter, rect: QRectF) -> None:
        font = self._body_font()
        font.setPointSizeF(9.5)
        p.setFont(font)
        p.setPen(ERROR if self._error else TEXT)
        text = QFontMetrics(font).elidedText(self._message, Qt.ElideRight, int(rect.width() - 28))
        p.drawText(rect, Qt.AlignCenter, text)

    # Clicks (hands-free only; the panel is otherwise inert) ----------------------------------
    def mousePressEvent(self, event) -> None:
        if self._state != "recording" or not self._handsfree:
            return
        x = event.position().x()
        if event.position().y() > BASE_HEIGHT:
            return
        if x < 44:
            self.cancel_clicked.emit()
        elif x > self.width() - 44:
            self.stop_clicked.emit()
