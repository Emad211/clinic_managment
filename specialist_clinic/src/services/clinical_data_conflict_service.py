"""Application service for explicit, clinician-reviewed source conflict resolution."""
from __future__ import annotations

from src.adapters.sqlite.clinical_data_conflict_repo import (
    ClinicalDataConflictRepository,
)
from src.domain.clinical_engine.data_conflicts import (
    ClinicalDataConflictError,
    ConflictResolutionMethod,
)


_METHOD_LABELS = {
    ConflictResolutionMethod.SELECT_CANDIDATE.value: "انتخاب یک منبع",
    ConflictResolutionMethod.CONFIRMED_ABSENT.value: "تأیید نبود مورد",
    ConflictResolutionMethod.MARK_UNKNOWN.value: "ثبت نامشخص",
    ConflictResolutionMethod.MERGE_CANDIDATES.value: "ادغام منابع مکمل",
}
_ASSERTION_LABELS = {
    "PRESENT": "موجود",
    "ABSENT": "نبود مورد",
    "UNKNOWN": "نامشخص",
}
_STATE_LABELS = {
    "open": ("تعارض باز", "danger"),
    "stale": ("resolution منسوخ", "danger"),
    "resolved_selected": ("منبع منتخب", "ok"),
    "resolved_merged": ("منابع ادغام‌شده", "ok"),
    "resolved_absent": ("نبود مورد تأیید شد", "ok"),
    "resolved_unknown": ("نامشخص ثبت شد", "warn"),
    "clear": ("بدون تعارض", "ok"),
}


class ClinicalDataConflictService:
    def __init__(self, repository=None):
        self.repository = repository or ClinicalDataConflictRepository()

    def projection(self, patient_link_id: int, collection_key: str, *, as_of_at=None):
        return self.repository.projection(
            patient_link_id,
            collection_key,
            as_of_at=as_of_at,
        )

    @staticmethod
    def present_groups(groups) -> list[dict]:
        result = []
        for raw in groups:
            group = dict(raw)
            state_fa, tone = _STATE_LABELS.get(
                group.get("state"), (group.get("state"), "info")
            )
            group["state_fa"] = state_fa
            group["tone"] = tone
            group["resolution_method_fa"] = _METHOD_LABELS.get(
                group.get("resolution_method")
            )
            candidates = []
            for raw_candidate in group.get("candidates", []):
                candidate = dict(raw_candidate)
                candidate["assertion_fa"] = _ASSERTION_LABELS.get(
                    candidate.get("assertion"), candidate.get("assertion")
                )
                candidates.append(candidate)
            group["candidates"] = candidates
            result.append(group)
        return result

    def resolve(
        self,
        *,
        patient_link_id: int,
        collection_key: str,
        conflict_group_key: str,
        method: str,
        actor_username: str,
        actor_user_id: int | None,
        expected_candidate_set_hash: str,
        expected_current_event_id: int | None,
        selected_candidate_keys=(),
        note: str | None = None,
    ) -> dict:
        try:
            normalized_method = ConflictResolutionMethod(method)
        except ValueError as exc:
            raise ClinicalDataConflictError("روش resolution معتبر نیست") from exc
        if normalized_method is ConflictResolutionMethod.SELECT_CANDIDATE:
            selected_candidate_keys = tuple(selected_candidate_keys)
            if len(selected_candidate_keys) != 1:
                raise ClinicalDataConflictError("یک candidate را انتخاب کنید")
        return self.repository.resolve(
            patient_link_id=patient_link_id,
            collection_key=collection_key,
            conflict_group_key=conflict_group_key,
            method=normalized_method,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            expected_candidate_set_hash=expected_candidate_set_hash,
            expected_current_event_id=expected_current_event_id,
            selected_candidate_keys=selected_candidate_keys,
            note=note,
        )
