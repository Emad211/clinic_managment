"""Atomic projections and append-only writes for the clinical care loop."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.clinical_care_loop_schema import (
    ensure_clinical_care_loop_storage,
)
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


_NON_TERMINAL = {"OPEN", "ASSIGNED", "SCHEDULED", "IN_PROGRESS", "DEFERRED"}
_EVENT_STATUS = {
    "ASSIGNED": "ASSIGNED",
    "SCHEDULED": "SCHEDULED",
    "STARTED": "IN_PROGRESS",
    "DEFERRED": "DEFERRED",
    "COMPLETED": "COMPLETED",
    "NOT_DONE": "NOT_DONE",
    "ENTERED_IN_ERROR": "ENTERED_IN_ERROR",
}


class ClinicalCareLoopConflict(RuntimeError):
    """The task head changed after the user loaded the worklist."""


class ClinicalCareLoopValidationError(ValueError):
    pass


def _now_text(value: datetime | None = None) -> str:
    current = value or iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.isoformat(sep=" ", timespec="seconds")


def _datetime_text(value: datetime | date | str | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _now_text(value)
    if isinstance(value, date):
        return f"{value.isoformat()} 00:00:00"
    text = str(value).strip()
    if len(text) == 10:
        text = f"{text} 00:00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ClinicalCareLoopValidationError("invalid clinical task datetime") from exc
    return text


def _clean(value, *, limit: int = 2000) -> str | None:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    if len(text) > limit:
        raise ClinicalCareLoopValidationError(f"text exceeds {limit} characters")
    return text


def _canonical_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class ClinicalCareLoopRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self):
        db = self._connection or get_db()
        ensure_clinical_care_loop_storage(db)
        return db

    @staticmethod
    def _task(db, task_id: int):
        row = db.execute(
            """SELECT task.*, patient.full_name AS patient_name,
                      patient.phone_number, patient.national_id
               FROM followup_tasks task
               JOIN patient_links patient ON patient.id=task.patient_link_id
               WHERE task.id=? AND task.source_engine='clinical_v2'""",
            (task_id,),
        ).fetchone()
        if not row:
            raise LookupError("clinical follow-up task not found")
        return row

    @staticmethod
    def _head(db, task_id: int):
        return db.execute(
            """SELECT event.*
               FROM clinical_task_events event
               WHERE event.task_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_task_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1""",
            (task_id,),
        ).fetchone()

    @staticmethod
    def latest_decision_event_id(db, recommendation_event_id: int) -> int | None:
        row = db.execute(
            """SELECT id FROM clinical_decision_events
               WHERE recommendation_event_id=?
               ORDER BY occurred_at DESC, id DESC LIMIT 1""",
            (recommendation_event_id,),
        ).fetchone()
        return int(row["id"]) if row else None

    @staticmethod
    def create_initial_event(
        db: sqlite3.Connection,
        *,
        task_id: int,
        due_at: str | None,
        actor_username: str,
        actor_user_id: int | None = None,
        recorded_at: datetime | None = None,
    ) -> int:
        recorded = _now_text(recorded_at)
        due = _datetime_text(due_at)
        payload = {
            "task_id": int(task_id),
            "event_type": "CREATED",
            "status": "OPEN",
            "assigned_to": None,
            "appointment_id": None,
            "due_at": due,
            "disposition_code": None,
            "outcome_event_id": None,
            "effective_at": recorded,
            "recorded_at": recorded,
            "supersedes_event_id": None,
        }
        cursor = db.execute(
            """INSERT INTO clinical_task_events
               (task_id, event_type, status, due_at, effective_at, recorded_at,
                actor_user_id, actor_username, content_hash)
               VALUES (?, 'CREATED', 'OPEN', ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                due,
                recorded,
                recorded,
                actor_user_id,
                actor_username,
                _canonical_hash(payload),
            ),
        )
        return int(cursor.lastrowid)

    def current_task(self, task_id: int) -> dict:
        db = self._db()
        task = dict(self._task(db, task_id))
        head = self._head(db, task_id)
        if not head:
            raise RuntimeError("clinical task has no lifecycle event")
        task["current_event"] = dict(head)
        task["current_event_id"] = int(head["id"])
        task["current_status"] = str(head["status"])
        outcomes = db.execute(
            """SELECT * FROM clinical_outcome_events
               WHERE task_id=? ORDER BY recorded_at DESC, id DESC""",
            (task_id,),
        ).fetchall()
        task["outcomes"] = [dict(row) for row in outcomes]
        task["latest_outcome_event_id"] = (
            int(outcomes[0]["id"]) if outcomes else None
        )
        return task

    def list_current(
        self,
        *,
        reason: str | None = None,
        query: str | None = None,
        patient_link_id: int | None = None,
        include_terminal: bool = False,
    ) -> list[dict]:
        db = self._db()
        sql = """SELECT task.*, patient.full_name AS patient_name,
                        patient.phone_number, patient.national_id,
                        event.id AS current_event_id,
                        event.status AS current_status,
                        event.assigned_to AS current_assigned_to,
                        event.appointment_id AS current_appointment_id,
                        event.due_at AS current_due_at,
                        event.disposition_code AS current_disposition_code,
                        event.outcome_event_id AS completion_outcome_event_id,
                        event.recorded_at AS current_recorded_at,
                        (
                            SELECT outcome.id FROM clinical_outcome_events outcome
                            WHERE outcome.task_id=task.id
                            ORDER BY outcome.recorded_at DESC, outcome.id DESC LIMIT 1
                        ) AS latest_outcome_event_id
                 FROM followup_tasks task
                 JOIN patient_links patient ON patient.id=task.patient_link_id
                 JOIN clinical_task_events event ON event.task_id=task.id
                 WHERE task.source_engine='clinical_v2'
                   AND NOT EXISTS (
                       SELECT 1 FROM clinical_task_events child
                       WHERE child.supersedes_event_id=event.id
                   )"""
        params: list[Any] = []
        if not include_terminal:
            sql += " AND event.status IN ('OPEN','ASSIGNED','SCHEDULED','IN_PROGRESS','DEFERRED')"
        if reason:
            sql += " AND task.reason=?"
            params.append(reason)
        if patient_link_id is not None:
            sql += " AND task.patient_link_id=?"
            params.append(int(patient_link_id))
        if query:
            like = f"%{query.strip()}%"
            sql += " AND (patient.national_id LIKE ? OR patient.full_name LIKE ? OR patient.phone_number LIKE ?)"
            params.extend((like, like, like))
        sql += " ORDER BY COALESCE(event.due_at, task.due_date) IS NULL, COALESCE(event.due_at, task.due_date), task.id DESC"
        return [dict(row) for row in db.execute(sql, params).fetchall()]

    def record_outcome(
        self,
        task_id: int,
        *,
        outcome_type: str,
        actor_username: str,
        actor_user_id: int | None = None,
        fact_key: str | None = None,
        value: Any = None,
        unit: str | None = None,
        verification: str = "CONFIRMED",
        observed_at: datetime | str | None = None,
        source_system: str = "clinician",
        source_record_id: str | None = None,
        note: str | None = None,
        recorded_at: datetime | None = None,
    ) -> dict:
        db = self._db()
        actor = _clean(actor_username, limit=200)
        if not actor:
            raise ClinicalCareLoopValidationError("actor_username is required")
        kind = str(outcome_type or "").strip().upper()
        if kind not in {
            "OBSERVATION",
            "PATIENT_REPORTED",
            "ENCOUNTER_COMPLETED",
            "PROCEDURE_COMPLETED",
            "LAB_COMPLETED",
            "OTHER",
        }:
            raise ClinicalCareLoopValidationError("invalid outcome_type")
        verification = str(verification or "").strip().upper()
        if verification not in {"CONFIRMED", "PROVISIONAL", "UNVERIFIED"}:
            raise ClinicalCareLoopValidationError("invalid outcome verification")
        recorded = _now_text(recorded_at)
        observed = _datetime_text(observed_at) or recorded
        value_json = (
            None
            if value is None or value == ""
            else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        payload = {
            "task_id": int(task_id),
            "outcome_type": kind,
            "fact_key": _clean(fact_key, limit=200),
            "value": value,
            "unit": _clean(unit, limit=80),
            "verification": verification,
            "observed_at": observed,
            "recorded_at": recorded,
            "source_system": _clean(source_system, limit=120),
            "source_record_id": _clean(source_record_id, limit=200),
            "note": _clean(note),
        }
        db.execute("BEGIN IMMEDIATE")
        try:
            self._task(db, task_id)
            head = self._head(db, task_id)
            if not head or str(head["status"]) not in _NON_TERMINAL:
                raise ClinicalCareLoopValidationError(
                    "outcome can only be added to a non-terminal clinical task"
                )
            cursor = db.execute(
                """INSERT INTO clinical_outcome_events
                   (task_id, outcome_type, fact_key, value_json, unit,
                    verification, observed_at, recorded_at, source_system,
                    source_record_id, note, actor_user_id, actor_username,
                    content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    kind,
                    payload["fact_key"],
                    value_json,
                    payload["unit"],
                    verification,
                    observed,
                    recorded,
                    payload["source_system"],
                    payload["source_record_id"],
                    payload["note"],
                    actor_user_id,
                    actor,
                    _canonical_hash(payload),
                ),
            )
            row = db.execute(
                "SELECT * FROM clinical_outcome_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise

    def append_task_event(
        self,
        task_id: int,
        *,
        event_type: str,
        expected_current_event_id: int,
        actor_username: str,
        actor_user_id: int | None = None,
        assigned_to: str | None = None,
        appointment_id: int | None = None,
        due_at: datetime | date | str | None = None,
        disposition_code: str | None = None,
        outcome_event_id: int | None = None,
        note: str | None = None,
        effective_at: datetime | None = None,
        recorded_at: datetime | None = None,
    ) -> dict:
        db = self._db()
        actor = _clean(actor_username, limit=200)
        if not actor:
            raise ClinicalCareLoopValidationError("actor_username is required")
        kind = str(event_type or "").strip().upper()
        status = _EVENT_STATUS.get(kind)
        if status is None:
            raise ClinicalCareLoopValidationError("invalid clinical task event")
        recorded = _now_text(recorded_at)
        effective = _now_text(effective_at or recorded_at)

        db.execute("BEGIN IMMEDIATE")
        try:
            self._task(db, task_id)
            head = self._head(db, task_id)
            if not head or int(head["id"]) != int(expected_current_event_id):
                raise ClinicalCareLoopConflict("clinical task changed after load")
            current_assignee = _clean(assigned_to, limit=200)
            if current_assignee is None:
                current_assignee = head["assigned_to"]
            current_appointment = (
                int(appointment_id)
                if appointment_id is not None
                else head["appointment_id"]
            )
            current_due = _datetime_text(due_at)
            if current_due is None:
                current_due = head["due_at"]
            disposition = _clean(disposition_code, limit=80)
            if disposition:
                disposition = disposition.upper()
            note_text = _clean(note)
            payload = {
                "task_id": int(task_id),
                "event_type": kind,
                "status": status,
                "assigned_to": current_assignee,
                "appointment_id": current_appointment,
                "due_at": current_due,
                "disposition_code": disposition,
                "outcome_event_id": outcome_event_id,
                "effective_at": effective,
                "recorded_at": recorded,
                "supersedes_event_id": int(head["id"]),
                "note": note_text,
            }
            cursor = db.execute(
                """INSERT INTO clinical_task_events
                   (task_id, event_type, status, assigned_to, appointment_id,
                    due_at, disposition_code, outcome_event_id, note,
                    effective_at, recorded_at, actor_user_id, actor_username,
                    supersedes_event_id, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    kind,
                    status,
                    current_assignee,
                    current_appointment,
                    current_due,
                    disposition,
                    outcome_event_id,
                    note_text,
                    effective,
                    recorded,
                    actor_user_id,
                    actor,
                    int(head["id"]),
                    _canonical_hash(payload),
                ),
            )
            row = db.execute(
                "SELECT * FROM clinical_task_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise
