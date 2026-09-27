"""Dictation history."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .db import Database


@dataclass
class Entry:
    id: int
    created_at: float
    mode: str
    app: str
    style: str
    raw: str
    final: str
    duration: float
    stt_ms: int
    llm_ms: int


class History:
    def __init__(self, db: Database):
        self._db = db

    def add(self, *, mode: str, app: str, style: str, raw: str, final: str,
            duration: float, stt_ms: int, llm_ms: int) -> None:
        self._db.execute(
            "INSERT INTO history(created_at, mode, app, style, raw, final, duration, stt_ms, llm_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), mode, app, style, raw, final, duration, stt_ms, llm_ms),
        )

    def search(self, text: str = "", limit: int = 300) -> list[Entry]:
        if text.strip():
            like = f"%{text.strip()}%"
            rows = self._db.query(
                "SELECT * FROM history WHERE final LIKE ? OR raw LIKE ? OR app LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (like, like, like, limit),
            )
        else:
            rows = self._db.query("SELECT * FROM history ORDER BY created_at DESC LIMIT ?", (limit,))
        return [Entry(**dict(row)) for row in rows]

    def recent(self, count: int = 5) -> list[Entry]:
        return self.search(limit=count)

    def delete(self, entry_id: int) -> None:
        self._db.execute("DELETE FROM history WHERE id = ?", (entry_id,))

    def clear(self) -> None:
        self._db.execute("DELETE FROM history")

    def prune(self, retention_days: int) -> None:
        if retention_days > 0:
            cutoff = time.time() - retention_days * 86400
            self._db.execute("DELETE FROM history WHERE created_at < ?", (cutoff,))

    def stats(self) -> tuple[int, float]:
        """Total words dictated and average words per minute."""
        rows = self._db.query("SELECT final, duration FROM history WHERE mode = 'dictate'")
        words = sum(len(row["final"].split()) for row in rows)
        seconds = sum(row["duration"] or 0 for row in rows)
        wpm = words / (seconds / 60) if seconds > 0 else 0.0
        return words, wpm
