"""Application service for explicit medication/allergy/problem-list review."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.adapters.sqlite.clinical_reconciliation_repo import (
    ClinicalReconciliationRepository,
)
from src.common.utils import iran_now
from src.services.clinical_data_conflict_service import (
    ClinicalDataConflictService,
)
from src.domain.clinical_engine.reconciliation import (
    COLLECTION_KEYS,
    COLLECTION_LABELS_FA,
)


_STATE_META = {
    "conflict_unresolved": (
        "تعارض بالینی حل‌نشده",
        "danger",
        "منابع برای یک مفهوم بالینی پاسخ ناسازگار دارند؛ موتور تا resolution صریح از این فهرست استفاده نمی‌کند.",
    ),
    "conflict_unknown": (
        "تعارض با وضعیت نامشخص بسته شد",
        "warn",
        "پاسخ قطعی در دسترس نیست و این فهرست عمداً UNKNOWN باقی می‌ماند.",
    ),
    "unreconciled": (
        "مرور نشده",
        "warn",
        "وجود یا نبود اقلام هنوز به‌عنوان فهرست کامل تأیید نشده است.",
    ),
    "partial": (
        "مرور ناقص",
        "warn",
        "بخشی از فهرست مرور شده، اما کامل‌بودن آن قابل ادعا نیست.",
    ),
    "stale": (
        "پس از مرور تغییر کرده",
        "danger",
        "محتوای فهرست بعد از آخرین تأیید تغییر کرده و باید دوباره مرور شود.",
    ),
    "mapping_incomplete": (
        "نگاشت استاندارد ناقص",
        "danger",
        "فهرست مرور شده است، اما بعضی اقلام کد یا کلاس استاندارد قابل استفاده ندارند.",
    ),
    "confirmed_present": (
        "مرور کامل",
        "ok",
        "فهرست فعلی به‌صورت کامل مرور و تأیید شده است.",
    ),
    "confirmed_absent": (
        "نبود مورد، صریحاً تأیید شده",
        "ok",
        "فهرست کامل مرور شده و نبود مورد به‌طور صریح ثبت شده است.",
    ),
}


class ClinicalReconciliationService:
    def __init__(self, repository=None, conflicts=None, clock=None):
        self.repository = repository or ClinicalReconciliationRepository()
        self.conflicts = conflicts or ClinicalDataConflictService()
        self.clock = clock or iran_now

    def patient_status(
        self,
        patient_link_id: int,
        *,
        as_of_at: datetime | None = None,
    ) -> dict[str, dict[str, Any]]:
        projections = self.repository.patient_projections(
            patient_link_id,
            as_of_at=as_of_at or self.clock(),
        )
        result: dict[str, dict[str, Any]] = {}
        for key, projection in projections.items():
            title, tone, detail = _STATE_META[projection.state]
            event = projection.reconciliation_event or {}
            result[key] = {
                "collection_key": key,
                "label": COLLECTION_LABELS_FA[key],
                "state": projection.state,
                "state_fa": title,
                "tone": tone,
                "detail": detail,
                "item_count": projection.item_count,
                "mapping_complete": projection.mapping_complete,
                "clinical_complete": (
                    projection.state in {"confirmed_present", "confirmed_absent"}
                ),
                "content_hash": projection.content_hash,
                "conflict_snapshot_hash": projection.conflict_snapshot_hash,
                "conflict_count": projection.conflict_count,
                "unresolved_conflict_count": projection.unresolved_conflict_count,
                "resolved_unknown_count": projection.resolved_unknown_count,
                "conflicts": self.conflicts.present_groups(projection.conflicts),
                "reconciled_at": event.get("reconciled_at"),
                "actor_username": event.get("actor_username"),
                "patient_confirmed": bool(event.get("patient_confirmed")),
                "completeness": event.get("completeness"),
                "note": event.get("note"),
                "warnings": list(projection.warnings),
            }
        return result

    def record(
        self,
        *,
        patient_link_id: int,
        collection_key: str,
        completeness: str,
        actor_username: str,
        actor_user_id: int | None,
        attested: bool,
        patient_confirmed: bool = False,
        note: str | None = None,
    ) -> dict[str, Any]:
        if collection_key not in COLLECTION_KEYS:
            raise ValueError("این فهرست قابل مرور نیست")
        if not attested:
            raise ValueError("تأیید مطالعهٔ کامل فهرست الزامی است")
        if completeness not in {"complete", "partial"}:
            raise ValueError("وضعیت کامل یا ناقص را مشخص کنید")
        clean_note = (note or "").strip()
        if completeness == "partial" and not clean_note:
            raise ValueError("برای مرور ناقص، علت یا بخشِ باقی‌مانده را بنویسید")
        return self.repository.record(
            patient_link_id=patient_link_id,
            collection_key=collection_key,
            completeness=completeness,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            source="clinician",
            patient_confirmed=patient_confirmed,
            reconciled_at=self.clock(),
            note=clean_note or None,
        )
