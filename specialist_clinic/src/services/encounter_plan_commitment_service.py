"""Validation and evidence-governed lifecycle for signed encounter commitments."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.encounter_plan_commitment_repo import (
    EncounterPlanCommitmentConflict,
    EncounterPlanCommitmentRepository,
    EncounterPlanCommitmentValidationError,
)
from src.adapters.sqlite.encounter_plan_commitment_schema import COMMITMENT_TYPES
from src.common.utils import iran_now


COMMITMENT_LABELS = {
    "CALL_CHECK": "تماس و بررسی وضعیت",
    "IN_PERSON_REVIEW": "بازبینی حضوری",
    "LAB_REVIEW": "بررسی نتیجه آزمایش",
    "MEDICATION_REVIEW": "بازبینی دارو",
    "REFERRAL_CHECK": "پیگیری ارجاع",
    "HOME_MONITORING_REVIEW": "بررسی پایش خانگی",
}

EVIDENCE_LABELS = {
    "CONTACT_EVENT": "رویداد تماس ثبت‌شده",
    "APPOINTMENT": "نوبت ثبت‌شده",
    "ENCOUNTER_DOCUMENT": "سند Encounter امضاشده",
    "LAB_RESULT": "نتیجه آزمایش",
    "MEDICATION_EVENT": "رویداد دارویی",
    "VITAL_READING": "اندازه‌گیری ثبت‌شده",
    "MANUAL_VERIFIED": "تأیید مستند دستی",
}

OUTCOME_LABELS = {
    "COMPLETED_AS_PLANNED": "طبق برنامه انجام شد",
    "NO_LONGER_NEEDED": "دیگر لازم نیست",
    "PATIENT_DECLINED": "بیمار نپذیرفت",
    "UNREACHABLE": "دسترسی ممکن نشد",
    "REFERRED_OUT": "به مرکز/پزشک دیگر ارجاع شد",
    "OTHER": "سایر",
}

_ALLOWED_EVIDENCE = {
    "CALL_CHECK": {"CONTACT_EVENT", "MANUAL_VERIFIED"},
    "IN_PERSON_REVIEW": {"APPOINTMENT", "ENCOUNTER_DOCUMENT"},
    "LAB_REVIEW": {"LAB_RESULT", "ENCOUNTER_DOCUMENT"},
    "MEDICATION_REVIEW": {"MEDICATION_EVENT", "ENCOUNTER_DOCUMENT"},
    "REFERRAL_CHECK": {"CONTACT_EVENT", "MANUAL_VERIFIED"},
    "HOME_MONITORING_REVIEW": {"VITAL_READING", "ENCOUNTER_DOCUMENT"},
}


class EncounterPlanCommitmentService:
    def __init__(
        self,
        *,
        db: sqlite3.Connection | None = None,
        repository: EncounterPlanCommitmentRepository | None = None,
        clock=None,
    ):
        self._connection = db
        self.repository = repository or EncounterPlanCommitmentRepository(db)
        self.clock = clock or iran_now

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def normalize_commitments(values: list[dict] | str | None) -> list[dict]:
        if values is None:
            return []
        if isinstance(values, str):
            try:
                decoded = json.loads(values or "[]")
            except json.JSONDecodeError as exc:
                raise EncounterPlanCommitmentValidationError(
                    "commitments JSON is invalid"
                ) from exc
        else:
            decoded = values
        if not isinstance(decoded, list):
            raise EncounterPlanCommitmentValidationError(
                "commitments must be an array"
            )
        output: list[dict] = []
        seen: set[str] = set()
        for raw in decoded:
            if not isinstance(raw, dict):
                raise EncounterPlanCommitmentValidationError(
                    "commitment row must be an object"
                )
            client_key = str(raw.get("client_key") or "").strip()
            kind = str(raw.get("commitment_type") or "").strip().upper()
            instruction = str(raw.get("instruction") or "").strip()
            fulfillment = str(raw.get("fulfillment") or "").strip().lower()
            assigned_to = str(raw.get("assigned_to") or "").strip() or None
            due_raw = raw.get("due_at")
            try:
                due = datetime.fromisoformat(str(due_raw).replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise EncounterPlanCommitmentValidationError(
                    "commitment due time is invalid"
                ) from exc
            if due.tzinfo is not None:
                due = due.replace(tzinfo=None)
            if len(client_key) < 12 or client_key in seen:
                raise EncounterPlanCommitmentValidationError(
                    "commitment client key is missing or duplicated"
                )
            if kind not in COMMITMENT_TYPES:
                raise EncounterPlanCommitmentValidationError(
                    "commitment type is invalid"
                )
            if not instruction:
                raise EncounterPlanCommitmentValidationError(
                    "commitment instruction is required"
                )
            if fulfillment not in {"remote", "in_person", "hybrid"}:
                raise EncounterPlanCommitmentValidationError(
                    "commitment fulfillment is invalid"
                )
            seen.add(client_key)
            output.append(
                {
                    "client_key": client_key,
                    "commitment_type": kind,
                    "instruction": instruction,
                    "fulfillment": fulfillment,
                    "due_at": due.isoformat(sep=" ", timespec="seconds"),
                    "assigned_to": assigned_to,
                }
            )
        return output

    def validate_for_document(
        self,
        *,
        outcome_code: str | None,
        commitments: list[dict] | str | None,
    ) -> list[dict]:
        normalized = self.normalize_commitments(commitments)
        now = self.clock()
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        for item in normalized:
            due = datetime.fromisoformat(item["due_at"])
            if due < now:
                raise EncounterPlanCommitmentValidationError(
                    "commitment due time cannot be in the past"
                )
        outcome = str(outcome_code or "").strip().upper()
        if outcome == "FOLLOWUP_REQUIRED" and not normalized:
            raise EncounterPlanCommitmentValidationError(
                "FOLLOWUP_REQUIRED requires at least one explicit commitment"
            )
        if outcome == "REFERRED" and not any(
            item["commitment_type"] == "REFERRAL_CHECK" for item in normalized
        ):
            raise EncounterPlanCommitmentValidationError(
                "REFERRED requires REFERRAL_CHECK commitment"
            )
        if outcome == "URGENT_ESCALATION":
            urgent_limit = now + timedelta(hours=24)
            urgent = [
                item
                for item in normalized
                if datetime.fromisoformat(item["due_at"]) <= urgent_limit
                and item.get("assigned_to")
            ]
            if not urgent:
                raise EncounterPlanCommitmentValidationError(
                    "URGENT_ESCALATION requires assigned commitment due within 24 hours"
                )
        return normalized

    def materialize_signed_document(
        self,
        *,
        document_event: dict,
        actor_username: str,
        actor_user_id: int | None,
        commit: bool = True,
    ) -> list[dict]:
        commitments = self.validate_for_document(
            outcome_code=document_event.get("outcome_code"),
            commitments=document_event.get("commitments_json") or "[]",
        )
        return self.repository.materialize_signed_document(
            document_event=document_event,
            commitments=commitments,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            commit=commit,
        )

    def _validate_evidence(
        self,
        *,
        task_id: int,
        commitment: dict,
        evidence_type: str,
        evidence_ref: str,
        note: str | None,
    ) -> None:
        db = self._db()
        patient_id = int(commitment["patient_link_id"])
        kind = str(commitment["commitment_type"])
        created_at = str(commitment["created_at"])
        evidence = str(evidence_type or "").strip().upper()
        reference = str(evidence_ref or "").strip()
        if evidence not in _ALLOWED_EVIDENCE[kind]:
            raise EncounterPlanCommitmentValidationError(
                "evidence type is not allowed for commitment type"
            )
        if not reference:
            raise EncounterPlanCommitmentValidationError(
                "completion evidence reference is required"
            )
        if evidence == "CONTACT_EVENT":
            row = db.execute(
                """SELECT 1 FROM followup_contact_events
                   WHERE id=? AND task_id=? AND patient_link_id=?
                     AND datetime(occurred_at)>=datetime(?)""",
                (int(reference), int(task_id), patient_id, created_at),
            ).fetchone()
        elif evidence == "APPOINTMENT":
            row = db.execute(
                """SELECT 1 FROM appointments
                   WHERE id=? AND patient_link_id=? AND status='done'
                     AND datetime(scheduled_at)>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        elif evidence == "ENCOUNTER_DOCUMENT":
            row = db.execute(
                """SELECT 1 FROM care_encounter_document_events
                   WHERE id=? AND patient_link_id=? AND document_status='SIGNED'
                     AND datetime(authored_at)>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        elif evidence == "LAB_RESULT":
            row = db.execute(
                """SELECT 1 FROM lab_results
                   WHERE id=? AND patient_link_id=?
                     AND datetime(taken_at)>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        elif evidence == "MEDICATION_EVENT":
            row = db.execute(
                """SELECT 1 FROM medication_events
                   WHERE id=? AND patient_link_id=?
                     AND datetime(COALESCE(event_date,created_at))>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        elif evidence == "VITAL_READING":
            row = db.execute(
                """SELECT 1 FROM vital_readings
                   WHERE id=? AND patient_link_id=?
                     AND datetime(measured_at)>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        else:
            row = len(str(note or "").strip()) >= 12
        if not row:
            raise EncounterPlanCommitmentValidationError(
                "completion evidence is stale, incomplete, or outside task scope"
            )

    def transition(
        self,
        *,
        task_id: int,
        transition: str,
        expected_current_event_id: int,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        due_at: datetime | str | None = None,
        assigned_to: str | None = None,
        appointment_id: int | None = None,
        evidence_type: str | None = None,
        evidence_ref: str | None = None,
        outcome_code: str | None = None,
        note: str | None = None,
        commit: bool = True,
    ) -> dict:
        current = self.repository.current_for_task(task_id)
        if not current:
            raise LookupError("plan commitment task not found")
        action = str(transition or "").strip().lower()
        event_by_action = {
            "start": "STARTED",
            "assign": "ASSIGNED",
            "reschedule": "RESCHEDULED",
            "schedule": "SCHEDULED",
            "complete": "COMPLETED",
            "cancel": "CANCELLED",
            "error": "ENTERED_IN_ERROR",
        }
        event = event_by_action.get(action)
        if not event:
            raise EncounterPlanCommitmentValidationError(
                "unknown plan commitment transition"
            )
        if event == "ASSIGNED" and not str(assigned_to or "").strip():
            raise EncounterPlanCommitmentValidationError(
                "assigned_to is required"
            )
        if event == "RESCHEDULED":
            if not due_at:
                raise EncounterPlanCommitmentValidationError(
                    "new due time is required"
                )
            parsed_due = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
            if parsed_due.tzinfo is not None:
                parsed_due = parsed_due.replace(tzinfo=None)
            now = self.clock()
            if now.tzinfo is not None:
                now = now.replace(tzinfo=None)
            if parsed_due < now:
                raise EncounterPlanCommitmentValidationError(
                    "new due time cannot be in the past"
                )
        if event == "SCHEDULED":
            if appointment_id is None:
                raise EncounterPlanCommitmentValidationError(
                    "appointment is required for scheduling"
                )
            appointment = self._db().execute(
                """SELECT 1 FROM appointments
                   WHERE id=? AND patient_link_id=? AND status='scheduled'""",
                (int(appointment_id), int(current["patient_link_id"])),
            ).fetchone()
            if not appointment:
                raise EncounterPlanCommitmentValidationError(
                    "scheduled appointment does not belong to commitment patient"
                )
        if event == "COMPLETED":
            if str(outcome_code or "").strip().upper() not in OUTCOME_LABELS:
                raise EncounterPlanCommitmentValidationError(
                    "completion outcome is required"
                )
            self._validate_evidence(
                task_id=task_id,
                commitment=current,
                evidence_type=evidence_type or "",
                evidence_ref=evidence_ref or "",
                note=note,
            )
        if event in {"CANCELLED", "ENTERED_IN_ERROR"} and not str(note or "").strip():
            raise EncounterPlanCommitmentValidationError(
                "cancellation/error note is required"
            )
        return self.repository.append_event(
            task_id=task_id,
            event_type=event,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            expected_current_event_id=expected_current_event_id,
            due_at=due_at,
            assigned_to=assigned_to,
            appointment_id=appointment_id,
            evidence_type=evidence_type,
            evidence_ref=evidence_ref,
            outcome_code=outcome_code,
            note=note,
            commit=commit,
        )


__all__ = [
    "COMMITMENT_LABELS",
    "EVIDENCE_LABELS",
    "OUTCOME_LABELS",
    "EncounterPlanCommitmentConflict",
    "EncounterPlanCommitmentService",
    "EncounterPlanCommitmentValidationError",
]
