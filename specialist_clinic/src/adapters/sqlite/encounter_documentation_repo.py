"""Repository for append-only encounter documentation events."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
from typing import Any, Iterable

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.encounter_documentation_schema import (
    ensure_encounter_documentation_storage,
)
from src.common.utils import iran_now


class EncounterDocumentationConflict(RuntimeError):
    pass


class EncounterDocumentationValidationError(ValueError):
    pass


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


def _time(value: datetime | str | None = None) -> str:
    current = value or iran_now()
    if isinstance(current, str):
        parsed = datetime.fromisoformat(current.replace("Z", "+00:00"))
    else:
        parsed = current
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _problems(values: Iterable[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        source = values.splitlines()
    else:
        source = list(values)
    output: list[str] = []
    seen: set[str] = set()
    for value in source:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


class EncounterDocumentationRepository:
    OUTCOMES = frozenset(
        {
            "STABLE_CONTINUE",
            "PLAN_CHANGED",
            "FOLLOWUP_REQUIRED",
            "REFERRED",
            "URGENT_ESCALATION",
            "OTHER",
        }
    )

    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        installed = db.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='care_encounter_document_events'"""
        ).fetchone()
        if not installed:
            if db.in_transaction:
                raise RuntimeError(
                    "encounter documentation storage is missing inside transaction"
                )
            ensure_encounter_documentation_storage(db)
        return db

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def encounter(self, encounter_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM care_encounters WHERE encounter_id=?",
                (str(encounter_id),),
            ).fetchone()
        )

    def requirement(self, encounter_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM care_encounter_document_requirements
                   WHERE encounter_id=?""",
                (str(encounter_id),),
            ).fetchone()
        )

    def require_for_encounter(
        self,
        encounter_id: str,
        *,
        actor_username: str,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        existing = self.requirement(encounter_id)
        if existing:
            return existing
        encounter = self.encounter(encounter_id)
        if not encounter:
            raise LookupError("encounter not found")
        if encounter["accounting_invoice_id"] is None:
            raise EncounterDocumentationValidationError(
                "documented doctor-queue encounter requires accounting invoice"
            )
        created_at = _time()
        payload = {
            "encounter_id": str(encounter["encounter_id"]),
            "journey_id": str(encounter["journey_id"]),
            "patient_link_id": int(encounter["patient_link_id"]),
            "accounting_invoice_id": int(encounter["accounting_invoice_id"]),
            "requirement_status": "REQUIRED",
            "source_code": "DOCTOR_QUEUE_A9",
            "created_at": created_at,
            "created_by": str(actor_username),
        }
        db.execute(
            """INSERT INTO care_encounter_document_requirements
               (encounter_id,journey_id,patient_link_id,accounting_invoice_id,
                requirement_status,source_code,created_at,created_by,content_hash)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (*payload.values(), _hash(payload)),
        )
        if commit:
            db.commit()
        return self.requirement(encounter_id)

    def current_document(self, encounter_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM care_encounter_document_events
                   WHERE encounter_id=?
                   ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (str(encounter_id),),
            ).fetchone()
        )

    def history(self, encounter_id: str) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM care_encounter_document_events
                   WHERE encounter_id=? ORDER BY recorded_at,id""",
                (str(encounter_id),),
            ).fetchall()
        ]

    def append_document(
        self,
        *,
        encounter_id: str,
        event_type: str,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        chief_complaint: str | None = None,
        objective_findings: str | None = None,
        assessment: str | None = None,
        plan: str | None = None,
        followup_instructions: str | None = None,
        problems: Iterable[str] | str | None = None,
        outcome_code: str | None = None,
        amendment_reason: str | None = None,
        authored_at: datetime | str | None = None,
        expected_current_event_id: int | None = None,
        commit: bool = True,
    ) -> dict:
        event = str(event_type or "").strip().upper()
        if event not in {
            "DRAFT_SAVED", "SIGNED", "AMENDED", "ENTERED_IN_ERROR"
        }:
            raise EncounterDocumentationValidationError(
                "invalid encounter document event type"
            )
        key = str(idempotency_key or "").strip()
        actor = str(actor_username or "").strip()
        if not key or not actor:
            raise EncounterDocumentationValidationError(
                "document actor and idempotency key are required"
            )
        outcome = str(outcome_code or "").strip().upper() or None
        if outcome is not None and outcome not in self.OUTCOMES:
            raise EncounterDocumentationValidationError(
                "invalid encounter outcome code"
            )
        assessment_text = _text(assessment)
        plan_text = _text(plan)
        amendment = _text(amendment_reason)
        if event in {"SIGNED", "AMENDED"}:
            if not assessment_text or not plan_text or outcome is None:
                raise EncounterDocumentationValidationError(
                    "signed document requires assessment, plan, and outcome"
                )
        if event in {"AMENDED", "ENTERED_IN_ERROR"} and not amendment:
            raise EncounterDocumentationValidationError(
                "amendment or error reason is required"
            )
        if event == "DRAFT_SAVED":
            outcome = None
            amendment = None
        document_status = (
            "DRAFT" if event == "DRAFT_SAVED"
            else "ENTERED_IN_ERROR" if event == "ENTERED_IN_ERROR"
            else "SIGNED"
        )
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            encounter = self.encounter(encounter_id)
            if not encounter:
                raise LookupError("encounter not found")
            existing = db.execute(
                """SELECT * FROM care_encounter_document_events
                   WHERE idempotency_key=?""",
                (key,),
            ).fetchone()
            if existing:
                existing = dict(existing)
                if (
                    existing["encounter_id"] != str(encounter_id)
                    or existing["event_type"] != event
                ):
                    raise EncounterDocumentationConflict(
                        "document idempotency key belongs to another mutation"
                    )
                if commit:
                    db.commit()
                return existing
            current = self.current_document(encounter_id)
            current_id = int(current["id"]) if current else None
            if expected_current_event_id is not None and current_id != int(
                expected_current_event_id
            ):
                raise EncounterDocumentationConflict(
                    "STALE_ENCOUNTER_DOCUMENT"
                )
            recorded_at = _time()
            authored = _time(authored_at or recorded_at)
            payload = {
                "encounter_id": str(encounter_id),
                "journey_id": str(encounter["journey_id"]),
                "patient_link_id": int(encounter["patient_link_id"]),
                "accounting_invoice_id": int(encounter["accounting_invoice_id"]),
                "event_type": event,
                "document_status": document_status,
                "chief_complaint": _text(chief_complaint),
                "objective_findings": _text(objective_findings),
                "assessment": assessment_text,
                "plan": plan_text,
                "followup_instructions": _text(followup_instructions),
                "problems_json": json.dumps(
                    _problems(problems), ensure_ascii=False
                ),
                "outcome_code": outcome,
                "amendment_reason": amendment,
                "authored_at": authored,
                "recorded_at": recorded_at,
                "actor_user_id": actor_user_id,
                "actor_username": actor,
                "idempotency_key": key,
                "supersedes_event_id": current_id,
            }
            cursor = db.execute(
                """INSERT INTO care_encounter_document_events
                   (encounter_id,journey_id,patient_link_id,accounting_invoice_id,
                    event_type,document_status,chief_complaint,objective_findings,
                    assessment,plan,followup_instructions,problems_json,outcome_code,
                    amendment_reason,authored_at,recorded_at,actor_user_id,
                    actor_username,idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                "SELECT * FROM care_encounter_document_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def current_signed_documents_for_patient(
        self,
        patient_link_id: int,
        *,
        limit: int = 50,
    ) -> list[dict]:
        rows = self._db().execute(
            """SELECT document.*,encounter.encounter_type
               FROM care_encounter_document_events document
               JOIN care_encounters encounter
                 ON encounter.encounter_id=document.encounter_id
               WHERE document.patient_link_id=?
                 AND document.id=(
                     SELECT head.id FROM care_encounter_document_events head
                     WHERE head.encounter_id=document.encounter_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 )
                 AND document.document_status='SIGNED'
               ORDER BY document.authored_at DESC,document.id DESC LIMIT ?""",
            (int(patient_link_id), int(limit)),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["problems"] = json.loads(item.get("problems_json") or "[]")
            output.append(item)
        return output


__all__ = [
    "EncounterDocumentationConflict",
    "EncounterDocumentationRepository",
    "EncounterDocumentationValidationError",
]
