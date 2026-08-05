"""Read-only context builder for the native five-tab Patient Workspace.

The service reuses the existing repositories and Clinical Engine v2 facade. It does not
interpret clinical values, create recommendations or add a second mutation path.
"""
from __future__ import annotations

import json

from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
from src.adapters.sqlite.drug_catalog_repo import DrugCatalogRepository
from src.adapters.sqlite.encounter_documentation_repo import (
    EncounterDocumentationRepository,
)
from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.lab_catalog_repo import LabCatalogRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.record_repo import RecordRepository
from src.adapters.sqlite.specialist_service_lineage_repo import (
    SpecialistServiceLineageRepository,
)
from src.adapters.sqlite.vitals_repo import VITAL_TYPES, VitalsRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.services.analytics_service import AnalyticsService
from src.services.clinical_engine.facade import ClinicalEngineReadOnlyFacade
from src.services.patient_cockpit_service import PatientCockpitService
from src.services.patient_service import PatientService
from src.services.sms.governance_service import SmsGovernanceService


WORKSPACE_TABS = {
    "summary": "خلاصه",
    "actions": "اقدامات",
    "clinical": "داده‌های بالینی",
    "meds": "دارو و نسخه",
    "encounters": "ویزیت‌ها و اسناد",
}


class PatientWorkspaceService:
    def build(self, patient_link_id: int) -> dict | None:
        pid = int(patient_link_id)
        profile = PatientService().get_full_profile(pid)
        if not profile:
            return None

        analytics = AnalyticsService().patient_analytics(pid)
        clinical_v2 = ClinicalEngineReadOnlyFacade().patient_detail(pid)
        vitals_repo = VitalsRepository()
        rules_repo = ClinicalRulesRepository()
        flags_repo = ClinicalFlagsRepository()
        record_repo = RecordRepository()

        condition_codes = [
            condition.get("condition_code")
            for condition in profile["conditions"]
            if condition.get("condition_code")
        ]
        entry_indicators = [
            indicator
            for indicator in rules_repo.for_conditions(condition_codes)
            if indicator.get("is_vital")
        ]
        indicator_labels = {
            indicator["key"]: indicator
            for indicator in rules_repo.all_indicators(active_only=False)
        }
        recent_vitals = vitals_repo.get_readings(pid, limit=50)
        for reading in recent_vitals:
            metadata = indicator_labels.get(reading["type"]) or VITAL_TYPES.get(
                reading["type"], {}
            )
            reading["type_label"] = metadata.get("label", reading["type"])
            reading["unit"] = reading.get("unit") or metadata.get("unit")

        labs = vitals_repo.get_labs(pid)
        appointments = AppointmentRepository().list_for_patient(pid)
        all_followups = FollowupRepository().list_for_patient(pid)
        open_followups = [
            item for item in all_followups if item.get("status") == "open"
        ]

        medication_events = PatientRepository().get_medication_events(pid)
        prescriptions = record_repo.list_prescriptions(pid)
        for prescription in prescriptions:
            try:
                parsed = json.loads(prescription.get("items") or "[]")
            except (TypeError, ValueError):
                parsed = []
            prescription["item_count"] = (
                len(parsed) if isinstance(parsed, (list, dict)) else 0
            )

        service_lines = (
            SpecialistServiceLineageRepository().current_lines_for_patient(
                pid, limit=200
            )
        )
        service_line_summary = {
            "total": len(service_lines),
            "visits": sum(
                1 for row in service_lines if row.get("item_type") == "VISIT"
            ),
            "injections": sum(
                1 for row in service_lines if row.get("item_type") == "INJECTION"
            ),
            "procedures": sum(
                1 for row in service_lines if row.get("item_type") == "PROCEDURE"
            ),
        }
        encounter_documents = (
            EncounterDocumentationRepository().current_signed_documents_for_patient(
                pid, limit=50
            )
        )
        cockpit = PatientCockpitService()
        next_action = cockpit.next_action(
            clinical_v2=clinical_v2,
            followups=open_followups,
            refill_due=analytics["refill_due"],
            appointments=appointments,
            indicators=analytics["indicators"],
        )
        care_timeline = cockpit.timeline(
            appointments=appointments,
            visits=profile["visit_history"],
            labs=labs,
            followups=all_followups,
            medication_events=medication_events,
            service_lines=service_lines,
            encounter_documents=encounter_documents,
        )

        wallet_repo = WalletRepository()
        return {
            "patient": profile["patient"],
            "conditions": profile["conditions"],
            "medications": profile["medications"],
            "allergies": profile["allergies"],
            "visit_history": profile["visit_history"],
            "reconciliation": profile.get("reconciliation") or {},
            "clinical_v2": clinical_v2,
            "next_action": next_action,
            "entry_indicators": entry_indicators,
            "recent_vitals": recent_vitals,
            "labs": labs,
            "appointments": appointments,
            "all_followups": all_followups,
            "followups": open_followups,
            "condition_catalog": PatientRepository().list_condition_catalog(),
            "flags_by_section": flags_repo.catalog_by_record_section(),
            "patient_flags": flags_repo.get_flag_states(pid),
            "drug_class_options": flags_repo.drug_classes(),
            "drug_class_map": flags_repo.drug_class_map(),
            "surgeries": record_repo.list_surgeries(pid),
            "medical_history": record_repo.list_history(pid),
            "notes_symptom": record_repo.list_notes(pid, "symptom"),
            "notes_exam": record_repo.list_notes(pid, "exam"),
            "notes_lifestyle": record_repo.list_notes(pid, "lifestyle"),
            "lab_catalog": LabCatalogRepository().all(),
            "drug_catalog": DrugCatalogRepository().all(),
            "medication_events": medication_events,
            "prescriptions": prescriptions,
            "indicators": analytics["indicators"],
            "by_category": analytics["by_category"],
            "per_disease": analytics["per_disease"],
            "refill_due": analytics["refill_due"],
            "appt_summary": analytics["appointments"],
            "visits_count": analytics["visits_count"],
            "last_visit": analytics["last_visit"],
            "care_timeline": care_timeline,
            "encounter_documents": encounter_documents,
            "service_lines": service_lines,
            "service_line_summary": service_line_summary,
            "sms_consent": SmsGovernanceService().summary(pid),
            "wallet_balance": wallet_repo.get_balance(pid),
            "wallet_tx": wallet_repo.transactions(pid, limit=20),
        }


__all__ = ["PatientWorkspaceService", "WORKSPACE_TABS"]
