"""Clinician-owned read model for hypoglycemia shadow candidate adjudication.

The queue never installs or repairs storage and never creates a review/task/action.
It exposes only current CANDIDATE or CONFLICT heads to explicitly authorized users.
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


class HypoglycemiaShadowAdjudicationQueue:
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
        """Return readiness without loading any patient/event row."""
        return self._storage_state(self._db())

    def snapshot(self) -> dict[str, Any]:
        db = self._db()
        state = self._storage_state(db)
        if state != "READY":
            return {
                "storage_state": state,
                "candidate_count": 0,
                "conflict_count": 0,
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
                          event.status,
                          event.event_level,
                          event.occurred_at,
                          event.recorded_at,
                          event.glucose_value,
                          event.glucose_unit,
                          event.external_assistance,
                          event.altered_function,
                          event.reporter_type,
                          event.verification,
                          event.source_system
                   FROM hypoglycemia_shadow_event_versions event
                   JOIN patient_links patient
                     ON patient.id=event.patient_link_id
                   WHERE event.status IN ('CANDIDATE','CONFLICT')
                     AND event.version_number=(
                         SELECT MAX(head.version_number)
                         FROM hypoglycemia_shadow_event_versions head
                         WHERE head.event_id=event.event_id
                     )
                   ORDER BY
                     CASE WHEN event.status='CONFLICT' THEN 0 ELSE 1 END,
                     CASE WHEN event.occurred_at IS NULL THEN 0 ELSE 1 END,
                     event.occurred_at,
                     event.id"""
            ).fetchall()
        ]
        return {
            "storage_state": "READY",
            "candidate_count": sum(
                1 for row in rows if row["status"] == "CANDIDATE"
            ),
            "conflict_count": sum(
                1 for row in rows if row["status"] == "CONFLICT"
            ),
            "items": rows,
        }
