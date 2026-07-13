"""Persistence adapter for the complete patient-record aggregate.

No route owns SQL.  The service layer handles validation/orchestration while this
module owns tenant-scoped ORM queries and the one catalog-mapping join that
Django cannot model because ``condition_lab_tests`` has a composite primary key.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from django.db import connection

from clinical.models import (
    Appointment,
    ClinicalIndicator,
    Condition,
    LabResult,
    PatientCondition,
    PatientFlag,
    PatientMedication,
    Prescription,
    VitalReading,
)
from clinical.record_models import (
    ClinicalNote,
    DrugCatalog,
    DrugClass,
    FlagCatalog,
    LabTestCatalog,
    MedicalHistory,
    MedicationEvent,
    SurgeryHistory,
)


CATEGORY_LABELS = {
    "cardiac": "قلبی-عروقی",
    "renal": "کلیه",
    "risk": "ریسک",
    "hepatic": "کبد",
    "repro": "باروری",
    "lifestyle": "سبک زندگی",
    "functional": "وضعیت عملکردی",
    "history": "سابقه",
    "exam": "معاینات",
    "other": "سایر",
}


def parse_flag_options(raw: Optional[str]) -> list[dict[str, str]]:
    """Mirror specialist_clinic's ``value|label,value|label`` parser."""
    result: list[dict[str, str]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        value, label = part.split("|", 1) if "|" in part else (part, part)
        result.append({"value": value.strip(), "label": label.strip()})
    return result


def parse_standard_doses(raw: Optional[str]) -> list[str]:
    """Parse the specialist catalog JSON-string, tolerating old comma strings."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(value) for value in parsed]
    except (TypeError, ValueError):
        pass
    return [part.strip() for part in raw.split(",") if part.strip()]


def _dict_rows(cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class RecordRepository:
    # ---------------------------------------------------------------- catalogs
    def list_condition_catalog(self, *, tenant_id: int) -> list[Condition]:
        return list(
            Condition.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
                "display_order", "id"
            )
        )

    def get_condition(self, *, tenant_id: int, condition_id: int) -> Optional[Condition]:
        return (
            Condition.objects.filter(
                tenant_id=tenant_id, id=condition_id, is_active=True
            ).first()
        )

    def list_flag_catalog(self, *, tenant_id: int) -> list[FlagCatalog]:
        return list(
            FlagCatalog.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
                "display_order", "id"
            )
        )

    def get_flags_by_keys(
        self, *, tenant_id: int, keys: Iterable[str]
    ) -> dict[str, FlagCatalog]:
        rows = FlagCatalog.objects.filter(
            tenant_id=tenant_id, is_active=True, flag_key__in=list(keys)
        )
        return {row.flag_key: row for row in rows}

    def list_lab_catalog(self, *, tenant_id: int) -> list[LabTestCatalog]:
        return list(
            LabTestCatalog.objects.filter(
                tenant_id=tenant_id, is_active=True
            ).order_by("display_order", "test_key")
        )

    def get_labs_by_keys(
        self, *, tenant_id: int, keys: Iterable[str]
    ) -> dict[str, LabTestCatalog]:
        rows = LabTestCatalog.objects.filter(
            tenant_id=tenant_id, is_active=True, test_key__in=list(keys)
        )
        return {row.test_key: row for row in rows}

    def suggested_labs(
        self, *, tenant_id: int, condition_codes: list[str]
    ) -> list[dict[str, Any]]:
        codes = [code for code in condition_codes if code]
        if not codes:
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT l.id, l.test_key, l.name_fa, l.unit, l.ref_low, l.ref_high,
                       l.category, l.display_order, l.is_active,
                       MIN(m.display_order) AS map_order
                FROM clinical.condition_lab_tests m
                JOIN clinical.lab_test_catalog l
                  ON l.tenant_id = m.tenant_id
                 AND l.test_key = m.lab_test_key
                WHERE m.tenant_id = %s
                  AND m.condition_code = ANY(%s)
                  AND l.is_active = TRUE
                GROUP BY l.id, l.test_key, l.name_fa, l.unit, l.ref_low,
                         l.ref_high, l.category, l.display_order, l.is_active
                ORDER BY map_order, l.display_order, l.test_key
                """,
                [tenant_id, codes],
            )
            return _dict_rows(cursor)

    def list_drug_classes(self, *, tenant_id: int) -> list[DrugClass]:
        return list(
            DrugClass.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
                "display_order", "id"
            )
        )

    def get_drug_class(
        self, *, tenant_id: int, class_key: str
    ) -> Optional[DrugClass]:
        return (
            DrugClass.objects.filter(
                tenant_id=tenant_id, class_key=class_key, is_active=True
            ).first()
        )

    def list_drug_catalog(self, *, tenant_id: int) -> list[DrugCatalog]:
        return list(
            DrugCatalog.objects.filter(tenant_id=tenant_id, is_active=True).order_by(
                "drug_class_key", "generic_fa", "id"
            )
        )

    def get_drug(
        self, *, tenant_id: int, drug_id: int
    ) -> Optional[DrugCatalog]:
        return (
            DrugCatalog.objects.filter(
                tenant_id=tenant_id, id=drug_id, is_active=True
            ).first()
        )

    def list_indicators(self, *, tenant_id: int) -> list[ClinicalIndicator]:
        return list(
            ClinicalIndicator.objects.filter(
                tenant_id=tenant_id, is_active=True, is_vital=True
            ).order_by("display_order", "id")
        )

    # ---------------------------------------------------------- patient record
    def list_surgeries(
        self, *, tenant_id: int, patient_link_id: int
    ) -> list[SurgeryHistory]:
        return list(
            SurgeryHistory.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-performed_on", "-id")
        )

    def create_surgery(self, **fields) -> SurgeryHistory:
        return SurgeryHistory.objects.create(**fields)

    def get_surgery(
        self, *, tenant_id: int, patient_link_id: int, row_id: int
    ) -> Optional[SurgeryHistory]:
        return (
            SurgeryHistory.objects.filter(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=row_id,
            ).first()
        )

    def list_medical_history(
        self, *, tenant_id: int, patient_link_id: int
    ) -> list[MedicalHistory]:
        return list(
            MedicalHistory.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-since", "-id")
        )

    def create_medical_history(self, **fields) -> MedicalHistory:
        return MedicalHistory.objects.create(**fields)

    def get_medical_history(
        self, *, tenant_id: int, patient_link_id: int, row_id: int
    ) -> Optional[MedicalHistory]:
        return (
            MedicalHistory.objects.filter(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=row_id,
            ).first()
        )

    def list_notes(
        self, *, tenant_id: int, patient_link_id: int
    ) -> list[ClinicalNote]:
        return list(
            ClinicalNote.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-recorded_at", "-id")
        )

    def create_note(self, **fields) -> ClinicalNote:
        return ClinicalNote.objects.create(**fields)

    def get_note(
        self, *, tenant_id: int, patient_link_id: int, row_id: int
    ) -> Optional[ClinicalNote]:
        return (
            ClinicalNote.objects.filter(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=row_id,
            ).first()
        )

    def list_patient_flags(
        self, *, tenant_id: int, patient_link_id: int
    ) -> list[PatientFlag]:
        return list(
            PatientFlag.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("flag_key")
        )

    def set_flag(
        self,
        *,
        tenant_id: int,
        patient_link_id: int,
        flag_key: str,
        value: str,
        recorded_by: str,
    ) -> PatientFlag:
        row, _created = PatientFlag.objects.update_or_create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            flag_key=flag_key,
            defaults={"value": value, "recorded_by": recorded_by},
        )
        return row

    def clear_flag(
        self, *, tenant_id: int, patient_link_id: int, flag_key: str
    ) -> int:
        deleted, _ = PatientFlag.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            flag_key=flag_key,
        ).delete()
        return deleted

    # ------------------------------------------------------------- conditions
    def list_patient_conditions(
        self, *, tenant_id: int, patient_link_id: int
    ) -> list[PatientCondition]:
        return list(
            PatientCondition.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-is_active", "-diagnosed_at", "-id")
        )

    def get_patient_condition(
        self, *, tenant_id: int, patient_link_id: int, row_id: int
    ) -> Optional[PatientCondition]:
        return (
            PatientCondition.objects.filter(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=row_id,
            ).first()
        )

    def find_condition_assignment(
        self, *, tenant_id: int, patient_link_id: int, condition_id: int
    ) -> Optional[PatientCondition]:
        return (
            PatientCondition.objects.select_for_update()
            .filter(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                condition_id=condition_id,
            )
            .order_by("-is_active", "-id")
            .first()
        )

    def create_patient_condition(self, **fields) -> PatientCondition:
        return PatientCondition.objects.create(**fields)

    # ------------------------------------------------------------- medications
    def list_medications(
        self, *, tenant_id: int, patient_link_id: int
    ) -> list[PatientMedication]:
        return list(
            PatientMedication.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-is_active", "-created_at", "-id")
        )

    def get_medication_for_update(
        self, *, tenant_id: int, patient_link_id: int, medication_id: int
    ) -> Optional[PatientMedication]:
        return (
            PatientMedication.objects.select_for_update()
            .filter(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=medication_id,
            )
            .first()
        )

    def create_medication(self, **fields) -> PatientMedication:
        return PatientMedication.objects.create(**fields)

    def create_medication_event(self, **fields) -> MedicationEvent:
        return MedicationEvent.objects.create(**fields)

    def list_medication_events(
        self, *, tenant_id: int, patient_link_id: int
    ) -> list[MedicationEvent]:
        return list(
            MedicationEvent.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("event_date", "id")
        )

    # ------------------------------------------------------------------- labs
    def list_labs(
        self, *, tenant_id: int, patient_link_id: int, limit: int = 200
    ) -> list[LabResult]:
        return list(
            LabResult.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-taken_at", "-id")[:limit]
        )

    def create_lab(self, **fields) -> LabResult:
        return LabResult.objects.create(**fields)

    def get_lab(
        self, *, tenant_id: int, patient_link_id: int, lab_id: int
    ) -> Optional[LabResult]:
        return (
            LabResult.objects.filter(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=lab_id,
            ).first()
        )

    # ----------------------------------------------------------------- vitals
    def list_vitals(
        self, *, tenant_id: int, patient_link_id: int, limit: int = 200
    ) -> list[VitalReading]:
        return list(
            VitalReading.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-measured_at", "-id")[:limit]
        )

    def create_vital(self, **fields) -> VitalReading:
        return VitalReading.objects.create(**fields)

    def get_vital(
        self, *, tenant_id: int, patient_link_id: int, vital_id: int
    ) -> Optional[VitalReading]:
        return (
            VitalReading.objects.filter(
                tenant_id=tenant_id,
                patient_link_id=patient_link_id,
                id=vital_id,
            ).first()
        )

    # ---------------------------------------------------------- other history
    def list_appointments(
        self, *, tenant_id: int, patient_link_id: int, limit: int = 100
    ) -> list[Appointment]:
        return list(
            Appointment.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-scheduled_at", "-id")[:limit]
        )

    def list_prescriptions(
        self, *, tenant_id: int, patient_link_id: int, limit: int = 100
    ) -> list[Prescription]:
        return list(
            Prescription.objects.filter(
                tenant_id=tenant_id, patient_link_id=patient_link_id
            ).order_by("-issued_at", "-id")[:limit]
        )
