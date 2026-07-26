"""Patient enrollment plus longitudinal clinical-profile orchestration."""
from __future__ import annotations

from typing import Optional

from src.adapters import accounting_bridge
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.services.clinical_reconciliation_service import (
    ClinicalReconciliationService,
)
from src.services.specialist_enrollment_service import (
    SpecialistProgramEnrollmentService,
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
        """Search accounting read-only and mark immutable specialist enrollment."""
        results = accounting_bridge.search_patients(query)
        enrollments = SpecialistEnrollmentRepository()
        for row in results:
            accounting_id = row.get("id")
            row["already_enrolled"] = bool(
                accounting_id
                and enrollments.get_by_accounting_patient(int(accounting_id))
            )
        return results

    def enroll_from_accounting(
        self, accounting_patient_id: int, enrolled_by: str
    ) -> Optional[int]:
        """Create the local mirror and immutable financial cutover atomically."""
        return SpecialistProgramEnrollmentService().enroll_from_accounting(
            int(accounting_patient_id), actor_username=enrolled_by
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
        """Create a local-only patient.

        Manual enrollment never infers an accounting link from name or national ID.
        Linking real accounting history must use the explicit accounting-enrollment
        workflow so a specialist cutover is recorded at the same time.
        """
        if national_id:
            existing = self.repo.get_by_national_id(national_id)
            if existing:
                return existing["id"]
        return self.repo.create(
            national_id=national_id or None,
            accounting_patient_id=None,
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
            "medications": self.repo.get_medications(pid),
            "allergies": self.repo.get_allergies(pid),
            "reconciliation": self.reconciliation.patient_status(pid),
            "visit_history": visit_history,
        }
