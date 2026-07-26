"""Idempotent red-flag alert projection and append-only lifecycle transitions."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.clinical_alert_schema import ensure_clinical_alert_storage
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


ACK_SLA_MINUTES = {
    "WARN": 24 * 60,
    "URGENT": 60,
    "CRITICAL": 15,
}
_EVENT_STATUS = {
    "ACKNOWLEDGED": "ACKNOWLEDGED",
    "ESCALATED": "ESCALATED",
    "RESOLVED": "RESOLVED",
    "ENTERED_IN_ERROR": "ENTERED_IN_ERROR",
}
_NON_TERMINAL = {"OPEN", "ACKNOWLEDGED", "ESCALATED"}


class ClinicalAlertConflict(RuntimeError):
    pass


class ClinicalAlertValidationError(ValueError):
    pass


def _clean(value, *, limit: int = 2000) -> str | None:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    if len(text) > limit:
        raise ClinicalAlertValidationError(f"text exceeds {limit} characters")
    return text


def _time(value: datetime | str | None = None) -> str:
    current = value or iran_now()
    if isinstance(current, str):
        parsed = datetime.fromisoformat(current.replace("Z", "+00:00"))
    else:
        parsed = current
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class ClinicalAlertRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        db = get_db()
        ensure_clinical_alert_storage(db)
        return db

    @staticmethod
    def _head(db: sqlite3.Connection, alert_id: int):
        return db.execute(
            """SELECT event.* FROM clinical_alert_events event
               WHERE event.alert_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_alert_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1""",
            (int(alert_id),),
        ).fetchone()

    def create_once(
        self,
        *,
        patient_link_id: int,
        source_run_id: str,
        source_recommendation_event_id: int,
        rule_code: str,
        action_type: str,
        severity: str,
        title_fa: str,
        message_fa: str,
        created_by: str,
        created_at: datetime | str | None = None,
    ) -> tuple[int, bool]:
        db = self._db()
        existing = db.execute(
            "SELECT id FROM clinical_alerts WHERE source_recommendation_event_id=?",
            (int(source_recommendation_event_id),),
        ).fetchone()
        if existing:
            return int(existing["id"]), False

        action = str(action_type or "").strip().lower()
        if action not in {"redflag", "safety_alert"}:
            raise ClinicalAlertValidationError("alert action_type is not safety-related")
        level = str(severity or "").strip().upper()
        if level not in ACK_SLA_MINUTES:
            raise ClinicalAlertValidationError("alert severity requires an acknowledgement SLA")
        actor = _clean(created_by, limit=200)
        title = _clean(title_fa, limit=500)
        message = _clean(message_fa)
        code = _clean(rule_code, limit=200)
        if not all((actor, title, message, code)):
            raise ClinicalAlertValidationError("alert identity, title, message and actor are required")
        created = _time(created_at)
        due = _time(datetime.fromisoformat(created) + timedelta(minutes=ACK_SLA_MINUTES[level]))
        body = {
            "patient_link_id": int(patient_link_id),
            "source_run_id": str(source_run_id),
            "source_recommendation_event_id": int(source_recommendation_event_id),
            "rule_code": code,
            "action_type": action,
            "severity": level,
            "title_fa": title,
            "message_fa": message,
            "acknowledgement_due_at": due,
            "created_at": created,
            "created_by": actor,
        }
        db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute(
                "SELECT id FROM clinical_alerts WHERE source_recommendation_event_id=?",
                (int(source_recommendation_event_id),),
            ).fetchone()
            if existing:
                db.commit()
                return int(existing["id"]), False
            cursor = db.execute(
                """INSERT INTO clinical_alerts
                   (patient_link_id, source_run_id, source_recommendation_event_id,
                    rule_code, action_type, severity, title_fa, message_fa,
                    acknowledgement_due_at, created_at, created_by, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(patient_link_id), str(source_run_id),
                    int(source_recommendation_event_id), code, action, level,
                    title, message, due, created, actor, _hash(body),
                ),
            )
            alert_id = int(cursor.lastrowid)
            event_body = {
                "alert_id": alert_id,
                "event_type": "CREATED",
                "status": "OPEN",
                "assigned_to": None,
                "note": None,
                "decision_event_id": None,
                "effective_at": created,
                "recorded_at": created,
                "actor_username": actor,
                "supersedes_event_id": None,
            }
            db.execute(
                """INSERT INTO clinical_alert_events
                   (alert_id, event_type, status, effective_at, recorded_at,
                    actor_username, content_hash)
                   VALUES (?, 'CREATED', 'OPEN', ?, ?, ?, ?)""",
                (alert_id, created, created, actor, _hash(event_body)),
            )
            db.commit()
            return alert_id, True
        except sqlite3.IntegrityError:
            db.rollback()
            existing = db.execute(
                "SELECT id FROM clinical_alerts WHERE source_recommendation_event_id=?",
                (int(source_recommendation_event_id),),
            ).fetchone()
            if existing:
                return int(existing["id"]), False
            raise
        except Exception:
            db.rollback()
            raise

    def current(self, alert_id: int) -> dict:
        db = self._db()
        row = db.execute(
            """SELECT alert.*, patient.full_name AS patient_name,
                      patient.phone_number, patient.national_id
               FROM clinical_alerts alert
               JOIN patient_links patient ON patient.id=alert.patient_link_id
               WHERE alert.id=?""",
            (int(alert_id),),
        ).fetchone()
        if not row:
            raise LookupError("clinical alert not found")
        head = self._head(db, alert_id)
        if not head:
            raise RuntimeError("clinical alert has no lifecycle event")
        result = dict(row)
        result["current_event"] = dict(head)
        result["current_event_id"] = int(head["id"])
        result["current_status"] = str(head["status"])
        result["current_assigned_to"] = head["assigned_to"]
        result["current_note"] = head["note"]
        result["current_recorded_at"] = head["recorded_at"]
        result["decision_event_id"] = head["decision_event_id"]
        return result

    def list_current(
        self,
        *,
        include_terminal: bool = False,
        patient_link_id: int | None = None,
    ) -> list[dict]:
        db = self._db()
        sql = """SELECT alert.*, patient.full_name AS patient_name,
                        patient.phone_number, patient.national_id,
                        event.id AS current_event_id,
                        event.status AS current_status,
                        event.assigned_to AS current_assigned_to,
                        event.note AS current_note,
                        event.decision_event_id,
                        event.recorded_at AS current_recorded_at
                 FROM clinical_alerts alert
                 JOIN patient_links patient ON patient.id=alert.patient_link_id
                 JOIN clinical_alert_events event ON event.alert_id=alert.id
                 WHERE NOT EXISTS (
                     SELECT 1 FROM clinical_alert_events child
                     WHERE child.supersedes_event_id=event.id
                 )"""
        params: list[Any] = []
        if not include_terminal:
            sql += " AND event.status IN ('OPEN','ACKNOWLEDGED','ESCALATED')"
        if patient_link_id is not None:
            sql += " AND alert.patient_link_id=?"
            params.append(int(patient_link_id))
        sql += " ORDER BY CASE alert.severity WHEN 'CRITICAL' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END, alert.acknowledgement_due_at, alert.id DESC"
        return [dict(row) for row in db.execute(sql, params).fetchall()]

    def append_event(
        self,
        alert_id: int,
        *,
        event_type: str,
        expected_current_event_id: int,
        actor_username: str,
        actor_user_id: int | None = None,
        assigned_to: str | None = None,
        note: str | None = None,
        decision_event_id: int | None = None,
        recorded_at: datetime | str | None = None,
    ) -> dict:
        db = self._db()
        kind = str(event_type or "").strip().upper()
        status = _EVENT_STATUS.get(kind)
        if status is None:
            raise ClinicalAlertValidationError("invalid clinical alert transition")
        actor = _clean(actor_username, limit=200)
        if not actor:
            raise ClinicalAlertValidationError("actor_username is required")
        assignee = _clean(assigned_to, limit=200)
        note_text = _clean(note)
        recorded = _time(recorded_at)
        db.execute("BEGIN IMMEDIATE")
        try:
            head = self._head(db, alert_id)
            if not head or int(head["id"]) != int(expected_current_event_id):
                raise ClinicalAlertConflict("clinical alert changed after load")
            if str(head["status"]) not in _NON_TERMINAL:
                raise ClinicalAlertValidationError("terminal clinical alert cannot transition")
            if assignee is None:
                assignee = head["assigned_to"]
            if kind == "ACKNOWLEDGED" and assignee is None:
                assignee = actor
            body = {
                "alert_id": int(alert_id),
                "event_type": kind,
                "status": status,
                "assigned_to": assignee,
                "note": note_text,
                "decision_event_id": decision_event_id,
                "effective_at": recorded,
                "recorded_at": recorded,
                "actor_username": actor,
                "supersedes_event_id": int(head["id"]),
            }
            cursor = db.execute(
                """INSERT INTO clinical_alert_events
                   (alert_id, event_type, status, assigned_to, note,
                    decision_event_id, effective_at, recorded_at, actor_user_id,
                    actor_username, supersedes_event_id, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(alert_id), kind, status, assignee, note_text,
                    decision_event_id, recorded, recorded, actor_user_id,
                    actor, int(head["id"]), _hash(body),
                ),
            )
            row = db.execute(
                "SELECT * FROM clinical_alert_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            db.commit()
            return dict(row)
        except Exception:
            db.rollback()
            raise

    def escalate_due(
        self,
        *,
        actor_username: str = "system:clinical-alert-escalation",
        now: datetime | str | None = None,
    ) -> list[int]:
        current = _time(now)
        due = self._db().execute(
            """SELECT alert.id, event.id AS current_event_id
               FROM clinical_alerts alert
               JOIN clinical_alert_events event ON event.alert_id=alert.id
               WHERE event.status='OPEN'
                 AND datetime(alert.acknowledgement_due_at) < datetime(?)
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_alert_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY alert.acknowledgement_due_at, alert.id""",
            (current,),
        ).fetchall()
        escalated: list[int] = []
        for row in due:
            try:
                self.append_event(
                    int(row["id"]),
                    event_type="ESCALATED",
                    expected_current_event_id=int(row["current_event_id"]),
                    actor_username=actor_username,
                    note="مهلت مشاهدهٔ هشدار سپری شد؛ escalation عملیاتی ثبت شد.",
                    recorded_at=current,
                )
                escalated.append(int(row["id"]))
            except ClinicalAlertConflict:
                continue
        return escalated
