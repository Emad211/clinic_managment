"""Atomic entry of an accounting patient into the specialist-care program."""
from __future__ import annotations

from src.adapters import accounting_bridge
from src.adapters import specialist_accounting_revenue
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.common.utils import iran_now


class SpecialistProgramEnrollmentService:
    def __init__(self, repository: SpecialistEnrollmentRepository | None = None):
        self.repository = repository or SpecialistEnrollmentRepository()

    def enroll_from_accounting(
        self,
        accounting_patient_id: int,
        *,
        actor_username: str,
    ) -> int:
        accounting_id = int(accounting_patient_id)
        actor = str(actor_username or "").strip()
        if not actor:
            raise ValueError("actor_username is required")

        existing_enrollment = self.repository.get_by_accounting_patient(accounting_id)
        if existing_enrollment:
            return int(existing_enrollment["patient_link_id"])

        patient = accounting_bridge.get_patient_by_id(accounting_id)
        if not patient:
            raise LookupError("بیمار در دیتابیس حسابداری پیدا نشد")

        # The historical cutoff is an audit snapshot only. Revenue eligibility still
        # requires an explicit Journey/Encounter/invoice attribution event.
        cutoff = specialist_accounting_revenue.max_invoice_id(accounting_id)
        effective_at = iran_now()
        db = self.repository.connection()
        db.execute("BEGIN IMMEDIATE")
        try:
            patient_link_id = self.repository.create_local_link_from_accounting(
                accounting_patient=patient,
                accounting_patient_id=accounting_id,
                enrolled_at=effective_at,
                created_by=actor,
                commit=False,
            )
            self.repository.create_once(
                patient_link_id=patient_link_id,
                accounting_patient_id=accounting_id,
                effective_at=effective_at,
                accounting_snapshot_at=effective_at,
                accounting_invoice_cutoff_id=cutoff,
                created_by=actor,
                commit=False,
            )
            from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
            SmsGovernanceRepository(db).ensure_patient_defaults(
                patient_link_id,
                actor_username=actor,
                commit=False,
            )
            db.commit()
            return int(patient_link_id)
        except Exception:
            db.rollback()
            raise
