"""Deterministic, conservative conflict handling for Clinical Engine v2."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Iterable

from src.domain.clinical_engine import (
    ResolvedEvaluation,
    RuleOutcome,
    RuleSeverity,
    Suppression,
)


_SEVERITY_ORDER = {
    RuleSeverity.CRITICAL: 0,
    RuleSeverity.URGENT: 1,
    RuleSeverity.WARN: 2,
    RuleSeverity.INFO: 3,
}


class ConflictResolver:
    """Deduplicate only explicit semantic equivalents and expose conflicts.

    The resolver deliberately does not infer that two clinically worded actions
    are equivalent.  Only a shared, non-empty ``semantic_key`` permits merging.
    A shared key with different action types is treated as a ruleset defect and
    every involved recommendation is withheld.
    """

    def resolve(self, evaluations: Iterable[object]) -> tuple[ResolvedEvaluation, ...]:
        resolved = [
            ResolvedEvaluation(item.compiled, item.result)
            for item in evaluations
        ]
        groups: dict[str, list[int]] = defaultdict(list)
        for index, item in enumerate(resolved):
            semantic_key = (item.compiled.definition.semantic_key or "").strip()
            if semantic_key and item.result.outcome is RuleOutcome.FIRED:
                groups[semantic_key].append(index)

        for semantic_key in sorted(groups):
            indexes = groups[semantic_key]
            if len(indexes) < 2:
                continue
            action_types = {
                resolved[index].compiled.definition.action_type for index in indexes
            }
            if len(action_types) != 1:
                for index in indexes:
                    resolved[index] = self._suppressed(
                        resolved[index],
                        reason_code="UNRESOLVED_CONFLICT",
                        message_fa=(
                            "برای این موضوع، قواعد به اقدام‌های ناسازگار رسیده‌اند؛ "
                            "هیچ پیشنهادی نمایش داده نمی‌شود."
                        ),
                    )
                continue

            ordered = sorted(indexes, key=lambda index: self._rank(resolved[index]))
            winner_index = ordered[0]
            winner = resolved[winner_index]
            all_items = [resolved[index] for index in ordered]
            resolved[winner_index] = replace(
                winner,
                merged_rule_codes=tuple(
                    item.compiled.definition.rule_code for item in all_items
                ),
                merged_titles=tuple(
                    item.compiled.definition.title for item in all_items
                ),
            )
            winner_code = winner.compiled.definition.rule_code
            for index in ordered[1:]:
                resolved[index] = self._suppressed(
                    resolved[index],
                    reason_code="DEDUPLICATED",
                    message_fa="این پیشنهاد با پیشنهاد معادلِ با اولویت بالاتر ادغام شد.",
                    caused_by_rule_code=winner_code,
                )
        return tuple(resolved)

    @staticmethod
    def _rank(item: ResolvedEvaluation) -> tuple[int, int, str, str]:
        definition = item.compiled.definition
        return (
            _SEVERITY_ORDER[definition.severity],
            definition.priority,
            definition.rule_code,
            definition.version,
        )

    @staticmethod
    def _suppressed(
        item: ResolvedEvaluation,
        *,
        reason_code: str,
        message_fa: str,
        caused_by_rule_code: str | None = None,
    ) -> ResolvedEvaluation:
        suppression = Suppression(
            reason_code=reason_code,
            message_fa=message_fa,
            caused_by_rule_code=caused_by_rule_code,
        )
        return replace(
            item,
            result=replace(
                item.result,
                outcome=RuleOutcome.SUPPRESSED,
                suppression=suppression,
                suppression_reasons=tuple(sorted({
                    *item.result.suppression_reasons, reason_code,
                })),
            ),
        )
