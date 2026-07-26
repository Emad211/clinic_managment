"""Application service for specialist encounters and explicit invoice attribution."""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.adapters import specialist_accounting_revenue
from src.adapters.sqlite.care_journey_repo import (
    CareJourneyConflict,
    CareJourneyRepository,
)
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.common.utils import iran_now


class CareJourneyError(RuntimeError):
    pass


class CareJourneyService:
    def __init__(self, db: sqlite3.Connection | None = None, clock=None):
        self._connection = db
        self.clock = clock or iran_now

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def start_accounting_visit(
        self,
        *,
        patient_link_id: int,
        accounting_invoice_id: int,
        actor_username: str,
        expected_work_date: str | None = None,
        effective_at: datetime | None = None,
        commit: bool = True,
    ) -> dict:
        patient_id = int(patient_link_id)
        invoice_id = int(accounting_invoice_id)
        actor = str(actor_username or "").strip()
        if not actor:
            raise CareJourneyError("actor_username is required")
        enrollment = SpecialistEnrollmentRepository(self._db()).get_by_patient(
            patient_id
        )
        if not enrollment:
            raise CareJourneyError("SPECIALIST_CUTOVER_MISSING")
        invoice = specialist_accounting_revenue.invoice_identity(invoice_id)
        if not invoice:
            raise CareJourneyError("ACCOUNTING_INVOICE_NOT_FOUND")
        if int(invoice["patient_id"]) != int(enrollment["accounting_patient_id"]):
            raise CareJourneyError("ACCOUNTING_IDENTITY_MISMATCH")
        if str(invoice.get("status") or "").lower() != "open":
            raise CareJourneyError("ACCOUNTING_INVOICE_NOT_OPEN")
        if expected_work_date and str(invoice.get("work_date") or "") != str(
            expected_work_date
        ):
            raise CareJourneyError("ACCOUNTING_WORK_DATE_MISMATCH")

        db = self._db()
        owns_transaction = commit
        if owns_transaction:
            if db.in_transaction:
                raise CareJourneyError("CALLER_TRANSACTION_ACTIVE")
            db.execute("BEGIN IMMEDIATE")
        try:
            repository = CareJourneyRepository(db)
            encounter = repository.create_invoice_encounter_once(
                patient_link_id=patient_id,
                accounting_invoice_id=invoice_id,
                actor_username=actor,
                effective_at=effective_at or self.clock(),
                commit=False,
            )
            repository.start_encounter(
                encounter["encounter_id"],
                actor_username=actor,
                effective_at=effective_at or self.clock(),
                commit=False,
            )
            attribution = repository.attribute_invoice_once(
                accounting_invoice_id=invoice_id,
                accounting_patient_id=int(invoice["patient_id"]),
                patient_link_id=patient_id,
                encounter_id=encounter["encounter_id"],
                actor_username=actor,
                reason_code="DOCTOR_QUEUE_STARTED",
                effective_at=effective_at or self.clock(),
                commit=False,
            )
            if owns_transaction:
                db.commit()
            return {"encounter": encounter, "attribution": attribution}
        except Exception:
            if owns_transaction:
                db.rollback()
            raise

    def complete_accounting_visit(
        self,
        *,
        accounting_invoice_id: int,
        actor_username: str,
        note: str | None = None,
        effective_at: datetime | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        owns_transaction = commit
        if owns_transaction:
            if db.in_transaction:
                raise CareJourneyError("CALLER_TRANSACTION_ACTIVE")
            db.execute("BEGIN IMMEDIATE")
        try:
            repository = CareJourneyRepository(db)
            encounter = repository.encounter_for_invoice(accounting_invoice_id)
            if not encounter:
                raise CareJourneyError("SPECIALIST_ENCOUNTER_NOT_FOUND")
            event = repository.complete_encounter(
                encounter["encounter_id"],
                actor_username=actor_username,
                effective_at=effective_at or self.clock(),
                note=note,
                commit=False,
            )
            if owns_transaction:
                db.commit()
            return {"encounter": encounter, "event": event}
        except (CareJourneyConflict, Exception):
            if owns_transaction:
                db.rollback()
            raise
