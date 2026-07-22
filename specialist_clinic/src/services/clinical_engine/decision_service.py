"""Clinician decisions as append-only events; never execute clinical actions."""
from __future__ import annotations

from src.adapters.sqlite.clinical_engine_action_repo import (
    ClinicalEngineActionRepository,
)
from src.adapters.sqlite.clinical_engine_fact_repo import (
    ClinicalEngineFactRepository,
)
from src.adapters.sqlite.clinical_engine_runtime_repo import (
    ClinicalEngineRuntimeRepository,
)
from src.domain.clinical_engine import ClinicalDecision
from src.services.clinical_engine.runtime import (
    ClinicalEngineRuntimeError,
    ClinicalEngineRuntimeService,
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

    def __init__(
        self,
        *,
        facts=None,
        runtime=None,
        runtime_repo=None,
        action_repo=None,
    ):
        self.facts = facts or ClinicalEngineFactRepository()
        self.runtime_repo = runtime_repo or ClinicalEngineRuntimeRepository()
        self.action_repo = action_repo or ClinicalEngineActionRepository(
            runtime_repo=self.runtime_repo
        )
        self.runtime = runtime or ClinicalEngineRuntimeService(
            facts=self.facts,
            runtime_repo=self.runtime_repo,
            action_repo=self.action_repo,
        )

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
        try:
            contract = self.runtime.contract(patient_link_id)
        except ClinicalEngineRuntimeError as exc:
            raise ClinicalDecisionValidationError(
                "clinical runtime is not available for this patient"
            ) from exc
        if contract is None or contract.mode not in {"on_selected", "on"}:
            raise ClinicalDecisionValidationError(
                "v2 decisions are not enabled for this patient"
            )

        try:
            normalized_decision = ClinicalDecision(str(decision).upper())
        except ValueError as exc:
            raise ClinicalDecisionValidationError("invalid decision") from exc
        if normalized_decision not in _ALLOWED_DECISIONS:
            raise ClinicalDecisionValidationError(
                "only ACCEPTED, DISMISSED and DEFERRED are allowed"
            )
        actor = (actor_username or "").strip()
        if not actor:
            raise ClinicalDecisionValidationError(
                "actor_username is required"
            )
        normalized_reason = (reason_code or "").strip().upper() or None
        if normalized_reason and normalized_reason not in _REASON_CODES:
            raise ClinicalDecisionValidationError("invalid reason_code")
        text = (reason_text or "").strip() or None
        if text and len(text) > 500:
            raise ClinicalDecisionValidationError(
                "reason_text is too long"
            )
        if (
            normalized_decision is ClinicalDecision.DISMISSED
            and not normalized_reason
        ):
            raise ClinicalDecisionValidationError(
                "reason_code is required for dismissal"
            )

        context = self.runtime_repo.recommendation_context(
            recommendation_event_id,
            patient_link_id=patient_link_id,
        )
        if not context or not context["payload"].get(
            "suggestion_only", False
        ):
            raise ClinicalDecisionValidationError(
                "recommendation is unavailable or does not belong to this patient"
            )
        try:
            return self.action_repo.append_current_decision(
                recommendation_event_id=recommendation_event_id,
                patient_link_id=patient_link_id,
                decision=normalized_decision,
                actor_user_id=actor_user_id,
                actor_username=actor,
                expected_current_event_id=expected_current_event_id,
                mode=contract.mode,
                engine_version=contract.engine_version,
                ruleset_id=contract.ruleset_id,
                clinical_data_revision=contract.clinical_data_revision,
                reason_code=normalized_reason,
                reason_text=text,
            )
        except RuntimeError as exc:
            if str(exc) == "STALE_DECISION_STATE":
                raise ClinicalDecisionConflict(
                    "recommendation decision changed; reload before recording another decision"
                ) from exc
            if str(exc) == "STALE_RECOMMENDATION":
                raise ClinicalDecisionValidationError(
                    "patient data or rollout state changed after this recommendation; "
                    "reload and review the current run"
                ) from exc
            raise
