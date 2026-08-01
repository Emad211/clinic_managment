"""Identifier-free aggregate observability for the hypoglycemia shadow slice.

This read model never installs storage, writes data, opens clinical tasks, or exposes
patient/event/source identities. Aggregate low-cell counts remain internal health data
and are not represented as anonymous or PHI-free.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Any, Callable

from src.common.utils import IRAN_TZ


_EVENT_STATUSES = (
    "CANDIDATE",
    "CONFIRMED",
    "CONFLICT",
    "REJECTED",
    "ENTERED_IN_ERROR",
)
_EVENT_LEVELS = ("LEVEL_2", "LEVEL_3", "UNKNOWN")
_REVIEW_TYPES = ("OPENED", "DISPOSITION_RECORDED", "ENTERED_IN_ERROR")
_DISPOSITIONS = (
    "NO_CHANGE",
    "MEDICATION_CHANGE_RECORDED",
    "EDUCATION",
    "DEVICE_REVIEW",
    "REFERRAL_RECORDED",
    "FOLLOWUP",
    "OTHER",
)
_REQUIRED_TABLES = frozenset(
    {
        "hypoglycemia_shadow_event_versions",
        "hypoglycemia_shadow_review_events",
    }
)
_SAVEPOINT = "hypoglycemia_shadow_observability"
_PRIVACY_SCOPE = "INTERNAL_AGGREGATE_LOW_CELL_COUNTS_POSSIBLE"


def _time_text(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(IRAN_TZ).replace(tzinfo=None)
    return value.isoformat(sep=" ", timespec="seconds")


def _zeros(keys: tuple[str, ...]) -> dict[str, int]:
    return {key: 0 for key in keys}


class HypoglycemiaShadowObservability:
    """Build one consistent identifier-free snapshot without database writes."""

    def __init__(
        self,
        db: sqlite3.Connection | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self._connection = db
        self._clock = clock or (lambda: datetime.now(IRAN_TZ))

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

    def _empty(self, storage_state: str) -> dict[str, Any]:
        attention = storage_state == "INCOMPLETE"
        return {
            "schema_version": "1.0",
            "generated_at": _time_text(self._clock()),
            "storage_state": storage_state,
            "integrity_state": "ATTENTION_REQUIRED" if attention else "OK",
            "contains_direct_identifiers": False,
            "privacy_scope": _PRIVACY_SCOPE,
            "current_event_total": 0,
            "event_counts": _zeros(_EVENT_STATUSES),
            "event_level_counts": _zeros(_EVENT_LEVELS),
            "current_review_total": 0,
            "review_counts": _zeros(_REVIEW_TYPES),
            "disposition_counts": _zeros(_DISPOSITIONS),
            "backlog": {
                "candidate_missing_occurrence_time": 0,
                "candidate_below_confirmed_verification": 0,
                "confirmed_without_active_review": 0,
            },
            "safety_anomalies": {
                "review_source_no_longer_current_confirmed": 0,
            },
        }

    def snapshot(self) -> dict[str, Any]:
        db = self._db()
        db.execute(f"SAVEPOINT {_SAVEPOINT}")
        try:
            result = self._snapshot_in_read_transaction(db)
            db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            return result
        except Exception:
            db.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
            db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            raise

    def _snapshot_in_read_transaction(
        self,
        db: sqlite3.Connection,
    ) -> dict[str, Any]:
        storage_state = self._storage_state(db)
        if storage_state != "READY":
            return self._empty(storage_state)

        current_events = [
            dict(row)
            for row in db.execute(
                """SELECT version.*
                   FROM hypoglycemia_shadow_event_versions version
                   WHERE version.version_number=(
                       SELECT MAX(head.version_number)
                       FROM hypoglycemia_shadow_event_versions head
                       WHERE head.event_id=version.event_id
                   )
                   ORDER BY version.event_id"""
            ).fetchall()
        ]
        current_reviews = [
            dict(row)
            for row in db.execute(
                """SELECT event.*
                   FROM hypoglycemia_shadow_review_events event
                   WHERE event.sequence_number=(
                       SELECT MAX(head.sequence_number)
                       FROM hypoglycemia_shadow_review_events head
                       WHERE head.review_id=event.review_id
                   )
                   ORDER BY event.review_id"""
            ).fetchall()
        ]
        event_identity = {
            int(row["id"]): str(row["event_id"])
            for row in db.execute(
                "SELECT id, event_id FROM hypoglycemia_shadow_event_versions"
            ).fetchall()
        }
        current_by_event = {
            str(row["event_id"]): row for row in current_events
        }

        event_counts = _zeros(_EVENT_STATUSES)
        level_counts = _zeros(_EVENT_LEVELS)
        for row in current_events:
            event_counts[str(row["status"])] += 1
            level_counts[str(row["event_level"])] += 1

        review_counts = _zeros(_REVIEW_TYPES)
        disposition_counts = _zeros(_DISPOSITIONS)
        active_review_versions: set[int] = set()
        stale_source_reviews = 0
        for row in current_reviews:
            event_type = str(row["event_type"])
            review_counts[event_type] += 1
            disposition = row.get("disposition_type")
            if disposition:
                disposition_counts[str(disposition)] += 1
            if event_type == "ENTERED_IN_ERROR":
                continue
            source_version_id = int(row["event_version_id"])
            event_id = event_identity.get(source_version_id)
            current = current_by_event.get(event_id) if event_id else None
            source_is_valid = bool(
                current
                and int(current["id"]) == source_version_id
                and current["status"] == "CONFIRMED"
                and current["verification"] == "CONFIRMED"
            )
            if source_is_valid:
                active_review_versions.add(source_version_id)
            else:
                stale_source_reviews += 1

        candidate_missing_time = sum(
            1
            for row in current_events
            if row["status"] == "CANDIDATE" and row["occurred_at"] is None
        )
        candidate_below_confirmed = sum(
            1
            for row in current_events
            if row["status"] == "CANDIDATE"
            and row["verification"] != "CONFIRMED"
        )
        confirmed_without_review = sum(
            1
            for row in current_events
            if row["status"] == "CONFIRMED"
            and row["verification"] == "CONFIRMED"
            and int(row["id"]) not in active_review_versions
        )

        return {
            "schema_version": "1.0",
            "generated_at": _time_text(self._clock()),
            "storage_state": "READY",
            "integrity_state": (
                "ATTENTION_REQUIRED" if stale_source_reviews else "OK"
            ),
            "contains_direct_identifiers": False,
            "privacy_scope": _PRIVACY_SCOPE,
            "current_event_total": len(current_events),
            "event_counts": event_counts,
            "event_level_counts": level_counts,
            "current_review_total": len(current_reviews),
            "review_counts": review_counts,
            "disposition_counts": disposition_counts,
            "backlog": {
                "candidate_missing_occurrence_time": candidate_missing_time,
                "candidate_below_confirmed_verification": candidate_below_confirmed,
                "confirmed_without_active_review": confirmed_without_review,
            },
            "safety_anomalies": {
                "review_source_no_longer_current_confirmed": stale_source_reviews,
            },
        }
