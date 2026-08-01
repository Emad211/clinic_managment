"""Owner-scoped read model for low-risk shadow review dispositions.

The queue never installs storage, assigns work, or exposes another owner's reviews. It
returns only current OPENED review heads whose source event remains current+confirmed.
"""
from __future__ import annotations

import sqlite3
from typing import Any


_REQUIRED_TABLES = frozenset(
    {
        "hypoglycemia_shadow_event_versions",
        "hypoglycemia_shadow_review_events",
    }
)


class HypoglycemiaShadowDispositionQueue:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        from src.adapters.sqlite.core import get_db

        return get_db()

    @staticmethod
    def _storage_state(db: sqlite3.Connection) -> str:
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)",
            tuple(sorted(_REQUIRED_TABLES)),
        ).fetchall()
        present = {
            str(row["name"] if hasattr(row, "keys") else row[0])
            for row in rows
        }
        if not present:
            return "NOT_INSTALLED"
        if present != _REQUIRED_TABLES:
            return "INCOMPLETE"
        return "READY"

    def state(self) -> str:
        return self._storage_state(self._db())

    def snapshot(self, *, owner_username: str) -> dict[str, Any]:
        owner = " ".join(str(owner_username or "").strip().split())
        if not owner:
            raise ValueError("owner_username is required")
        db = self._db()
        state = self._storage_state(db)
        if state != "READY":
            return {
                "storage_state": state,
                "open_count": 0,
                "items": [],
            }

        rows = [
            dict(row)
            for row in db.execute(
                """SELECT review.id AS review_event_id,
                          review.review_id,
                          review.sequence_number,
                          review.owner_username,
                          review.recorded_at AS review_opened_at,
                          event.id AS event_version_id,
                          event.event_id,
                          event.version_number AS event_version_number,
                          event.patient_link_id,
                          patient.full_name AS patient_name,
                          event.event_level,
                          event.occurred_at,
                          event.glucose_value,
                          event.glucose_unit,
                          event.external_assistance,
                          event.altered_function,
                          event.reporter_type,
                          event.source_system
                   FROM hypoglycemia_shadow_review_events review
                   JOIN hypoglycemia_shadow_event_versions event
                     ON event.id=review.event_version_id
                   JOIN patient_links patient
                     ON patient.id=review.patient_link_id
                   WHERE review.owner_username=?
                     AND review.event_type='OPENED'
                     AND review.sequence_number=(
                         SELECT MAX(head.sequence_number)
                         FROM hypoglycemia_shadow_review_events head
                         WHERE head.review_id=review.review_id
                     )
                     AND event.status='CONFIRMED'
                     AND event.verification='CONFIRMED'
                     AND event.version_number=(
                         SELECT MAX(current.version_number)
                         FROM hypoglycemia_shadow_event_versions current
                         WHERE current.event_id=event.event_id
                     )
                   ORDER BY review.recorded_at, review.id""",
                (owner,),
            ).fetchall()
        ]
        return {
            "storage_state": "READY",
            "open_count": len(rows),
            "items": rows,
        }
