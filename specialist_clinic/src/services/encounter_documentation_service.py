"""Atomic doctor-queue documentation, signing, and encounter completion."""
from __future__ import annotations

import sqlite3
from typing import Any

from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
from src.adapters.sqlite.encounter_documentation_repo import (
    EncounterDocumentationConflict,
    EncounterDocumentationRepository,
    EncounterDocumentationValidationError,
)
from src.adapters.sqlite.vitals_repo import VitalsRepository
from src.services.care_journey_service import CareJourneyService
from src.services.encounter_plan_commitment_service import (
    EncounterPlanCommitmentService,
)


class EncounterDocumentationStateError(RuntimeError):
    pass


class EncounterDocumentationService:
    def __init__(
        self,
        *,
        db: sqlite3.Connection | None = None,
        repository: EncounterDocumentationRepository | None = None,
    ):
        self._connection = db
        self.repository = repository or EncounterDocumentationRepository(db)

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def _active_event(db: sqlite3.Connection, encounter_id: str) -> dict:
        row = db.execute(
            """SELECT * FROM care_encounter_events
               WHERE encounter_id=? ORDER BY recorded_at DESC,id DESC LIMIT 1""",
            (str(encounter_id),),
        ).fetchone()
        if not row or row["event_type"] != "STARTED":
            raise EncounterDocumentationStateError(
                "ENCOUNTER_NOT_ACTIVE_FOR_DOCUMENTATION"
            )
        return dict(row)

    @staticmethod
    def _completed_event(db: sqlite3.Connection, encounter_id: str) -> dict:
        row = db.execute(
            """SELECT * FROM care_encounter_events
               WHERE encounter_id=? ORDER BY recorded_at DESC,id DESC LIMIT 1""",
            (str(encounter_id),),
        ).fetchone()
        if not row or row["event_type"] != "COMPLETED":
            raise EncounterDocumentationStateError(
                "ENCOUNTER_NOT_COMPLETED_FOR_AMENDMENT"
            )
        return dict(row)

    def require_documentation(
        self,
        encounter_id: str,
        *,
        actor_username: str,
        commit: bool = True,
    ) -> dict:
        return self.repository.require_for_encounter(
            encounter_id,
            actor_username=actor_username,
            commit=commit,
        )

    @staticmethod
    def _record_vitals(
        db: sqlite3.Connection,
        *,
        patient_link_id: int,
        readings: list[tuple[str, float, str | None]],
        measured_at: str | None,
        actor_username: str,
    ) -> list[int]:
        repository = VitalsRepository(db)
        ids: list[int] = []
        for vital_type, value, unit in readings:
            ids.append(
                repository.add_reading(
                    int(patient_link_id),
                    vtype=vital_type,
                    value=float(value),
                    unit=unit,
                    measured_at=measured_at,
                    recorded_by=actor_username,
                    commit=False,
                )
            )
        return ids

    def save_draft_with_vitals(
        self,
        *,
        visit_snapshot: dict,
        document: dict[str, Any],
        readings: list[tuple[str, float, str | None]],
        measured_at: str | None,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        expected_current_event_id: int | None,
    ) -> dict:
        db = self._db()
        if db.in_transaction:
            raise EncounterDocumentationStateError("CALLER_TRANSACTION_ACTIVE")
        db.execute("BEGIN IMMEDIATE")
        try:
            documentation = EncounterDocumentationRepository(db)
            existing = documentation.document_by_idempotency(idempotency_key)
            if existing:
                db.commit()
                return {"document": existing, "vital_ids": []}
            self._active_event(db, visit_snapshot["encounter_id"])
            requirement = documentation.requirement(
                visit_snapshot["encounter_id"]
            )
            if not requirement or requirement["requirement_status"] != "REQUIRED":
                raise EncounterDocumentationStateError(
                    "ENCOUNTER_DOCUMENTATION_NOT_REQUIRED"
                )
            commitments = EncounterPlanCommitmentService(
                db=db
            ).validate_for_document(
                outcome_code=None,
                commitments=document.get("commitments"),
            )
            vital_ids = self._record_vitals(
                db,
                patient_link_id=int(visit_snapshot["patient_link_id"]),
                readings=readings,
                measured_at=measured_at,
                actor_username=actor_username,
            )
            event = EncounterDocumentationRepository(db).append_document(
                encounter_id=visit_snapshot["encounter_id"],
                event_type="DRAFT_SAVED",
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
                chief_complaint=document.get("chief_complaint"),
                objective_findings=document.get("objective_findings"),
                assessment=document.get("assessment"),
                plan=document.get("plan"),
                followup_instructions=document.get("followup_instructions"),
                problems=document.get("problems"),
                commitments=commitments,
                expected_current_event_id=expected_current_event_id,
                commit=False,
            )
            db.commit()
            return {"document": event, "vital_ids": vital_ids}
        except Exception:
            db.rollback()
            raise

    def sign_and_complete(
        self,
        *,
        visit_snapshot: dict,
        document: dict[str, Any],
        readings: list[tuple[str, float, str | None]],
        measured_at: str | None,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        expected_current_event_id: int | None,
    ) -> dict:
        db = self._db()
        if db.in_transaction:
            raise EncounterDocumentationStateError("CALLER_TRANSACTION_ACTIVE")
        db.execute("BEGIN IMMEDIATE")
        try:
            documentation = EncounterDocumentationRepository(db)
            existing = documentation.document_by_idempotency(idempotency_key)
            if existing:
                encounter = CareJourneyRepository(db).encounter(
                    visit_snapshot["encounter_id"]
                )
                db.commit()
                return {
                    "document": existing,
                    "vital_ids": [],
                    "encounter": encounter,
                }
            self._active_event(db, visit_snapshot["encounter_id"])
            requirement = documentation.requirement(
                visit_snapshot["encounter_id"]
            )
            if not requirement or requirement["requirement_status"] != "REQUIRED":
                raise EncounterDocumentationStateError(
                    "ENCOUNTER_DOCUMENTATION_NOT_REQUIRED"
                )
            commitments = EncounterPlanCommitmentService(
                db=db
            ).validate_for_document(
                outcome_code=document.get("outcome_code"),
                commitments=document.get("commitments"),
            )
            vital_ids = self._record_vitals(
                db,
                patient_link_id=int(visit_snapshot["patient_link_id"]),
                readings=readings,
                measured_at=measured_at,
                actor_username=actor_username,
            )
            signed = EncounterDocumentationRepository(db).append_document(
                encounter_id=visit_snapshot["encounter_id"],
                event_type="SIGNED",
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
                chief_complaint=document.get("chief_complaint"),
                objective_findings=document.get("objective_findings"),
                assessment=document.get("assessment"),
                plan=document.get("plan"),
                followup_instructions=document.get("followup_instructions"),
                problems=document.get("problems"),
                commitments=commitments,
                outcome_code=document.get("outcome_code"),
                expected_current_event_id=expected_current_event_id,
                commit=False,
            )
            materialized = EncounterPlanCommitmentService(
                db=db
            ).materialize_signed_document(
                document_event=signed,
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                commit=False,
            )
            DoctorQueueRepository(db).mark_done(
                accounting_invoice_id=visit_snapshot["accounting_invoice_id"],
                patient_link_id=visit_snapshot["patient_link_id"],
                national_id=visit_snapshot.get("national_id"),
                full_name=visit_snapshot.get("full_name") or "—",
                work_date=visit_snapshot["work_date"],
                done_by=actor_username,
                notes=str(document.get("assessment") or "").strip(),
                commit=False,
            )
            completed = CareJourneyService(db=db).complete_accounting_visit(
                accounting_invoice_id=visit_snapshot["accounting_invoice_id"],
                actor_username=actor_username,
                note=str(document.get("plan") or "").strip(),
                commit=False,
            )
            db.commit()
            return {
                "document": signed,
                "vital_ids": vital_ids,
                "encounter": completed["encounter"],
                "commitments": materialized,
            }
        except Exception:
            db.rollback()
            raise

    def amend_completed_document(
        self,
        *,
        encounter_id: str,
        document: dict[str, Any],
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        expected_current_event_id: int,
        amendment_reason: str,
    ) -> dict:
        db = self._db()
        if db.in_transaction:
            raise EncounterDocumentationStateError("CALLER_TRANSACTION_ACTIVE")
        db.execute("BEGIN IMMEDIATE")
        try:
            self._completed_event(db, encounter_id)
            documentation = EncounterDocumentationRepository(db)
            current = documentation.current_document(encounter_id)
            if not current:
                raise LookupError("encounter document not found")
            event = documentation.append_document(
                encounter_id=encounter_id,
                event_type="AMENDED",
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                idempotency_key=idempotency_key,
                chief_complaint=document.get("chief_complaint"),
                objective_findings=document.get("objective_findings"),
                assessment=document.get("assessment"),
                plan=document.get("plan"),
                followup_instructions=document.get("followup_instructions"),
                problems=document.get("problems"),
                commitments=current.get("commitments_json") or "[]",
                outcome_code=document.get("outcome_code"),
                amendment_reason=amendment_reason,
                expected_current_event_id=expected_current_event_id,
                commit=False,
            )
            db.commit()
            return event
        except Exception:
            db.rollback()
            raise


__all__ = [
    "EncounterDocumentationConflict",
    "EncounterDocumentationService",
    "EncounterDocumentationStateError",
    "EncounterDocumentationValidationError",
]
