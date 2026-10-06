"""Doctor accounts, login guard and audit log (docs/04 §6, §8)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any


# ------------------------------------------------------------------ doctor_account
def doctor_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM doctor_account WHERE username = ?", (username,)).fetchone()


def doctor_by_id(conn: sqlite3.Connection, doctor_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM doctor_account WHERE id = ?", (doctor_id,)).fetchone()


def doctor_by_staff(conn: sqlite3.Connection, staff_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM doctor_account WHERE staff_id = ?", (staff_id,)).fetchone()


def list_doctors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT d.*, s.full_name AS staff_name, s.is_active AS staff_active, s.staff_type "
        "FROM doctor_account d LEFT JOIN acc_staff s ON s.acc_id = d.staff_id ORDER BY d.username").fetchall()


def insert_doctor(conn: sqlite3.Connection, username: str, password_hash: bytes, staff_id: int,
                  is_director: bool, by: str, at: str) -> int:
    cur = conn.execute(
        "INSERT INTO doctor_account(username, password_hash, staff_id, is_director, is_active, created_by, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?, ?)", (username, password_hash, staff_id, int(is_director), by, at))
    return int(cur.lastrowid)


def update_doctor(conn: sqlite3.Connection, doctor_id: int, **fields: Any) -> None:
    allowed = {"password_hash", "is_director", "is_active"}
    assert fields and set(fields) <= allowed, fields
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE doctor_account SET {cols} WHERE id = ?", (*fields.values(), doctor_id))


# ------------------------------------------------------------------ login_guard
def guard_get(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT failed_count, locked_until FROM login_guard WHERE username = ?",
                        (username,)).fetchone()


def guard_set(conn: sqlite3.Connection, username: str, failed_count: int, locked_until: str | None) -> None:
    conn.execute(
        "INSERT INTO login_guard(username, failed_count, locked_until) VALUES (?, ?, ?) "
        "ON CONFLICT(username) DO UPDATE SET failed_count = excluded.failed_count, "
        "locked_until = excluded.locked_until", (username, failed_count, locked_until))


def guard_clear(conn: sqlite3.Connection, username: str) -> None:
    conn.execute("DELETE FROM login_guard WHERE username = ?", (username,))


# ------------------------------------------------------------------ audit_log
def audit(conn: sqlite3.Connection, at: str, actor: str, action: str, entity: str,
          entity_id: Any = None, before: Any = None, after: Any = None) -> None:
    conn.execute(
        "INSERT INTO audit_log(at, actor, action, entity, entity_id, before_json, after_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (at, actor, action, entity, None if entity_id is None else str(entity_id),
         None if before is None else json.dumps(before, ensure_ascii=False, default=str),
         None if after is None else json.dumps(after, ensure_ascii=False, default=str)))
