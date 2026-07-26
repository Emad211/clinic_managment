"""Physician queue with canonical accounting identity and specialist journeys.

Accounting is always read-only. Posted hidden fields are never trusted for patient,
invoice, work-date, or revenue attribution. An optional appointment id is validated
server-side and linked to the Encounter in the same transaction that records attendance.
"""
from __future__ import annotations

from src.adapters import accounting_bridge, specialist_accounting_revenue
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelRepository,
)
from src.adapters.sqlite.specialist_financial_funnel_schema import (
    ensure_specialist_financial_funnel_storage,
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
        appointments = AppointmentRepository()
        funnel = SpecialistFinancialFunnelRepository()
        from src.services.campaign_economics_service import CampaignEconomicsService
        campaign_economics = CampaignEconomicsService()
        waiting, done = [], []
        for invoice in opens:
            accounting_patient_id = int(invoice["patient_id"])
            enrollment = self.enrollments.get_by_accounting_patient(
                accounting_patient_id
            )
            entry = log.get(int(invoice["invoice_id"])) or {}
            status = entry.get("status", "waiting")
            patient_link_id = (
                int(enrollment["patient_link_id"]) if enrollment else None
            )
            encounter = CareJourneyRepository().encounter_for_invoice(
                int(invoice["invoice_id"])
            )
            link = (
                funnel.appointment_link_for_encounter(encounter["encounter_id"])
                if encounter
                else None
            )
            options = (
                appointments.scheduled_for_patient_date(patient_link_id, work_day)
                if patient_link_id and not link
                else []
            )
            row = {
                "invoice_id": int(invoice["invoice_id"]),
                "accounting_patient_id": accounting_patient_id,
                "national_id": (invoice.get("national_id") or "").strip() or None,
                "full_name": invoice.get("full_name") or "—",
                "phone_number": invoice.get("phone_number"),
                "opened_at": invoice.get("opened_at"),
                "work_date": invoice.get("work_date") or work_day,
                "status": status,
                "patient_link_id": patient_link_id,
                "enrolled": bool(enrollment),
                "done_by": entry.get("done_by"),
                "appointment_options": options,
                "linked_appointment_id": (
                    int(link["appointment_id"]) if link else None
                ),
                "campaign_response_options": (
                    campaign_economics.positive_response_options(patient_link_id)
                    if patient_link_id else []
                ),
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
        link = SpecialistFinancialFunnelRepository().appointment_link_for_encounter(
            encounter["encounter_id"]
        )
        canonical["encounter_id"] = encounter["encounter_id"]
        canonical["journey_id"] = encounter["journey_id"]
        canonical["appointment_id"] = (
            int(link["appointment_id"]) if link else None
        )
        return canonical

    @staticmethod
    def _validate_appointment(
        db,
        *,
        appointment_id: int,
        patient_link_id: int,
        work_date: str,
    ) -> dict:
        appointment = AppointmentRepository(db).get(int(appointment_id))
        if not appointment:
            raise DoctorQueueIdentityError("SPECIALIST_APPOINTMENT_NOT_FOUND")
        if int(appointment["patient_link_id"]) != int(patient_link_id):
            raise DoctorQueueIdentityError("SPECIALIST_APPOINTMENT_PATIENT_MISMATCH")
        if str(appointment.get("status") or "") != "scheduled":
            raise DoctorQueueIdentityError("SPECIALIST_APPOINTMENT_NOT_SCHEDULED")
        if str(appointment.get("scheduled_at") or "")[:10] != str(work_date):
            raise DoctorQueueIdentityError("SPECIALIST_APPOINTMENT_DATE_MISMATCH")
        return appointment

    def start(
        self,
        snapshot: dict,
        actor_username: str | None = None,
        appointment_id: int | None = None,
        campaign_response_event_id: int | None = None,
        require_documentation: bool = False,
    ) -> dict:
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
        ensure_specialist_financial_funnel_storage(db)
        db.execute("BEGIN IMMEDIATE")
        try:
            if appointment_id is not None:
                self._validate_appointment(
                    db,
                    appointment_id=int(appointment_id),
                    patient_link_id=int(canonical["patient_link_id"]),
                    work_date=str(canonical["work_date"]),
                )
            started = CareJourneyService(db=db).start_accounting_visit(
                patient_link_id=canonical["patient_link_id"],
                accounting_invoice_id=canonical["accounting_invoice_id"],
                actor_username=actor,
                expected_work_date=canonical["work_date"],
                effective_at=iran_now(),
                commit=False,
            )
            encounter = started["encounter"]
            if appointment_id is not None:
                SpecialistFinancialFunnelRepository(db).link_appointment_once(
                    appointment_id=int(appointment_id),
                    encounter_id=encounter["encounter_id"],
                    patient_link_id=int(canonical["patient_link_id"]),
                    journey_id=encounter["journey_id"],
                    actor_username=actor,
                    effective_at=iran_now(),
                    commit=False,
                )
                AppointmentRepository(db).set_status(
                    int(appointment_id), "done", commit=False
                )
            if campaign_response_event_id is not None:
                from src.services.campaign_economics_service import (
                    CampaignEconomicsService,
                )
                CampaignEconomicsService(db=db).attribute_response_to_journey(
                    response_event_id=int(campaign_response_event_id),
                    journey_id=encounter["journey_id"],
                    actor_username=actor,
                    idempotency_key=(
                        f"doctor-queue-campaign-attribution:"
                        f"{encounter['journey_id']}:"
                        f"{int(campaign_response_event_id)}"
                    ),
                    commit=False,
                )
            if require_documentation:
                from src.adapters.sqlite.encounter_documentation_repo import (
                    EncounterDocumentationRepository,
                )
                EncounterDocumentationRepository(db).require_for_encounter(
                    encounter["encounter_id"],
                    actor_username=actor,
                    commit=False,
                )
            DoctorQueueRepository(db).start(
                **self._repo_snapshot(canonical), commit=False
            )
            db.commit()
            canonical["encounter_id"] = encounter["encounter_id"]
            canonical["journey_id"] = encounter["journey_id"]
            canonical["appointment_id"] = appointment_id
            canonical["campaign_response_event_id"] = campaign_response_event_id
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
        """Legacy-compatible completion; REQUIRED A9 encounters need a signed document."""
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
                raise DoctorQueueIdentityError("SPECIALIST_VISIT_NOT_STARTED")
            current = repository.current_encounter_event(encounter["encounter_id"])
            if not current or current["event_type"] != "STARTED":
                raise DoctorQueueIdentityError("SPECIALIST_VISIT_NOT_ACTIVE")
            from src.adapters.sqlite.encounter_documentation_repo import (
                EncounterDocumentationRepository,
            )
            documentation = EncounterDocumentationRepository(db)
            requirement = documentation.requirement(encounter["encounter_id"])
            if requirement and requirement["requirement_status"] == "REQUIRED":
                document = documentation.current_document(encounter["encounter_id"])
                if not document or document["document_status"] != "SIGNED":
                    raise DoctorQueueIdentityError(
                        "SIGNED_ENCOUNTER_DOCUMENT_REQUIRED"
                    )
            DoctorQueueRepository(db).mark_done(
                done_by=done_by,
                notes=notes,
                commit=False,
                **self._repo_snapshot(canonical),
            )
            completed = CareJourneyService(db=db).complete_accounting_visit(
                accounting_invoice_id=canonical["accounting_invoice_id"],
                actor_username=done_by,
                effective_at=iran_now(),
                note=notes,
                commit=False,
            )
            db.commit()
            canonical["encounter_id"] = completed["encounter"]["encounter_id"]
            canonical["journey_id"] = completed["encounter"]["journey_id"]
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
