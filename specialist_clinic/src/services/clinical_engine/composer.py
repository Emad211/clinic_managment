"""Pure suggestion-only recommendation composition for Clinical Engine v2."""

from __future__ import annotations

from typing import Any

from src.domain.clinical_engine import (
    ActionType,
    CompiledRule,
    EvaluationResult,
    Presentation,
    Recommendation,
    RuleOutcome,
)


_PRESENTATION = {
    ActionType.REDFLAG: Presentation.INTERRUPTIVE,
    ActionType.SAFETY_ALERT: Presentation.PROMINENT,
}


def recommendation_payload(
    recommendation: Recommendation | None,
    *,
    title_fa: str | None = None,
    semantic_key: str | None = None,
    merged_rule_codes: tuple[str, ...] = (),
    merged_titles: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if recommendation is None:
        return None
    payload = {
        "recommendation_key": recommendation.recommendation_key,
        "action_type": recommendation.action_type.value,
        "text_fa": recommendation.text_fa,
        "suggestion_only": recommendation.suggestion_only,
        "requires_clinician_confirmation": recommendation.requires_clinician_confirmation,
        "presentation": recommendation.presentation.value,
        "may_create_internal_task": recommendation.may_create_internal_task,
    }
    if title_fa is not None:
        payload["title_fa"] = title_fa
    if semantic_key is not None:
        payload["semantic_key"] = semantic_key
    if merged_rule_codes:
        payload["merged_rule_codes"] = list(merged_rule_codes)
        payload["merged_titles"] = list(merged_titles)
    return payload


class RecommendationComposer:
    """Create inert DTOs only; never prescribes, mutates, messages, or creates tasks."""

    def compose(
        self, compiled: CompiledRule, result: EvaluationResult
    ) -> Recommendation | None:
        if result.outcome is not RuleOutcome.FIRED:
            return None
        definition = compiled.definition
        policy = definition.recommendation
        required = {
            "text_fa", "requires_clinician_confirmation", "may_create_internal_task"
        }
        if not hasattr(policy, "keys") or not required.issubset(policy.keys()):
            return None
        return Recommendation(
            recommendation_key=(
                f"rec:{definition.rule_code}:{definition.version}"
            ),
            action_type=definition.action_type,
            text_fa=str(policy["text_fa"]),
            suggestion_only=True,
            requires_clinician_confirmation=bool(
                policy["requires_clinician_confirmation"]
            ),
            presentation=_PRESENTATION.get(
                definition.action_type, Presentation.NON_INTERRUPTIVE
            ),
            may_create_internal_task=bool(policy["may_create_internal_task"]),
        )
