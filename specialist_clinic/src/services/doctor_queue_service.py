"""Physician queue with canonical accounting identity and specialist journeys.

Accounting is always read-only. Posted hidden fields are never trusted for patient,
invoice, work-date, or revenue attribution.
"""
from __future__ import annotations

from src.adapters import accounting_bridge, specialist_accounting_revenue
from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.common.utils import iran_now, today_str
from src.services.care_journey_service import CareJourneyService


class DoctorQueueIdentityError(RuntimeError):
    pass


class DoctorQueueService:
    def __init__(self, *, work_date_provider=None):
        self.repo = DoctorQueueRepository()
        self.enrollments = SpecialistEnrollmentRepository()
        self.work_date_provider = work_date_provider or today_str

    def queue(self, work_date: str | None = None) -> dict:
        work_day = work_date or self.work_date_provider()
        opens = accounting_bridge.fetch_open_visit_invoices(work_date=work_day)
        log = self.repo.log_map(work_day)
        waiting, done = [], []
        for invoice in opens:
            accounting_patient_id = int(invoice["patient_id"])
            enrollment = self.enrollments.get_by_accounting_patient(
                accounting_patient_id
            )
            entry = log.get(int(invoice["invoice_id"])) or {}
            status = entry.get("status", "waiting")
            row = {
                "invoice_id": int(invoice["invoice_id"]),
                "accounting_patient_id": accounting_patient_id,
                "national_id": (invoice.get("national_id") or "").strip() or None,
                "full_name": invoice.get("full_name") or "—",
                "phone_number": invoice.get("phone_number"),
                "opened_at": invoice.get("opened_at"),
                "work_date": invoice.get("work_date") or work_day,
                "status": status,
                "patient_link_id": (
                    int(enrollment["patient_link_id"]) if enrollment else None
                ),
                "enrolled": bool(enrollment),
                "done_by": entry.get("done_by"),
            }
            (done if status == "done" else waiting).append(row)
        return {"waiting": waiting, "done": done, "work_date": work_day}

    def canonical_snapshot(self, accounting_invoice_id: int) -> dict:
        try:
            invoice = specialist_accounting_revenue.invoice_identity(
                int(accounting_invoice_id)
            )
        except (
            specialist_accounting_revenue.AccountingRevenueUnavailable,
            specialist_accounting_revenue.AccountingRevenueSchemaError,
        ) as exc:
            raise DoctorQueueIdentityError("ACCOUNTING_BRIDGE_UNAVAILABLE") from exc
        if not invoice:
            raise DoctorQueueIdentityError("ACCOUNTING_INVOICE_NOT_FOUND")
        accounting_patient_id = int(invoice["patient_id"])
        patient = accounting_bridge.get_patient_by_id(accounting_patient_id) or {}
        enrollment = self.enrollments.get_by_accounting_patient(
            accounting_patient_id
        )
        return {
            "accounting_invoice_id": int(invoice["invoice_id"]),
            "accounting_patient_id": accounting_patient_id,
            "patient_link_id": (
                int(enrollment["patient_link_id"]) if enrollment else None
            ),
            "national_id": (patient.get("national_id") or "").strip() or None,
            "full_name": patient.get("full_name") or "—",
            "phone_number": patient.get("phone_number"),
            "work_date": invoice.get("work_date") or today_str(),
            "accounting_status": str(invoice.get("status") or "").lower(),
        }

    def active_visit_snapshot(self, accounting_invoice_id: int) -> dict:
        canonical = self.canonical_snapshot(accounting_invoice_id)
        if str(canonical["work_date"]) != str(self.work_date_provider()):
            raise DoctorQueueIdentityError("ACCOUNTING_INVOICE_OUTSIDE_ACTIVE_DAY")
        if not canonical.get("patient_link_id"):
            raise DoctorQueueIdentityError("SPECIALIST_ENROLLMENT_REQUIRED")
        encounter = CareJourneyRepository().encounter_for_invoice(
            canonical["accounting_invoice_id"]
        )
        if not encounter:
            raise DoctorQueueIdentityError("SPECIALIST_VISIT_NOT_STARTED")
        current = CareJourneyRepository().current_encounter_event(
            encounter["encounter_id"]
        )
        if not current or current["event_type"] != "STARTED":
            raise DoctorQueueIdentityError("SPECIALIST_VISIT_NOT_ACTIVE")
        canonical["encounter_id"] = encounter["encounter_id"]
        canonical["journey_id"] = encounter["journey_id"]
        return canonical

    def start(self, snapshot: dict, actor_username: str | None = None) -> dict:
        canonical = self.canonical_snapshot(snapshot["accounting_invoice_id"])
        actor = str(actor_username or "system:doctor-queue").strip()
        if str(canonical["work_date"]) != str(self.work_date_provider()):
            raise DoctorQueueIdentityError("ACCOUNTING_INVOICE_OUTSIDE_ACTIVE_DAY")
        if canonical["accounting_status"] != "open":
            raise DoctorQueueIdentityError("ACCOUNTING_INVOICE_NOT_OPEN")
        if not canonical.get("patient_link_id"):
            self.repo.start(**self._repo_snapshot(canonical))
            return canonical

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            CareJourneyService(db=db).start_accounting_visit(
                patient_link_id=canonical["patient_link_id"],
                accounting_invoice_id=canonical["accounting_invoice_id"],
                actor_username=actor,
                expected_work_date=canonical["work_date"],
                effective_at=iran_now(),
                commit=False,
            )
            DoctorQueueRepository(db).start(
                **self._repo_snapshot(canonical), commit=False
            )
            db.commit()
            return canonical
        except Exception:
            db.rollback()
            raise

    def end_visit(
        self,
        snapshot: dict,
        done_by: str,
        notes: str | None = None,
    ) -> dict:
        canonical = self.canonical_snapshot(snapshot["accounting_invoice_id"])
        if str(canonical["work_date"]) != str(self.work_date_provider()):
            raise DoctorQueueIdentityError("ACCOUNTING_INVOICE_OUTSIDE_ACTIVE_DAY")
        if not canonical.get("patient_link_id"):
            self.repo.mark_done(
                done_by=done_by,
                notes=notes,
                **self._repo_snapshot(canonical),
            )
            return canonical

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            repository = CareJourneyRepository(db)
            encounter = repository.encounter_for_invoice(
                canonical["accounting_invoice_id"]
            )
            if not encounter:
                if canonical["accounting_status"] != "open":
                    raise DoctorQueueIdentityError(
                        "SPECIALIST_ENCOUNTER_MISSING_FOR_CLOSED_INVOICE"
                    )
                CareJourneyService(db=db).start_accounting_visit(
                    patient_link_id=canonical["patient_link_id"],
                    accounting_invoice_id=canonical["accounting_invoice_id"],
                    actor_username=done_by,
                    expected_work_date=canonical["work_date"],
                    effective_at=iran_now(),
                    commit=False,
                )
            DoctorQueueRepository(db).mark_done(
                done_by=done_by,
                notes=notes,
                commit=False,
                **self._repo_snapshot(canonical),
            )
            CareJourneyService(db=db).complete_accounting_visit(
                accounting_invoice_id=canonical["accounting_invoice_id"],
                actor_username=done_by,
                effective_at=iran_now(),
                note=notes,
                commit=False,
            )
            db.commit()
            return canonical
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _repo_snapshot(snapshot: dict) -> dict:
        return {
            "accounting_invoice_id": int(snapshot["accounting_invoice_id"]),
            "patient_link_id": snapshot.get("patient_link_id"),
            "national_id": snapshot.get("national_id"),
            "full_name": snapshot.get("full_name") or "—",
            "work_date": snapshot.get("work_date") or today_str(),
        }
