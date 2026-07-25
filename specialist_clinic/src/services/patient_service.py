"""Patient enrollment plus longitudinal clinical-profile orchestration."""
from __future__ import annotations

from typing import Optional

from src.adapters import accounting_bridge
from src.adapters.sqlite.patients_repo import PatientRepository
from src.services.clinical_reconciliation_service import (
    ClinicalReconciliationService,
)


class PatientService:
    def __init__(
        self,
        repo: PatientRepository | None = None,
        reconciliation: ClinicalReconciliationService | None = None,
    ):
        self.repo = repo or PatientRepository()
        self.reconciliation = reconciliation or ClinicalReconciliationService()

    def search_accounting(self, query: str) -> list[dict]:
        """Search accounting read-only and mark already-enrolled patients."""
        results = accounting_bridge.search_patients(query)
        for row in results:
            national_id = row.get("national_id")
            row["already_enrolled"] = bool(
                national_id and self.repo.get_by_national_id(national_id)
            )
        return results

    def enroll_from_accounting(
        self, accounting_patient_id: int, enrolled_by: str
    ) -> Optional[int]:
        """Pull one patient from accounting without ever writing its database."""
        patient = accounting_bridge.get_patient_by_id(accounting_patient_id)
        if not patient:
            return None
        national_id = patient.get("national_id")
        if national_id:
            existing = self.repo.get_by_national_id(national_id)
            if existing:
                return existing["id"]
        return self.repo.create(
            national_id=national_id,
            accounting_patient_id=patient.get("id"),
            full_name=patient.get("full_name") or "—",
            phone_number=patient.get("phone_number"),
            gender=patient.get("gender"),
            birthdate=patient.get("birthdate"),
            address=patient.get("address"),
            enrolled_by=enrolled_by,
        )

    def enroll_manual(
        self,
        *,
        full_name,
        national_id,
        phone_number,
        gender,
        birthdate,
        address,
        enrolled_by,
    ) -> Optional[int]:
        """Create a local patient and optionally link a read-only accounting match."""
        if national_id:
            existing = self.repo.get_by_national_id(national_id)
            if existing:
                return existing["id"]
            accounting_patient = accounting_bridge.get_patient_by_national_id(
                national_id
            )
            accounting_patient_id = (
                accounting_patient.get("id") if accounting_patient else None
            )
        else:
            accounting_patient_id = None
        return self.repo.create(
            national_id=national_id or None,
            accounting_patient_id=accounting_patient_id,
            full_name=full_name,
            phone_number=phone_number,
            gender=gender,
            birthdate=birthdate,
            address=address,
            enrolled_by=enrolled_by,
        )

    def get_full_profile(self, pid: int) -> Optional[dict]:
        patient = self.repo.get_by_id(pid)
        if not patient:
            return None
        visit_history = []
        if patient.get("accounting_patient_id"):
            visit_history = accounting_bridge.get_visit_history(
                patient["accounting_patient_id"]
            )
        return {
            "patient": patient,
            "conditions": self.repo.get_patient_conditions(pid),
            # Preserve the long-standing cockpit contract: only active medicines
            # are shown. Historical rows are consumed by the reconciliation/fact
            # repositories, not leaked into current prescription and UI flows.
            "medications": self.repo.get_medications(pid),
            "allergies": self.repo.get_allergies(pid),
            "reconciliation": self.reconciliation.patient_status(pid),
            "visit_history": visit_history,
        }
