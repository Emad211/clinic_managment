"""Repository for the rebuildable FO-2 shadow Work Item projection."""
from __future__ import annotations

import json
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followup_projection_schema import (
    ensure_followup_projection_storage,
)
from src.services.followup_orchestration.identity import canonical_hash

_COLUMNS = (
    "episode_id",
    "patient_link_id",
    "episode_type",
    "reason_code",
    "reason_label",
    "why_created",
    "current_state",
    "state_class",
    "next_action_code",
    "next_action_label",
    "waiting_reason_code",
    "waiting_reason_label",
    "blocked_reason_code",
    "blocked_reason_label",
    "owner_role_proposal",
    "owner_user_id",
    "action_due_at",
    "target_at",
    "priority",
    "sla_state",
    "last_source_event_at",
    "last_episode_event_id",
    "sms_state",
    "appointment_state",
    "evidence_state",
    "source_count",
    "source_fingerprint",
    "state_detail_json",
    "projection_version",
    "policy_version",
    "as_of_at",
    "projection_hash",
    "rebuilt_at",
)


class FollowupProjectionRepository:
    def __init__(
        self,
        db: sqlite3.Connection | None = None,
        *,
        install_schema: bool = True,
    ):
        self._connection = db or get_db()
        if install_schema:
            ensure_followup_projection_storage(self._connection)

    def _db(self) -> sqlite3.Connection:
        return self._connection

    @staticmethod
    def _values(row: dict) -> tuple:
        values = []
        for column in _COLUMNS:
            value = row.get(column)
            if column == "state_detail_json" and not isinstance(value, str):
                value = json.dumps(
                    value or {},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            values.append(value)
        return tuple(values)

    def replace_all(self, rows: list[dict]) -> dict:
        """Atomically replace the cache; source and Episode tables are untouched."""
        db = self._db()
        placeholders = ",".join("?" for _ in _COLUMNS)
        columns = ",".join(_COLUMNS)
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("DELETE FROM followup_work_item_projection")
            if rows:
                db.executemany(
                    f"INSERT INTO followup_work_item_projection ({columns}) "
                    f"VALUES ({placeholders})",
                    [self._values(row) for row in rows],
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {
            "rows_written": len(rows),
            "projection_set_hash": self.set_hash(),
        }

    def upsert_one(self, row: dict) -> dict:
        """Refresh one disposable projection row after an authoritative action."""
        db = self._db()
        placeholders = ",".join("?" for _ in _COLUMNS)
        columns = ",".join(_COLUMNS)
        updates = ",".join(
            f"{column}=excluded.{column}"
            for column in _COLUMNS
            if column != "episode_id"
        )
        db.execute(
            f"""INSERT INTO followup_work_item_projection ({columns})
                VALUES ({placeholders})
                ON CONFLICT(episode_id) DO UPDATE SET {updates}""",
            self._values(row),
        )
        db.commit()
        return {
            "episode_id": str(row["episode_id"]),
            "projection_hash": str(row["projection_hash"]),
        }

    def get(self, episode_id: str) -> dict | None:
        row = self._db().execute(
            "SELECT * FROM followup_work_item_projection WHERE episode_id=?",
            (str(episode_id),),
        ).fetchone()
        return dict(row) if row else None

    def list_all(self) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                "SELECT * FROM followup_work_item_projection ORDER BY episode_id"
            ).fetchall()
        ]

    def count(self) -> int:
        row = self._db().execute(
            "SELECT COUNT(*) FROM followup_work_item_projection"
        ).fetchone()
        return int(row[0])

    def set_hash(self) -> str:
        rows = self._db().execute(
            """SELECT episode_id, projection_hash
               FROM followup_work_item_projection ORDER BY episode_id"""
        ).fetchall()
        return canonical_hash(
            [
                {"episode_id": str(row[0]), "projection_hash": str(row[1])}
                for row in rows
            ]
        )


__all__ = ["FollowupProjectionRepository"]
