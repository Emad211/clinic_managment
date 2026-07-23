"""Application service for explicit clinical encounter lifecycle operations."""
from __future__ import annotations

from datetime import datetime

from src.adapters.sqlite.clinical_encounter_repo import (
    ClinicalEncounterConflict,
    ClinicalEncounterRepository,
)
from src.common.utils import iran_now
from src.domain.clinical_engine.context import (
    CareSetting,
    ClinicalContextError,
    EncounterEventType,
    EncounterType,
)


CARE_SETTING_LABELS = {
    CareSetting.PRIMARY_CARE.value: "مراقبت اولیه",
    CareSetting.SPECIALTY_CLINIC.value: "درمانگاه تخصصی",
    CareSetting.URGENT_CARE.value: "مراجعهٔ فوری",
    CareSetting.TELEHEALTH.value: "مراقبت از راه دور",
}
ENCOUNTER_TYPE_LABELS = {
    EncounterType.OFFICE_VISIT.value: "ویزیت حضوری",
    EncounterType.FOLLOWUP.value: "ویزیت پیگیری",
    EncounterType.URGENT_VISIT.value: "ویزیت فوری",
    EncounterType.TELEVISIT.value: "ویزیت از راه دور",
    EncounterType.MEDICATION_REVIEW.value: "مرور داروها",
    EncounterType.PREVENTIVE_VISIT.value: "ویزیت پیشگیری",
    EncounterType.CHRONIC_CARE_REVIEW.value: "مرور مراقبت مزمن",
}
STATUS_LABELS = {
    "OPEN": "باز",
    "FINALIZED": "نهایی‌شده",
    "CANCELLED": "لغوشده",
    "ENTERED_IN_ERROR": "ثبت‌شده به‌اشتباه",
}


class ClinicalEncounterService:
    def __init__(self, *, repository=None, clock=None):
        self.repository = repository or ClinicalEncounterRepository()
        self.clock = clock or iran_now

    @staticmethod
    def _reasons(raw) -> tuple[str, ...]:
        if isinstance(raw, str):
            raw = raw.replace("،", ",").split(",")
        return tuple(str(item).strip() for item in (raw or ()) if str(item).strip())

    def open(
        self,
        patient_link_id: int,
        *,
        care_setting: str,
        encounter_type: str,
        actor_username: str,
        actor_user_id: int | None,
        appointment_id: int | None = None,
        reason_codes=(),
        chief_complaint: str | None = None,
        responsible_actor: str | None = None,
        effective_at: datetime | None = None,
        note: str | None = None,
    ) -> dict:
        return self.repository.open(
            patient_link_id,
            care_setting=CareSetting(care_setting),
            encounter_type=EncounterType(encounter_type),
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            appointment_id=appointment_id,
            reason_codes=self._reasons(reason_codes),
            chief_complaint=chief_complaint,
            responsible_actor=responsible_actor,
            effective_at=effective_at or self.clock(),
            recorded_at=self.clock(),
            note=note,
        )

    def update(
        self,
        encounter_key: str,
        *,
        expected_current_event_id: int,
        actor_username: str,
        actor_user_id: int | None,
        care_setting: str,
        encounter_type: str,
        reason_codes=(),
        chief_complaint: str | None = None,
        responsible_actor: str | None = None,
        note: str | None = None,
    ) -> dict:
        return self.repository.append(
            encounter_key,
            event_type=EncounterEventType.UPDATED,
            expected_current_event_id=expected_current_event_id,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            care_setting=CareSetting(care_setting),
            encounter_type=EncounterType(encounter_type),
            reason_codes=self._reasons(reason_codes),
            chief_complaint=chief_complaint,
            responsible_actor=responsible_actor,
            recorded_at=self.clock(),
            note=note,
        )

    def transition(
        self,
        encounter_key: str,
        *,
        transition: str,
        expected_current_event_id: int,
        actor_username: str,
        actor_user_id: int | None,
        note: str | None = None,
    ) -> dict:
        mapping = {
            "finalize": EncounterEventType.FINALIZED,
            "cancel": EncounterEventType.CANCELLED,
            "entered_in_error": EncounterEventType.ENTERED_IN_ERROR,
        }
        event_type = mapping.get(str(transition or "").strip().lower())
        if event_type is None:
            raise ClinicalContextError("invalid encounter transition")
        return self.repository.append(
            encounter_key,
            event_type=event_type,
            expected_current_event_id=expected_current_event_id,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            recorded_at=self.clock(),
            note=note,
        )

    def list_for_patient(self, patient_link_id: int) -> list[dict]:
        result = self.repository.list_for_patient(patient_link_id)
        for item in result:
            item["care_setting_fa"] = CARE_SETTING_LABELS.get(
                item.get("care_setting"), item.get("care_setting")
            )
            item["encounter_type_fa"] = ENCOUNTER_TYPE_LABELS.get(
                item.get("encounter_type"), item.get("encounter_type")
            )
            item["status_fa"] = STATUS_LABELS.get(
                item.get("status"), item.get("status")
            )
        return result


__all__ = [
    "CARE_SETTING_LABELS",
    "ENCOUNTER_TYPE_LABELS",
    "STATUS_LABELS",
    "ClinicalEncounterConflict",
    "ClinicalEncounterService",
]
