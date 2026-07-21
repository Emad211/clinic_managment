"""Clinician decisions as append-only events; never execute clinical actions."""

from __future__ import annotations

from src.adapters.sqlite.clinical_engine_audit_repo import ClinicalEngineAuditRepository
from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
from src.domain.clinical_engine import (
    ClinicalDecision,
    RecommendationEventType,
    RunStatus,
)


_ALLOWED_DECISIONS = {
    ClinicalDecision.ACCEPTED,
    ClinicalDecision.DISMISSED,
    ClinicalDecision.DEFERRED,
}
_REASON_CODES = {
    "NOT_APPLICABLE_NOW",
    "PATIENT_PREFERENCE",
    "CLINICAL_JUDGMENT",
    "MORE_DATA_NEEDED",
    "ALREADY_ADDRESSED",
    "OTHER",
}


class ClinicalDecisionValidationError(ValueError):
    pass


class ClinicalDecisionConflict(RuntimeError):
    pass


class ClinicalDecisionService:
    """Validate and append review state without prescribing or mutating care."""

    def __init__(self, *, audit=None, facts=None):
        self.audit = audit or ClinicalEngineAuditRepository()
        self.facts = facts or ClinicalEngineFactRepository()

    def record(
        self,
        *,
        patient_link_id: int,
        recommendation_event_id: int,
        decision: str | ClinicalDecision,
        actor_user_id: int | None,
        actor_username: str,
        expected_current_event_id: int | None,
        reason_code: str | None = None,
        reason_text: str | None = None,
    ) -> dict:
        if self.facts.get_mode() != "on_selected" or not self.facts.is_selected_patient(
            patient_link_id
        ):
            raise ClinicalDecisionValidationError("v2 decisions are not enabled for this patient")
        try:
            normalized_decision = ClinicalDecision(str(decision).upper())
        except ValueError as exc:
            raise ClinicalDecisionValidationError("invalid decision") from exc
        if normalized_decision not in _ALLOWED_DECISIONS:
            raise ClinicalDecisionValidationError("CORRECTED is reserved for imported audit repair")
        actor = (actor_username or "").strip()
        if not actor:
            raise ClinicalDecisionValidationError("actor_username is required")
        normalized_reason = (reason_code or "").strip().upper() or None
        if normalized_reason and normalized_reason not in _REASON_CODES:
            raise ClinicalDecisionValidationError("invalid reason_code")
        text = (reason_text or "").strip() or None
        if text and len(text) > 500:
            raise ClinicalDecisionValidationError("reason_text is too long")
        if normalized_decision is ClinicalDecision.DISMISSED and not normalized_reason:
            raise ClinicalDecisionValidationError("reason_code is required for dismissal")

        context = self.audit.recommendation_context(
            recommendation_event_id, patient_link_id=patient_link_id
        )
        if not context or not context["payload"].get("suggestion_only", False):
            raise ClinicalDecisionValidationError(
                "recommendation is unavailable or does not belong to this patient"
            )
        try:
            return self.audit.append_current_decision(
                recommendation_event_id=recommendation_event_id,
                patient_link_id=patient_link_id,
                decision=normalized_decision,
                actor_user_id=actor_user_id,
                actor_username=actor,
                expected_current_event_id=expected_current_event_id,
                reason_code=normalized_reason,
                reason_text=text,
            )
        except RuntimeError as exc:
            if str(exc) == "STALE_DECISION_STATE":
                raise ClinicalDecisionConflict(
                    "recommendation decision changed; reload before recording another decision"
                ) from exc
            raise


class LegacyDecisionImporter:
    """Idempotently retain the last observable v1 state with an honesty warning."""

    DISCLAIMER = "فقط آخرین وضعیت legacy وارد شد؛ تاریخچهٔ بازنویسی‌شده غیرقابل بازیابی است."

    def __init__(self, audit=None):
        self.audit = audit or ClinicalEngineAuditRepository()

    def import_once(self) -> int:
        imported = 0
        for legacy in self.audit.unimported_legacy_decisions():
            key = f"legacy-state:{legacy['id']}"
            event = self.audit.recommendation_by_key(key)
            if not event:
                run_id = self.audit.start_run(
                    patient_link_id=int(legacy["patient_link_id"]),
                    as_of_at=legacy.get("acted_at") or legacy.get("created_at") or "legacy-unknown",
                    engine_version="legacy-state-import-v1",
                    fact_snapshot={
                        "legacy_state_only": True,
                        "suggestion_log_id": int(legacy["id"]),
                        "disclaimer_fa": self.DISCLAIMER,
                    },
                    created_by="legacy-importer",
                )
                event_id = self.audit.append_recommendation_event(
                    run_id=run_id,
                    recommendation_key=key,
                    action_type="legacy_state_only",
                    event_type=RecommendationEventType.CREATED,
                    payload={
                        "suggestion_only": True,
                        "legacy_state_only": True,
                        "rule_code": legacy.get("rule_code"),
                        "text_fa": legacy.get("suggestion_text"),
                        "disclaimer_fa": self.DISCLAIMER,
                    },
                )
                self.audit.complete_run(
                    run_id,
                    status=RunStatus.COMPLETED,
                    summary={"legacy_state_only": True, "imported_rows": 1},
                )
            else:
                event_id = int(event["id"])
            status = str(legacy["status"]).lower()
            decision = (
                ClinicalDecision.ACCEPTED
                if status == "accepted"
                else ClinicalDecision.DISMISSED
            )
            note = (legacy.get("note") or "").strip()
            reason_text = f"{note} — {self.DISCLAIMER}" if note else self.DISCLAIMER
            self.audit.append_current_decision(
                recommendation_event_id=event_id,
                patient_link_id=int(legacy["patient_link_id"]),
                decision=decision,
                actor_user_id=None,
                actor_username=legacy.get("acted_by") or "legacy-unknown",
                expected_current_event_id=None,
                reason_code="OTHER",
                reason_text=reason_text,
                legacy_source_suggestion_log_id=int(legacy["id"]),
            )
            imported += 1
        return imported
