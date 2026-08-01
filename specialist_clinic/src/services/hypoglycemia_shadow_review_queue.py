"""Read-only queue of current confirmed events eligible for explicit review opening.

The queue does not install or repair storage and does not infer urgency, create tasks,
or make any clinical recommendation.  It only identifies exact confirmed event versions
that have never had a shadow review root.
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


class HypoglycemiaShadowReviewQueue:
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
        """Return storage readiness without reading patient/event rows."""
        return self._storage_state(self._db())

    def snapshot(self) -> dict[str, Any]:
        db = self._db()
        state = self._storage_state(db)
        if state != "READY":
            return {
                "storage_state": state,
                "ready_count": 0,
                "items": [],
            }

        rows = [
            dict(row)
            for row in db.execute(
                """SELECT event.id AS version_id,
                          event.event_id,
                          event.version_number,
                          event.patient_link_id,
                          patient.full_name AS patient_name,
                          event.event_level,
                          event.occurred_at,
                          event.recorded_at,
                          event.glucose_value,
                          event.glucose_unit,
                          event.external_assistance,
                          event.altered_function,
                          event.reporter_type,
                          event.source_system,
                          event.actor_username AS adjudicated_by
                   FROM hypoglycemia_shadow_event_versions event
                   JOIN patient_links patient
                     ON patient.id=event.patient_link_id
                   WHERE event.status='CONFIRMED'
                     AND event.verification='CONFIRMED'
                     AND event.version_number=(
                         SELECT MAX(head.version_number)
                         FROM hypoglycemia_shadow_event_versions head
                         WHERE head.event_id=event.event_id
                     )
                     AND NOT EXISTS (
                         SELECT 1
                         FROM hypoglycemia_shadow_review_events review
                         WHERE review.event_version_id=event.id
                           AND review.sequence_number=1
                     )
                   ORDER BY
                     CASE WHEN event.occurred_at IS NULL THEN 1 ELSE 0 END,
                     event.occurred_at,
                     event.id"""
            ).fetchall()
        ]
        return {
            "storage_state": "READY",
            "ready_count": len(rows),
            "items": rows,
        }
