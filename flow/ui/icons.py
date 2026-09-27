"""Tray icons drawn at runtime (no binary assets)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

STATE_COLORS = {
    "idle": QColor(31, 41, 55),
    "recording": QColor(239, 68, 68),
    "command": QColor(124, 58, 237),
    "processing": QColor(79, 70, 229),
    "paused": QColor(107, 114, 128),
}


def mic_icon(state: str = "idle") -> QIcon:
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(STATE_COLORS.get(state, STATE_COLORS["idle"]))
    p.drawRoundedRect(QRectF(0, 0, size, size), 16, 16)

    white = QColor(255, 255, 255)
    p.setBrush(white)
    p.drawRoundedRect(QRectF(24, 10, 16, 28), 8, 8)
    pen = QPen(white, 4.5, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(16, 16, 32, 30), 180 * 16, 180 * 16)
    p.drawLine(32, 47, 32, 54)
    if state == "paused":
        p.setPen(QPen(white, 5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(12, 12, 52, 52)
    p.end()
    return QIcon(pm)
