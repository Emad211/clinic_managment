"""Key/value stores: ``sync_state`` (poller bookkeeping) and ``setting`` (user-changed settings)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any


def sync_get(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM sync_state").fetchall())


def sync_set(conn: sqlite3.Connection, values: dict[str, Any]) -> None:
    conn.executemany(
        "INSERT INTO sync_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in values.items()])


def setting_get(conn: sqlite3.Connection, key: str) -> Any | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def setting_set(conn: sqlite3.Connection, key: str, value: Any, by: str, at: str) -> None:
    conn.execute(
        "INSERT INTO setting(key, value, updated_by, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, "
        "updated_at = excluded.updated_at",
        (key, json.dumps(value, ensure_ascii=False), by, at))


def setting_delete(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM setting WHERE key = ?", (key,))
