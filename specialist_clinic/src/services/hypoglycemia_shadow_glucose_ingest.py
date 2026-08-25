"""Atomic bridge from recorded fasting glucose to shadow candidates.

This is deliberately not part of ``VitalsRepository``: the repository remains
purely descriptive. The bridge creates only a CANDIDATE event and never confirms
an episode, opens a review, creates a task/alert, or produces a treatment action.

Engine independence (safety net — intentional):
    This bridge is a patient-safety detector for Level-2 hypoglycemia
    (fasting glucose < 54 mg/dL). It runs *inline* on the vital-write path
    (``VitalsRepository.add_reading``) inside the same request transaction —
    it does NOT depend on the clinical analytical engine (Engine v2), the rule
    engine, or the background scheduler. A Level-2 glucose therefore produces a
    shadow candidate identically whether the analytical engine is ON, OFF, or
    UNAVAILABLE, and whether or not the scheduler is alive.

    This independence is required, not incidental: a missed hypoglycemia event
    is a patient-safety false negative, so this detector must never be gated
    behind (or silenced by) the toggle that turns the analytical engine off.
    Keep it free of any ``clinical_engine`` / ``rule_engine`` import; the
    guard test ``tests/test_hypoglycemia_shadow_engine_independent.py`` enforces
    this and must stay green.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Any, Callable

from src.adapters.sqlite.vitals_repo import VitalsRepository
from src.common.utils import IRAN_TZ, iran_now
from src.services.hypoglycemia_shadow import (
    HypoglycemiaShadowConflict,
    HypoglycemiaShadowService,
    ensure_hypoglycemia_shadow_storage,
)


_FASTING_GLUCOSE_KEY = "fbs"
_LEVEL_2_LIMIT_MG_DL = 54.0
_REQUIRED_TABLES = frozenset(
    {
        "hypoglycemia_shadow_event_versions",
        "hypoglycemia_shadow_review_events",
    }
)
_INVALIDATABLE_STATES = frozenset({"CANDIDATE", "CONFLICT", "CONFIRMED"})


class HypoglycemiaShadowSourceIntegrityError(RuntimeError):
    """The source and its shadow lineage cannot be changed atomically."""


class _JoinedConnection:
    """Let the existing shadow service join a caller-owned SQLite transaction.

    The orchestration ensures storage before opening its transaction.  The proxy
    therefore suppresses the service's idempotent schema script and connection
    context commit while delegating all SQL to the real connection.
    """

    def __init__(self, db: sqlite3.Connection):
        self._db = db

    def executescript(self, _script: str):
        return self

    def commit(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def __getattr__(self, name: str):
        return getattr(self._db, name)


def _time_text(value: datetime | str | None) -> str:
    if value is None:
        parsed = iran_now()
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(IRAN_TZ).replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _mg_dl(value: Any, unit: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    normalized = str(unit or "").strip().lower()
    if normalized == "mg/dl":
        return numeric
    if normalized == "mmol/l":
        return numeric * 18.0
    return None


class HypoglycemiaShadowGlucoseIngestService:
    """Join fasting-glucose source lifecycle to the isolated shadow ledger."""

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

    @staticmethod
    def _eligible(row: dict[str, Any]) -> bool:
        if str(row.get("type") or "").strip().lower() != _FASTING_GLUCOSE_KEY:
            return False
        value_mg_dl = _mg_dl(row.get("value"), row.get("unit"))
        return value_mg_dl is not None and value_mg_dl < _LEVEL_2_LIMIT_MG_DL

    def _joined_shadow(self, db: sqlite3.Connection) -> HypoglycemiaShadowService:
        if self._storage_state(db) != "READY":
            raise HypoglycemiaShadowSourceIntegrityError(
                "hypoglycemia shadow storage is not ready"
            )
        return HypoglycemiaShadowService(
            _JoinedConnection(db),
            clock=self._clock,
        )

    @staticmethod
    def _reading(
        db: sqlite3.Connection,
        *,
        patient_link_id: int,
        reading_id: int,
    ) -> dict[str, Any]:
        row = db.execute(
            """SELECT * FROM vital_readings
               WHERE id=? AND patient_link_id=?""",
            (int(reading_id), int(patient_link_id)),
        ).fetchone()
        if row is None:
            raise LookupError("vital reading not found for patient")
        return dict(row)

    @staticmethod
    def _event_for_reading(
        db: sqlite3.Connection,
        reading_id: int,
    ) -> str | None:
        row = db.execute(
            """SELECT event_id
               FROM hypoglycemia_shadow_event_versions
               WHERE source_system='vital_readings'
                 AND source_record_id=?
                 AND version_number=1""",
            (str(int(reading_id)),),
        ).fetchone()
        return str(row["event_id"]) if row else None

    def _create_candidate(
        self,
        db: sqlite3.Connection,
        row: dict[str, Any],
        *,
        actor_username: str,
    ) -> dict[str, Any]:
        return self._joined_shadow(db).create_candidate(
            patient_link_id=int(row["patient_link_id"]),
            source_system="vital_readings",
            source_record_id=str(int(row["id"])),
            actor_username=actor_username,
            reporter_type="SYSTEM",
            occurred_at=row.get("measured_at"),
            event_level="LEVEL_2",
            glucose_value=row.get("value"),
            glucose_unit=row.get("unit"),
            external_assistance="UNKNOWN",
            altered_function="UNKNOWN",
            verification="PROVISIONAL",
            note=(
                "Candidate derived from a recorded fasting-glucose observation; "
                "clinician adjudication is required."
            ),
        )

    def add_vital_reading(
        self,
        patient_link_id: int,
        *,
        vtype: str,
        value: Any,
        unit: str | None = None,
        measured_at: datetime | str | None = None,
        source: str = "clinic",
        notes: str | None = None,
        recorded_by: str | None = None,
    ) -> int:
        """Insert one reading and, only when eligible, one atomic candidate."""
        db = self._db()
        normalized_time = _time_text(measured_at)
        effective_unit = unit
        if effective_unit is None:
            from src.adapters.sqlite.vitals_repo import VITAL_TYPES

            effective_unit = VITAL_TYPES.get(vtype, {}).get("unit")
        preview = {
            "type": vtype,
            "value": value,
            "unit": effective_unit,
        }
        repo = VitalsRepository(db)
        if not self._eligible(preview):
            return repo.add_reading(
                patient_link_id,
                vtype=vtype,
                value=value,
                unit=effective_unit,
                measured_at=normalized_time,
                source=source,
                notes=notes,
                recorded_by=recorded_by,
            )

        # Install the isolated ledger before beginning the source/candidate
        # transaction; executescript must never commit a pending vital insert.
        ensure_hypoglycemia_shadow_storage(db)
        actor = str(recorded_by or "system:vitals").strip() or "system:vitals"
        with db:
            reading_id = repo.add_reading(
                patient_link_id,
                vtype=vtype,
                value=value,
                unit=effective_unit,
                measured_at=normalized_time,
                source=source,
                notes=notes,
                recorded_by=recorded_by,
                commit=False,
            )
            row = self._reading(
                db,
                patient_link_id=patient_link_id,
                reading_id=reading_id,
            )
            self._create_candidate(db, row, actor_username=actor)
        return reading_id

    def ensure_candidate_for_reading(
        self,
        *,
        patient_link_id: int,
        reading_id: int,
        actor_username: str,
    ) -> dict[str, Any] | None:
        """Idempotently process one existing reading without broad scanning."""
        db = self._db()
        row = self._reading(
            db,
            patient_link_id=patient_link_id,
            reading_id=reading_id,
        )
        if not self._eligible(row):
            return None
        ensure_hypoglycemia_shadow_storage(db)
        with db:
            return self._create_candidate(
                db,
                row,
                actor_username=str(actor_username or "system:vitals"),
            )

    def delete_vital_reading(
        self,
        *,
        patient_link_id: int,
        reading_id: int,
        actor_username: str,
    ) -> None:
        """Invalidate an active source event and delete its reading atomically."""
        db = self._db()
        self._reading(
            db,
            patient_link_id=patient_link_id,
            reading_id=reading_id,
        )
        state = self._storage_state(db)
        repo = VitalsRepository(db)
        if state == "NOT_INSTALLED":
            repo.delete_reading(reading_id)
            return
        if state != "READY":
            raise HypoglycemiaShadowSourceIntegrityError(
                "cannot delete source while shadow storage is incomplete"
            )

        shadow = self._joined_shadow(db)
        event_id = self._event_for_reading(db, reading_id)
        with db:
            if event_id:
                event = shadow.get_event(event_id)
                current = event["current"]
                if current["status"] in _INVALIDATABLE_STATES:
                    shadow.adjudicate(
                        event_id,
                        expected_current_version_id=int(current["id"]),
                        decision="ENTERED_IN_ERROR",
                        actor_username=str(actor_username or "system:vitals"),
                        note="Source fasting-glucose reading was deleted.",
                    )
            repo.delete_reading(reading_id, commit=False)
