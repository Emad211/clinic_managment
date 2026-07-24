"""Atomic append-only permission overrides with optimistic concurrency."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.security_permission_schema import (
    ensure_security_permission_storage,
)
from src.common.utils import iran_now
from src.security.permissions import Permission


class SecurityPermissionConflict(RuntimeError):
    pass


class SecurityPermissionValidationError(ValueError):
    pass


def _now_text(value: datetime | None = None) -> str:
    current = value or iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.isoformat(sep=" ", timespec="seconds")


def _hash(payload: dict) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class SecurityPermissionRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self):
        db = self._connection or get_db()
        ensure_security_permission_storage(db)
        return db

    @staticmethod
    def _head(db, user_id: int, permission_key: str):
        return db.execute(
            """SELECT event.*
               FROM security_permission_events event
               WHERE event.user_id=? AND event.permission_key=?
                 AND NOT EXISTS (
                     SELECT 1 FROM security_permission_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1""",
            (user_id, permission_key),
        ).fetchone()

    def current_overrides(self, user_id: int) -> dict[Permission, bool]:
        rows = self._db().execute(
            """SELECT event.permission_key, event.effect
               FROM security_permission_events event
               WHERE event.user_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM security_permission_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.permission_key""",
            (int(user_id),),
        ).fetchall()
        result: dict[Permission, bool] = {}
        for row in rows:
            try:
                permission = Permission(row["permission_key"])
            except ValueError:
                # Unknown historical keys fail closed and are ignored by runtime.
                continue
            result[permission] = row["effect"] == "GRANTED"
        return result

    def list_for_user(self, user_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT event.*
                   FROM security_permission_events event
                   WHERE event.user_id=?
                   ORDER BY event.recorded_at DESC, event.id DESC""",
                (int(user_id),),
            ).fetchall()
        ]

    def record(
        self,
        *,
        user_id: int,
        permission: str | Permission,
        effect: str,
        actor_username: str,
        actor_user_id: int | None,
        reason: str,
        expected_current_event_id: int | None,
        recorded_at: datetime | None = None,
    ) -> dict:
        permission_key = Permission(permission).value
        normalized_effect = str(effect or "").strip().upper()
        if normalized_effect not in {"GRANTED", "REVOKED"}:
            raise SecurityPermissionValidationError("invalid permission effect")
        actor = " ".join(str(actor_username or "").strip().split())
        explanation = " ".join(str(reason or "").strip().split())
        if not actor:
            raise SecurityPermissionValidationError("actor_username is required")
        if len(explanation) < 3 or len(explanation) > 1000:
            raise SecurityPermissionValidationError(
                "permission reason must contain 3 to 1000 characters"
            )
        if (
            normalized_effect == "GRANTED"
            and actor_user_id is not None
            and int(actor_user_id) == int(user_id)
        ):
            raise SecurityPermissionValidationError(
                "self-granting a permission is not allowed"
            )
        recorded = _now_text(recorded_at)
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            user = db.execute(
                "SELECT id FROM users WHERE id=?",
                (int(user_id),),
            ).fetchone()
            if not user:
                raise LookupError("permission target user not found")
            head = self._head(db, int(user_id), permission_key)
            current_id = int(head["id"]) if head else None
            if current_id != expected_current_event_id:
                raise SecurityPermissionConflict(
                    "permission state changed after load"
                )
            payload = {
                "user_id": int(user_id),
                "permission_key": permission_key,
                "effect": normalized_effect,
                "actor_user_id": actor_user_id,
                "actor_username": actor,
                "reason": explanation,
                "recorded_at": recorded,
                "supersedes_event_id": current_id,
            }
            cursor = db.execute(
                """INSERT INTO security_permission_events
                   (user_id, permission_key, effect, actor_user_id,
                    actor_username, reason, recorded_at,
                    supersedes_event_id, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(user_id),
                    permission_key,
                    normalized_effect,
                    actor_user_id,
                    actor,
                    explanation,
                    recorded,
                    current_id,
                    _hash(payload),
                ),
            )
            row = db.execute(
                "SELECT * FROM security_permission_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise
