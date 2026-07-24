"""Executable applicability scope for Clinical Engine v2 rules.

The original predicate evaluator remains responsible for fact expressions. This boundary
runs first and turns rule metadata into deterministic applicability semantics:

* a definite mismatch is ``NOT_APPLICABLE``;
* missing scope data is ``NEEDS_DATA``;
* a missing or malformed evaluation context is ``ERROR``.
"""
from __future__ import annotations

from dataclasses import replace
from numbers import Real
from typing import Any, Mapping

from src.domain.clinical_engine import (
    ClinicalFact,
    DataIssue,
    EvaluationResult,
    FactSnapshot,
    FactStatus,
    PredicateResult,
    PredicateState,
    RuleOutcome,
    VerificationStatus,
)
from src.domain.clinical_engine.context import EvaluationMode
from src.services.clinical_engine.evaluator import RuleEvaluator as PredicateRuleEvaluator


_OUTPATIENT_SETTINGS = {
    "primary_care",
    "specialty_clinic",
    "urgent_care",
    "telehealth",
}


def _scope_result(
    compiled,
    outcome: RuleOutcome,
    predicate: PredicateResult,
    *,
    issues: tuple[DataIssue, ...] = (),
    error_code: str | None = None,
) -> EvaluationResult:
    return EvaluationResult(
        rule_code=compiled.definition.rule_code,
        rule_version=compiled.definition.version,
        phase=compiled.definition.phase,
        outcome=outcome,
        predicate=predicate,
        data_issues=issues,
        missing_facts=tuple(sorted({item.fact_key for item in issues})),
        error_code=error_code,
        error_message=predicate.message if error_code else None,
    )


def _issue(fact_key: str, code: str, message: str) -> DataIssue:
    return DataIssue(fact_key=fact_key, issue=code, message_fa=message)


def _usable_single(
    snapshot: FactSnapshot,
    key: str,
) -> tuple[ClinicalFact | None, DataIssue | None]:
    candidates = [fact for fact in snapshot.facts if fact.key == key]
    if len(candidates) != 1:
        code = "MISSING" if not candidates else "CONFLICTING"
        return None, _issue(
            key,
            code,
            "دادهٔ لازم برای تعیین دامنهٔ قاعده موجود یا یکتا نیست.",
        )
    fact = candidates[0]
    if fact.status is FactStatus.ABSENT and fact.verification is VerificationStatus.CONFIRMED:
        return fact, None
    if (
        fact.status is not FactStatus.PRESENT
        or fact.value is None
        or fact.verification is VerificationStatus.UNVERIFIED
    ):
        return None, _issue(
            key,
            "SCOPE_DATA_UNUSABLE",
            "دادهٔ لازم برای تعیین دامنهٔ قاعده قابل اتکا نیست.",
        )
    return fact, None


class ContextualRuleEvaluator(PredicateRuleEvaluator):
    """Evaluate context/scope before eligibility, required facts and condition."""

    def evaluate(self, compiled, snapshot: FactSnapshot) -> EvaluationResult:
        scope = self.evaluate_scope(compiled, snapshot)
        if scope.state is PredicateState.FALSE:
            return _scope_result(compiled, RuleOutcome.NOT_APPLICABLE, scope)
        if scope.state is PredicateState.UNKNOWN:
            return _scope_result(
                compiled,
                RuleOutcome.NEEDS_DATA,
                scope,
                issues=scope.data_issues,
            )
        if scope.state is PredicateState.ERROR:
            return _scope_result(
                compiled,
                RuleOutcome.ERROR,
                scope,
                issues=scope.data_issues,
                error_code=scope.reason_code or "SCOPE_EVALUATION_ERROR",
            )

        raw = super().evaluate(compiled, snapshot)
        predicate = PredicateResult(
            node_id="rule-root",
            state=raw.predicate.state,
            kind="RULE",
            message="دامنهٔ کاربرد و شرط بالینی قاعده ارزیابی شدند.",
            fact_keys=tuple(sorted({*scope.fact_keys, *raw.predicate.fact_keys})),
            fact_ids=tuple(sorted({*scope.fact_ids, *raw.predicate.fact_ids})),
            actual=raw.predicate.actual,
            expected=raw.predicate.expected,
            reason_code=raw.predicate.reason_code,
            data_issues=raw.predicate.data_issues,
            children=(scope, raw.predicate),
        )
        return replace(raw, predicate=predicate)

    def evaluate_scope(self, compiled, snapshot: FactSnapshot) -> PredicateResult:
        context = getattr(snapshot, "evaluation_context", None)
        if context is None:
            issue = _issue(
                "context",
                "EVALUATION_CONTEXT_MISSING",
                "زمینهٔ اجرای بالینی مشخص نشده است.",
            )
            return PredicateResult(
                node_id="scope-context",
                state=PredicateState.ERROR,
                kind="SCOPE",
                message=issue.message_fa,
                reason_code=issue.issue,
                data_issues=(issue,),
            )
        if int(context.patient_link_id) != int(snapshot.patient_link_id):
            issue = _issue(
                "context",
                "EVALUATION_CONTEXT_PATIENT_MISMATCH",
                "زمینهٔ اجرا به بیمار دیگری تعلق دارد.",
            )
            return PredicateResult(
                node_id="scope-context",
                state=PredicateState.ERROR,
                kind="SCOPE",
                message=issue.message_fa,
                reason_code=issue.issue,
                data_issues=(issue,),
            )

        scope: Mapping[str, Any] = compiled.definition.scope
        children: list[PredicateResult] = []

        allowed_modes = set(scope.get("evaluation_modes") or (
            EvaluationMode.ENCOUNTER.value,
            EvaluationMode.LONGITUDINAL.value,
        ))
        children.append(self._match(
            "scope-mode",
            context.evaluation_mode.value in allowed_modes,
            actual=context.evaluation_mode.value,
            expected=sorted(allowed_modes),
            message_true="نوع اجرای موتور در دامنهٔ قاعده است.",
            message_false="این قاعده برای نوع اجرای فعلی کاربرد ندارد.",
            reason="EVALUATION_MODE_OUT_OF_SCOPE",
        ))

        allowed_settings = set(scope.get("care_settings") or ())
        setting_matches = (
            context.care_setting.value in allowed_settings
            or (
                "outpatient" in allowed_settings
                and context.care_setting.value in _OUTPATIENT_SETTINGS
            )
        )
        children.append(self._match(
            "scope-care-setting",
            setting_matches,
            actual=context.care_setting.value,
            expected=sorted(allowed_settings),
            message_true="محل ارائهٔ خدمت در دامنهٔ قاعده است.",
            message_false="این قاعده در محل ارائهٔ خدمت فعلی کاربرد ندارد.",
            reason="CARE_SETTING_OUT_OF_SCOPE",
        ))

        if context.evaluation_mode is EvaluationMode.ENCOUNTER:
            allowed_encounters = set(scope.get("encounter_types") or ())
            children.append(self._match(
                "scope-encounter-type",
                context.encounter_type.value in allowed_encounters,
                actual=context.encounter_type.value,
                expected=sorted(allowed_encounters),
                message_true="نوع encounter در دامنهٔ قاعده است.",
                message_false="این قاعده برای نوع encounter فعلی کاربرد ندارد.",
                reason="ENCOUNTER_TYPE_OUT_OF_SCOPE",
            ))

        required_reasons = set(scope.get("reason_codes") or ())
        if required_reasons:
            actual_reasons = set(context.reason_codes)
            children.append(self._match(
                "scope-reason-code",
                bool(required_reasons & actual_reasons),
                actual=sorted(actual_reasons),
                expected=sorted(required_reasons),
                message_true="علت مراجعه در دامنهٔ قاعده است.",
                message_false="علت مراجعهٔ فعلی در دامنهٔ قاعده نیست.",
                reason="REASON_CODE_OUT_OF_SCOPE",
            ))

        age_min = scope.get("age_min")
        age_max = scope.get("age_max")
        if age_min is not None or age_max is not None:
            age_fact, age_issue = _usable_single(snapshot, "demographic.age_years")
            if age_issue:
                children.append(self._unknown("scope-age", age_issue))
            elif not isinstance(age_fact.value, Real) or isinstance(age_fact.value, bool):
                children.append(self._error(
                    "scope-age",
                    _issue(
                        "demographic.age_years",
                        "INVALID_SCOPE_DATA_TYPE",
                        "سن بیمار برای تعیین دامنه عددی نیست.",
                    ),
                ))
            else:
                age = float(age_fact.value)
                matches = (
                    (age_min is None or age >= float(age_min))
                    and (age_max is None or age <= float(age_max))
                )
                children.append(self._match(
                    "scope-age",
                    matches,
                    actual=age,
                    expected={"minimum": age_min, "maximum": age_max},
                    message_true="سن بیمار در دامنهٔ قاعده است.",
                    message_false="سن بیمار خارج از دامنهٔ قاعده است.",
                    reason="AGE_OUT_OF_SCOPE",
                    fact=age_fact,
                ))

        allowed_sex = set(scope.get("sex") or ())
        if allowed_sex and "any" not in allowed_sex:
            sex_fact, sex_issue = _usable_single(snapshot, "demographic.sex")
            if sex_issue:
                children.append(self._unknown("scope-sex", sex_issue))
            else:
                sex = str(sex_fact.value).strip().lower()
                children.append(self._match(
                    "scope-sex",
                    sex in allowed_sex,
                    actual=sex,
                    expected=sorted(allowed_sex),
                    message_true="جنس ثبت‌شده در دامنهٔ قاعده است.",
                    message_false="جنس ثبت‌شده خارج از دامنهٔ قاعده است.",
                    reason="SEX_OUT_OF_SCOPE",
                    fact=sex_fact,
                ))

        required_conditions = set(scope.get("condition_codes") or ())
        if required_conditions:
            # A confirmed specific problem can establish positive applicability even
            # when the aggregate problem list has not yet been reconciled completely.
            # Completeness is still required before absence can be inferred.
            specific = [
                fact
                for code in sorted(required_conditions)
                for fact in snapshot.facts
                if fact.key == f"condition.{code}"
                and fact.status is FactStatus.PRESENT
                and bool(fact.value)
                and fact.verification is VerificationStatus.CONFIRMED
            ]
            if specific:
                matched = specific[0]
                children.append(self._match(
                    "scope-condition",
                    True,
                    actual=matched.key.removeprefix("condition."),
                    expected=sorted(required_conditions),
                    message_true="تشخیص لازم در پرونده موجود است.",
                    message_false="تشخیص لازم برای این قاعده در پرونده موجود نیست.",
                    reason="CONDITION_OUT_OF_SCOPE",
                    fact=matched,
                ))
            else:
                condition_fact, condition_issue = _usable_single(
                    snapshot, "condition.codes"
                )
                if condition_issue:
                    children.append(self._unknown("scope-condition", condition_issue))
                elif condition_fact.status is FactStatus.ABSENT:
                    children.append(self._match(
                        "scope-condition",
                        False,
                        actual=[],
                        expected=sorted(required_conditions),
                        message_true="تشخیص لازم در پرونده موجود است.",
                        message_false="تشخیص لازم برای این قاعده در پرونده موجود نیست.",
                        reason="CONDITION_OUT_OF_SCOPE",
                        fact=condition_fact,
                    ))
                elif not isinstance(
                    condition_fact.value, (list, tuple, set, frozenset)
                ):
                    children.append(self._error(
                        "scope-condition",
                        _issue(
                            "condition.codes",
                            "INVALID_SCOPE_DATA_TYPE",
                            "فهرست تشخیص‌ها ساختار معتبر ندارد.",
                        ),
                    ))
                else:
                    actual_conditions = {str(item) for item in condition_fact.value}
                    children.append(self._match(
                        "scope-condition",
                        bool(required_conditions & actual_conditions),
                        actual=sorted(actual_conditions),
                        expected=sorted(required_conditions),
                        message_true="تشخیص لازم در پرونده موجود است.",
                        message_false="تشخیص لازم برای این قاعده در پرونده موجود نیست.",
                        reason="CONDITION_OUT_OF_SCOPE",
                        fact=condition_fact,
                    ))

        states = [child.state for child in children]
        if PredicateState.ERROR in states:
            state = PredicateState.ERROR
        elif PredicateState.FALSE in states:
            state = PredicateState.FALSE
        elif PredicateState.UNKNOWN in states:
            state = PredicateState.UNKNOWN
        else:
            state = PredicateState.TRUE
        issues = tuple(
            issue for child in children for issue in child.data_issues
        )
        return PredicateResult(
            node_id="scope-root",
            state=state,
            kind="SCOPE",
            message={
                PredicateState.TRUE: "قاعده در زمینهٔ فعلی قابل ارزیابی است.",
                PredicateState.FALSE: "قاعده در زمینهٔ فعلی کاربرد ندارد.",
                PredicateState.UNKNOWN: "دادهٔ کافی برای تعیین دامنه وجود ندارد.",
                PredicateState.ERROR: "تعیین دامنهٔ قاعده با خطا متوقف شد.",
            }[state],
            fact_keys=tuple(sorted({
                key for child in children for key in child.fact_keys
            })),
            fact_ids=tuple(sorted({
                fact_id for child in children for fact_id in child.fact_ids
            })),
            reason_code={
                PredicateState.FALSE: next(
                    (child.reason_code for child in children
                     if child.state is PredicateState.FALSE),
                    "SCOPE_OUT_OF_SCOPE",
                ),
                PredicateState.UNKNOWN: "SCOPE_DATA_UNUSABLE",
                PredicateState.ERROR: "SCOPE_EVALUATION_ERROR",
            }.get(state),
            data_issues=issues,
            children=tuple(children),
        )

    @staticmethod
    def _match(
        node_id: str,
        matches: bool,
        *,
        actual,
        expected,
        message_true: str,
        message_false: str,
        reason: str,
        fact: ClinicalFact | None = None,
    ) -> PredicateResult:
        return PredicateResult(
            node_id=node_id,
            state=PredicateState.TRUE if matches else PredicateState.FALSE,
            kind="SCOPE",
            message=message_true if matches else message_false,
            fact_keys=(fact.key,) if fact else (),
            fact_ids=(fact.fact_id,) if fact else (),
            actual=actual,
            expected=expected,
            reason_code=None if matches else reason,
        )

    @staticmethod
    def _unknown(node_id: str, issue: DataIssue) -> PredicateResult:
        return PredicateResult(
            node_id=node_id,
            state=PredicateState.UNKNOWN,
            kind="SCOPE",
            message=issue.message_fa,
            fact_keys=(issue.fact_key,),
            reason_code=issue.issue,
            data_issues=(issue,),
        )

    @staticmethod
    def _error(node_id: str, issue: DataIssue) -> PredicateResult:
        return PredicateResult(
            node_id=node_id,
            state=PredicateState.ERROR,
            kind="SCOPE",
            message=issue.message_fa,
            fact_keys=(issue.fact_key,),
            reason_code=issue.issue,
            data_issues=(issue,),
        )
