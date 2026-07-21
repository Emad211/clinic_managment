"""Fail-closed phase ordering and executable safety policy for engine v2."""

from __future__ import annotations

from dataclasses import dataclass, replace

from src.domain.clinical_engine import (
    ActionType,
    ClinicalPhase,
    CompiledRule,
    DataIssue,
    EvaluationResult,
    FactSnapshot,
    PredicateResult,
    PredicateState,
    RuleOutcome,
    RunStatus,
    Suppression,
)
from src.services.clinical_engine.evaluator import RuleEvaluator


_PHASE_ORDER = {
    ClinicalPhase.PREFLIGHT: 0,
    ClinicalPhase.SAFETY: 1,
    ClinicalPhase.ROUTINE: 2,
}


@dataclass(frozen=True, slots=True)
class SafetyEvaluation:
    compiled: CompiledRule
    result: EvaluationResult


@dataclass(frozen=True, slots=True)
class SafetyRun:
    evaluations: tuple[SafetyEvaluation, ...]
    status: RunStatus
    redflag_rule_codes: tuple[str, ...] = ()
    routine_outputs_blocked: bool = False


class SafetyKernel:
    """Evaluate all phases deterministically and abstain when safety is unclear."""

    def __init__(self, evaluator: RuleEvaluator | None = None):
        self.evaluator = evaluator or RuleEvaluator()

    def evaluate(
        self, compiled_rules: list[CompiledRule] | tuple[CompiledRule, ...],
        snapshot: FactSnapshot,
        *,
        safety_precheck_failed: bool = False,
    ) -> SafetyRun:
        indexed = list(enumerate(compiled_rules))
        ordered = [
            compiled for _, compiled in sorted(
                indexed,
                key=lambda item: (
                    _PHASE_ORDER[item[1].definition.phase], item[0]
                ),
            )
        ]
        guardrail_evaluations: list[SafetyEvaluation] = []
        routine_rules: list[CompiledRule] = []
        for compiled in ordered:
            if compiled.definition.phase is ClinicalPhase.ROUTINE:
                routine_rules.append(compiled)
                continue
            guardrail_evaluations.append(SafetyEvaluation(
                compiled, self._evaluate_rule(compiled, snapshot)
            ))

        redflag_codes = tuple(
            item.compiled.definition.rule_code
            for item in guardrail_evaluations
            if item.compiled.definition.action_type is ActionType.REDFLAG
            and item.result.outcome is RuleOutcome.FIRED
        )
        uncleared_redflags = tuple(
            item
            for item in guardrail_evaluations
            if item.compiled.definition.action_type is ActionType.REDFLAG
            and item.result.outcome is RuleOutcome.NEEDS_DATA
        )
        safety_failed = safety_precheck_failed or any(
            item.result.outcome is RuleOutcome.ERROR
            for item in guardrail_evaluations
        )

        routine_evaluations: list[SafetyEvaluation] = []
        for compiled in routine_rules:
            raw = self._evaluate_rule(compiled, snapshot)
            resolved, local_safety_error = self._apply_local_policy(
                compiled, raw, snapshot
            )
            safety_failed = safety_failed or local_safety_error
            routine_evaluations.append(SafetyEvaluation(compiled, resolved))

        if safety_failed:
            routine_evaluations = [
                SafetyEvaluation(item.compiled, self._suppress_if_fired(
                    item.result,
                    "SAFETY_SUBSYSTEM_FAILED",
                    "بررسی ایمنی کامل نشد؛ خروجی روتین متوقف شد.",
                ))
                for item in routine_evaluations
            ]
        elif redflag_codes:
            caused_by = redflag_codes[0]
            routine_evaluations = [
                SafetyEvaluation(item.compiled, self._suppress_if_fired(
                    item.result,
                    "ACTIVE_REDFLAG",
                    "به دلیل هشدار فوری فعال، خروجی روتین متوقف شد.",
                    caused_by_rule_code=caused_by,
                ))
                for item in routine_evaluations
            ]
        elif uncleared_redflags:
            routine_evaluations = [
                SafetyEvaluation(item.compiled, self._needs_data_if_fired(
                    item.result, uncleared_redflags
                ))
                for item in routine_evaluations
            ]

        evaluations = tuple((*guardrail_evaluations, *routine_evaluations))
        if safety_failed:
            status = RunStatus.SAFETY_FAILED
        elif any(
            item.result.outcome is RuleOutcome.ERROR
            for item in routine_evaluations
        ):
            status = RunStatus.COMPLETED_WITH_ERRORS
        else:
            status = RunStatus.COMPLETED
        return SafetyRun(
            evaluations=evaluations,
            status=status,
            redflag_rule_codes=redflag_codes,
            routine_outputs_blocked=bool(
                safety_failed or redflag_codes or uncleared_redflags
            ),
        )

    def _apply_local_policy(self, compiled, result, snapshot):
        if result.outcome is not RuleOutcome.FIRED:
            return result, False
        policy = compiled.definition.safety
        redflag_exclusions = getattr(
            policy, "redflag_exclusions", policy.get("redflag_exclusions", ())
            if hasattr(policy, "get") else ()
        )
        hard_exclusions = getattr(
            policy, "hard_exclusions", policy.get("hard_exclusions", ())
            if hasattr(policy, "get") else ()
        )
        if not redflag_exclusions and not hard_exclusions:
            return result, False
        fact_policies = {
            item["key"]: item for item in compiled.definition.required_facts
        }
        redflag_checks = tuple(
            self._evaluate_safety_expression(
                expression, snapshot, policies=fact_policies, kind="SAFETY"
            )
            for expression in redflag_exclusions
        )
        hard_checks = tuple(
            (
                exclusion,
                self._evaluate_safety_expression(
                    exclusion.condition, snapshot,
                    policies=fact_policies, kind="SAFETY",
                ),
            )
            for exclusion in hard_exclusions
        )
        checks = (*redflag_checks, *(item[1] for item in hard_checks))
        if any(item.state is PredicateState.ERROR for item in checks):
            trace = self._safety_trace(checks, PredicateState.ERROR)
            return self._with_safety_trace(
                result, trace, RuleOutcome.ERROR,
                error_code="SAFETY_EVALUATION_ERROR",
                error_message="خطا در ارزیابی گاردریل ایمنی قاعده.",
            ), True

        active_redflag = next(
            (item for item in redflag_checks if item.state is PredicateState.TRUE),
            None,
        )
        active_hard = next(
            (
                (exclusion, check)
                for exclusion, check in hard_checks
                if check.state is PredicateState.TRUE
            ),
            None,
        )
        if active_redflag or active_hard:
            trace = self._safety_trace(checks, PredicateState.FALSE)
            if active_redflag:
                suppression = Suppression(
                    reason_code="ACTIVE_REDFLAG",
                    message_fa="گاردریل هشدار فوری این قاعده فعال است.",
                )
            else:
                exclusion, _ = active_hard
                suppression = Suppression(
                    reason_code="HARD_SAFETY",
                    message_fa=exclusion.message_fa,
                )
            return self._with_safety_trace(
                result, trace, RuleOutcome.SUPPRESSED,
                suppression=suppression,
            ), False

        if any(item.state is PredicateState.UNKNOWN for item in checks):
            trace = self._safety_trace(checks, PredicateState.UNKNOWN)
            return self._with_safety_trace(
                result, trace, RuleOutcome.NEEDS_DATA
            ), False

        trace = self._safety_trace(checks, PredicateState.TRUE)
        return self._with_safety_trace(result, trace, result.outcome), False

    def _evaluate_rule(self, compiled, snapshot):
        try:
            return self.evaluator.evaluate(compiled, snapshot)
        except Exception as exc:
            predicate = PredicateResult(
                node_id="runtime-error",
                state=PredicateState.ERROR,
                kind="PREDICATE",
                message="خطای غیرمنتظره در ارزیابی قاعده.",
                reason_code="UNEXPECTED_EVALUATION_ERROR",
            )
            return EvaluationResult(
                rule_code=compiled.definition.rule_code,
                rule_version=compiled.definition.version,
                phase=compiled.definition.phase,
                outcome=RuleOutcome.ERROR,
                predicate=predicate,
                error_code="UNEXPECTED_EVALUATION_ERROR",
                error_message=str(exc),
            )

    def _evaluate_safety_expression(self, expression, snapshot, **kwargs):
        try:
            return self.evaluator.evaluate_expression(expression, snapshot, **kwargs)
        except Exception:
            return PredicateResult(
                node_id=getattr(expression, "node_id", "safety-runtime-error"),
                state=PredicateState.ERROR,
                kind="SAFETY",
                message="خطای غیرمنتظره در ارزیابی گاردریل ایمنی.",
                reason_code="UNEXPECTED_SAFETY_ERROR",
            )

    @staticmethod
    def _safety_trace(checks, state):
        issues = SafetyKernel._dedupe_issues(
            issue for check in checks for issue in check.data_issues
        )
        return PredicateResult(
            node_id="safety-root",
            state=state,
            kind="SAFETY",
            message={
                PredicateState.TRUE: "گاردریل‌های ایمنی برقرارند.",
                PredicateState.FALSE: "یک گاردریل ایمنی فعال است.",
                PredicateState.UNKNOWN: "دادهٔ کافی برای تأیید ایمنی وجود ندارد.",
                PredicateState.ERROR: "ارزیابی گاردریل ایمنی ناموفق بود.",
            }[state],
            fact_keys=tuple(sorted({
                key for check in checks for key in check.fact_keys
            })),
            fact_ids=tuple(sorted({
                fact_id for check in checks for fact_id in check.fact_ids
            })),
            reason_code={
                PredicateState.FALSE: "SAFETY_EXCLUSION_ACTIVE",
                PredicateState.UNKNOWN: "SAFETY_NOT_CLEARED",
                PredicateState.ERROR: "SAFETY_EVALUATION_ERROR",
            }.get(state),
            data_issues=issues,
            children=tuple(checks),
        )

    @staticmethod
    def _with_safety_trace(
        result, safety_trace, outcome, *, suppression=None,
        error_code=None, error_message=None,
    ):
        effective_state = (
            result.predicate.state
            if outcome is RuleOutcome.SUPPRESSED
            else safety_trace.state
            if outcome in {RuleOutcome.NEEDS_DATA, RuleOutcome.ERROR}
            else result.predicate.state
        )
        issues = SafetyKernel._dedupe_issues((
            *result.data_issues, *safety_trace.data_issues
        ))
        predicate = PredicateResult(
            node_id="rule-root",
            state=effective_state,
            kind="RULE",
            message="شرط بالینی و گاردریل‌های ایمنی ارزیابی شدند.",
            fact_keys=tuple(sorted({
                *result.predicate.fact_keys, *safety_trace.fact_keys
            })),
            fact_ids=tuple(sorted({
                *result.predicate.fact_ids, *safety_trace.fact_ids
            })),
            reason_code=(
                suppression.reason_code if suppression
                else safety_trace.reason_code
            ),
            data_issues=issues,
            children=(result.predicate, safety_trace),
        )
        return replace(
            result,
            outcome=outcome,
            predicate=predicate,
            data_issues=issues,
            missing_facts=tuple(sorted({item.fact_key for item in issues})),
            suppression=suppression,
            suppression_reasons=(suppression.reason_code,) if suppression else (),
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _suppress_if_fired(
        result, reason_code, message_fa, *, caused_by_rule_code=None
    ):
        if result.outcome is not RuleOutcome.FIRED:
            return result
        suppression = Suppression(
            reason_code=reason_code,
            message_fa=message_fa,
            caused_by_rule_code=caused_by_rule_code,
        )
        return replace(
            result,
            outcome=RuleOutcome.SUPPRESSED,
            suppression=suppression,
            suppression_reasons=(reason_code,),
        )

    @staticmethod
    def _needs_data_if_fired(result, uncleared_redflags):
        if result.outcome is not RuleOutcome.FIRED:
            return result
        issues = SafetyKernel._dedupe_issues((
            *result.data_issues,
            *(
                issue
                for item in uncleared_redflags
                for issue in item.result.data_issues
            ),
        ))
        safety_children = tuple(
            item.result.predicate for item in uncleared_redflags
        )
        predicate = PredicateResult(
            node_id="preflight-clearance",
            state=PredicateState.UNKNOWN,
            kind="SAFETY",
            message="هشدار فوری به دلیل دادهٔ ناکافی قابل رد نیست.",
            fact_keys=tuple(sorted({
                key for child in safety_children for key in child.fact_keys
            })),
            fact_ids=tuple(sorted({
                fact_id for child in safety_children for fact_id in child.fact_ids
            })),
            reason_code="SAFETY_NOT_CLEARED",
            data_issues=issues,
            children=(result.predicate, *safety_children),
        )
        return replace(
            result,
            outcome=RuleOutcome.NEEDS_DATA,
            predicate=predicate,
            data_issues=issues,
            missing_facts=tuple(sorted({item.fact_key for item in issues})),
        )

    @staticmethod
    def _dedupe_issues(issues):
        seen = set()
        result = []
        for issue in issues:
            if not isinstance(issue, DataIssue):
                continue
            key = (issue.fact_key, issue.issue)
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return tuple(result)
