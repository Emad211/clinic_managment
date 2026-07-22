"""Versioned preparation and quality checks for the synthetic safety cohort."""

from __future__ import annotations

from src.adapters.sqlite.demo_cohort_repo import DemoCohortRepository
from src.domain.clinical_engine.demo_cohort import (
    DEMO_COHORT_VERSION,
    DEMO_PATIENTS,
    DEMO_REFERENCE_AT,
    expected_totals,
)
from src.services.activity_logger import log_activity


class DemoCohortService:
    def __init__(self, repository=None):
        self.repository = repository or DemoCohortRepository()

    @staticmethod
    def reference_at():
        return DEMO_REFERENCE_AT

    def summary(self) -> dict:
        summary = self.repository.summary(expected_version=DEMO_COHORT_VERSION)
        summary.update({
            "expected_version": DEMO_COHORT_VERSION,
            "reference_at": DEMO_REFERENCE_AT,
            "years": 5.5,
        })
        return summary

    def ensure(self, *, actor: str, force: bool = False) -> dict:
        actor = (actor or "manager").strip()
        before = self.summary()
        rebuilt = force or not before["ready"]
        if rebuilt:
            self.repository.replace_all(
                DEMO_PATIENTS, version=DEMO_COHORT_VERSION, actor=actor,
            )
        after = self.summary()
        self._validate(after)
        after["rebuilt"] = rebuilt
        if rebuilt:
            log_activity(
                "clinical_v2_demo_cohort_rebuild",
                f"Rebuilt {after['patient_count']} synthetic longitudinal records "
                f"at cohort version {DEMO_COHORT_VERSION}",
                user_id=0, username=actor,
            )
        return after

    @staticmethod
    def _validate(summary: dict) -> None:
        expected = expected_totals()
        actual = summary["totals"]
        checks = {
            "patients": summary["patient_count"] == 10,
            "vitals": actual["vitals"] == expected["vitals"],
            "labs": actual["labs"] == expected["labs"],
            "medications": actual["medications"] == expected["meds"],
            "notes": actual["notes"] == expected["notes"],
            "appointments": actual["appointments"] == expected["appointments"],
            "followups": actual["followups"] == expected["followups"],
            "prescriptions": actual["prescriptions"] == expected["prescriptions"],
            "history": actual["history"] == expected["history"],
            "conditions": actual["conditions"] == expected["conditions"],
        }
        failed = [key for key, passed in checks.items() if not passed]
        if failed:
            raise RuntimeError(
                "synthetic cohort failed completeness checks: " + ", ".join(failed)
            )
