"""Application service for explicit clinical-task and outcome transitions."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.adapters.sqlite.clinical_care_loop_repo import (
    ClinicalCareLoopConflict,
    ClinicalCareLoopRepository,
    ClinicalCareLoopValidationError,
)
from src.common.utils import iran_now


STATUS_LABELS = {
    "OPEN": "باز",
    "ASSIGNED": "واگذار شده",
    "SCHEDULED": "زمان‌بندی شده",
    "IN_PROGRESS": "در حال انجام",
    "DEFERRED": "به تعویق افتاده",
    "COMPLETED": "تکمیل شده",
    "NOT_DONE": "انجام نشد",
    "ENTERED_IN_ERROR": "ثبت‌شده به‌اشتباه",
}
OUTCOME_LABELS = {
    "OBSERVATION": "مشاهده یا اندازه‌گیری",
    "PATIENT_REPORTED": "گزارش بیمار",
    "ENCOUNTER_COMPLETED": "مراجعه انجام شد",
    "PROCEDURE_COMPLETED": "اقدام انجام شد",
    "LAB_COMPLETED": "آزمایش انجام شد",
    "OTHER": "سایر",
}
DISPOSITION_LABELS = {
    "PATIENT_DECLINED": "عدم تمایل بیمار",
    "UNREACHABLE": "عدم دسترسی به بیمار",
    "CLINICIAN_CANCELLED": "لغو با تصمیم بالینی",
    "DUPLICATE": "تکراری",
    "NO_LONGER_NEEDED": "دیگر لازم نیست",
    "OTHER": "سایر",
}


class ClinicalCareLoopService:
    def __init__(self, *, repository=None, clock=None):
        self.repository = repository or ClinicalCareLoopRepository()
        self.clock = clock or iran_now

    def list_open(
        self,
        *,
        reason: str | None = None,
        query: str | None = None,
        patient_link_id: int | None = None,
    ) -> list[dict]:
        rows = self.repository.list_current(
            reason=reason,
            query=query,
            patient_link_id=patient_link_id,
            include_terminal=False,
        )
        today = self.clock().date()
        for row in rows:
            row["status_fa"] = STATUS_LABELS.get(
                row.get("current_status"), row.get("current_status")
            )
            due = row.get("current_due_at") or row.get("due_date")
            try:
                due_date = datetime.fromisoformat(str(due)).date() if due else None
            except ValueError:
                due_date = None
            row["overdue_days"] = (
                max((today - due_date).days, 0) if due_date else 0
            )
            row["is_overdue"] = bool(
                due_date and due_date < today
            )
        return rows

    def current(self, task_id: int) -> dict:
        task = self.repository.current_task(task_id)
        task["status_fa"] = STATUS_LABELS.get(
            task["current_status"], task["current_status"]
        )
        return task

    def record_outcome(
        self,
        task_id: int,
        *,
        outcome_type: str,
        actor_username: str,
        actor_user_id: int | None,
        fact_key: str | None = None,
        value: Any = None,
        unit: str | None = None,
        verification: str = "CONFIRMED",
        observed_at: datetime | str | None = None,
        source_system: str = "clinician",
        source_record_id: str | None = None,
        note: str | None = None,
    ) -> dict:
        return self.repository.record_outcome(
            task_id,
            outcome_type=outcome_type,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            fact_key=fact_key,
            value=value,
            unit=unit,
            verification=verification,
            observed_at=observed_at,
            source_system=source_system,
            source_record_id=source_record_id,
            note=note,
            recorded_at=self.clock(),
        )

    def transition(
        self,
        task_id: int,
        *,
        transition: str,
        expected_current_event_id: int,
        actor_username: str,
        actor_user_id: int | None,
        assigned_to: str | None = None,
        appointment_id: int | None = None,
        due_at: datetime | date | str | None = None,
        disposition_code: str | None = None,
        outcome_event_id: int | None = None,
        note: str | None = None,
    ) -> dict:
        mapping = {
            "assign": "ASSIGNED",
            "schedule": "SCHEDULED",
            "start": "STARTED",
            "defer": "DEFERRED",
            "complete": "COMPLETED",
            "not_done": "NOT_DONE",
            "entered_in_error": "ENTERED_IN_ERROR",
        }
        event_type = mapping.get(str(transition or "").strip().lower())
        if event_type is None:
            raise ClinicalCareLoopValidationError(
                "invalid clinical task transition"
            )
        return self.repository.append_task_event(
            task_id,
            event_type=event_type,
            expected_current_event_id=expected_current_event_id,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            assigned_to=assigned_to,
            appointment_id=appointment_id,
            due_at=due_at,
            disposition_code=disposition_code,
            outcome_event_id=outcome_event_id,
            note=note,
            recorded_at=self.clock(),
        )


__all__ = [
    "ClinicalCareLoopConflict",
    "ClinicalCareLoopService",
    "ClinicalCareLoopValidationError",
    "DISPOSITION_LABELS",
    "OUTCOME_LABELS",
    "STATUS_LABELS",
]
