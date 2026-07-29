"""Repository for non-clinical application settings."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


class SystemSettingsRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self.db = db

    def _connection(self) -> sqlite3.Connection:
        return self.db or get_db()

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._connection().execute(
            "SELECT value FROM settings WHERE key=?",
            (str(key),),
        ).fetchone()
        return str(row["value"]) if row and row["value"] is not None else default

    def set(self, key: str, value: str) -> None:
        db = self._connection()
        db.execute(
            """INSERT INTO settings (key,value,updated_at)
               VALUES (?,?,datetime('now','+3 hours','+30 minutes'))
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   updated_at=excluded.updated_at""",
            (str(key), str(value)),
        )
        db.commit()


__all__ = ["SystemSettingsRepository"]
