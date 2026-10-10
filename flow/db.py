"""Shared SQLite storage for the dictionary, snippets and history."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

MIGRATIONS = [
    """
    CREATE TABLE vocabulary (
        id INTEGER PRIMARY KEY,
        word TEXT NOT NULL UNIQUE COLLATE NOCASE
    );
    CREATE TABLE replacements (
        id INTEGER PRIMARY KEY,
        pattern TEXT NOT NULL,
        replacement TEXT NOT NULL
    );
    CREATE TABLE snippets (
        id INTEGER PRIMARY KEY,
        trigger TEXT NOT NULL UNIQUE COLLATE NOCASE,
        expansion TEXT NOT NULL
    );
    CREATE TABLE history (
        id INTEGER PRIMARY KEY,
        created_at REAL NOT NULL,
        mode TEXT NOT NULL,
        app TEXT,
        style TEXT,
        raw TEXT NOT NULL,
        final TEXT NOT NULL,
        duration REAL,
        stt_ms INTEGER,
        llm_ms INTEGER
    );
    CREATE INDEX history_created ON history(created_at);
    """,
    """
    CREATE TABLE skills (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        instruction TEXT NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: Path | str):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for index in range(version, len(MIGRATIONS)):
                self._conn.executescript(MIGRATIONS[index])
                self._conn.execute(f"PRAGMA user_version = {index + 1}")
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
