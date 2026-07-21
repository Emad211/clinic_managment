"""Deterministic four-state evaluator for compiled Clinical Engine v2 rules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from numbers import Real
from typing import Any

from src.domain.clinical_engine import (
    AllExpression,
    AnyExpression,
    ClinicalFact,
    CompiledRule,
    ConflictStatus,
    DataIssue,
    EvaluationResult,
    FactSnapshot,
    FactStatus,
    FreshnessStatus,
    LeafExpression,
    NotExpression,
    PredicateResult,
    PredicateState,
    RuleOutcome,
    VerificationStatus,
)
from src.common.utils import IRAN_TZ


_VERIFICATION_RANK = {
    VerificationStatus.UNVERIFIED: 0,
    VerificationStatus.PROVISIONAL: 1,
    VerificationStatus.CONFIRMED: 2,
}
_MISSING_STATUSES = {
    FactStatus.UNKNOWN: "UNKNOWN",
    FactStatus.NOT_ASKED: "NOT_ASKED",
    FactStatus.NOT_APPLICABLE: "UNKNOWN",
    FactStatus.ENTERED_IN_ERROR: "UNKNOWN",
}
_UNIT_ALIASES = {
    "mmHg": "mm[Hg]",
    "mL/min/1.73m2": "mL/min/{1.73_m2}",
    "mL/min/1.73 m2": "mL/min/{1.73_m2}",
    "kg/m²": "kg/m2",
}


def combine_all(states: Sequence[PredicateState]) -> PredicateState:
    if PredicateState.ERROR in states:
        return PredicateState.ERROR
    if PredicateState.FALSE in states:
        return PredicateState.FALSE
    if PredicateState.UNKNOWN in states:
        return PredicateState.UNKNOWN
    return PredicateState.TRUE


def combine_any(states: Sequence[PredicateState]) -> PredicateState:
    if PredicateState.ERROR in states:
        return PredicateState.ERROR
    if PredicateState.TRUE in states:
        return PredicateState.TRUE
    if PredicateState.UNKNOWN in states:
        return PredicateState.UNKNOWN
    return PredicateState.FALSE


def negate(state: PredicateState) -> PredicateState:
    return {
        PredicateState.TRUE: PredicateState.FALSE,
        PredicateState.FALSE: PredicateState.TRUE,
        PredicateState.UNKNOWN: PredicateState.UNKNOWN,
        PredicateState.ERROR: PredicateState.ERROR,
    }[state]


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _typed_equal(left: Any, right: Any) -> bool | None:
    if _is_number(left) and _is_number(right):
        return float(left) == float(right)
    if type(left) is not type(right):
        return None
    return left == right


def _local_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(IRAN_TZ).replace(tzinfo=None)
    return value


def _age_seconds(as_of_at: datetime, effective_at: datetime) -> float:
    return (_local_naive(as_of_at) - _local_naive(effective_at)).total_seconds()


def _unit(value: str | None) -> str | None:
    return _UNIT_ALIASES.get(value, value)


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def data_issue_payload(issue: DataIssue) -> dict[str, str]:
    return {
        "fact_key": issue.fact_key,
        "issue": issue.issue,
        "message_fa": issue.message_fa,
    }


def predicate_trace_payload(predicate: PredicateResult) -> dict[str, Any]:
    return {
        "node_id": predicate.node_id,
        "kind": predicate.kind,
        "state": predicate.state.value,
        "message_fa": predicate.message or "",
        "fact_ids": list(predicate.fact_ids),
        "actual": _json_value(predicate.actual),
        "expected": _json_value(predicate.expected),
        "reason_code": predicate.reason_code,
        "children": [predicate_trace_payload(child) for child in predicate.children],
    }


def evaluation_payload(result: EvaluationResult) -> dict[str, Any]:
    error = None
    if result.error_code:
        error = {
            "code": result.error_code,
            "message": result.error_message or result.predicate.message or result.error_code,
        }
    return {
        "rule_code": result.rule_code,
        "rule_version": result.rule_version,
        "phase": result.phase.value,
        "predicate_state": result.predicate.state.value,
        "outcome": result.outcome.value,
        "trace": predicate_trace_payload(result.predicate),
        "data_issues": [data_issue_payload(issue) for issue in result.data_issues],
        "suppression": None,
        "recommendations": [],
        "error": error,
    }


class RuleEvaluator:
    """Evaluate immutable rules against one frozen snapshot; owns no clock or I/O."""

    def evaluate(self, compiled: CompiledRule, snapshot: FactSnapshot) -> EvaluationResult:
        definition = compiled.definition
        policies = {item["key"]: item for item in definition.required_facts}
        try:
            eligibility = self.evaluate_expression(
                definition.eligibility, snapshot, policies=policies, kind="ELIGIBILITY"
            )
            if eligibility.state is PredicateState.FALSE:
                return self._result(compiled, RuleOutcome.NOT_APPLICABLE, eligibility)
            if eligibility.state is PredicateState.UNKNOWN:
                return self._result(compiled, RuleOutcome.NEEDS_DATA, eligibility)
            if eligibility.state is PredicateState.ERROR:
                return self._result(compiled, RuleOutcome.ERROR, eligibility,
                                    error_code=eligibility.reason_code or "ELIGIBILITY_ERROR")

            required_outcome, required_issues = self._check_required_facts(
                definition.required_facts, snapshot
            )
            if required_outcome is not None:
                required_trace = PredicateResult(
                    node_id="required-facts", state=PredicateState.UNKNOWN,
                    kind="REQUIRED_FACT", message="دادهٔ الزامی قابل استفاده نیست.",
                    fact_keys=tuple(sorted({item.fact_key for item in required_issues})),
                    reason_code="REQUIRED_FACT_UNUSABLE", data_issues=required_issues,
                )
                return self._result(compiled, required_outcome, required_trace,
                                    data_issues=required_issues)

            condition = self.evaluate_expression(
                definition.condition, snapshot, policies=policies
            )
            issues = self._dedupe_issues((*required_issues, *condition.data_issues))
            outcome = {
                PredicateState.TRUE: RuleOutcome.FIRED,
                PredicateState.FALSE: RuleOutcome.NOT_FIRED,
                PredicateState.UNKNOWN: RuleOutcome.NEEDS_DATA,
                PredicateState.ERROR: RuleOutcome.ERROR,
            }[condition.state]
            return self._result(
                compiled, outcome, condition, data_issues=issues,
                error_code=condition.reason_code if outcome is RuleOutcome.ERROR else None,
            )
        except Exception as exc:
            trace = PredicateResult(
                node_id="runtime-error", state=PredicateState.ERROR,
                kind="PREDICATE", message="خطای غیرمنتظره در ارزیابی قاعده.",
                reason_code="UNEXPECTED_EVALUATION_ERROR",
            )
            return self._result(
                compiled, RuleOutcome.ERROR, trace,
                error_code="UNEXPECTED_EVALUATION_ERROR", error_message=str(exc),
            )

    def evaluate_expression(
        self,
        expression,
        snapshot: FactSnapshot,
        *,
        policies: Mapping[str, Mapping[str, Any]] | None = None,
        kind: str | None = None,
    ) -> PredicateResult:
        policies = policies or {}
        if isinstance(expression, AllExpression):
            children = tuple(
                self.evaluate_expression(child, snapshot, policies=policies)
                for child in expression.children
            )
            return self._branch(expression.node_id, "ALL", combine_all, children, kind)
        if isinstance(expression, AnyExpression):
            children = tuple(
                self.evaluate_expression(child, snapshot, policies=policies)
                for child in expression.children
            )
            return self._branch(expression.node_id, "ANY", combine_any, children, kind)
        if isinstance(expression, NotExpression):
            child = self.evaluate_expression(expression.child, snapshot, policies=policies)
            return PredicateResult(
                node_id=expression.node_id, state=negate(child.state), kind=kind or "NOT",
                message="نقیض گزاره", fact_keys=child.fact_keys, fact_ids=child.fact_ids,
                reason_code=child.reason_code, data_issues=child.data_issues,
                children=(child,),
            )
        if isinstance(expression, LeafExpression):
            return self._leaf(expression, snapshot, policies.get(expression.fact), kind)
        raise TypeError(f"unsupported expression type: {type(expression).__name__}")

    def _leaf(self, expression: LeafExpression, snapshot: FactSnapshot,
              policy: Mapping[str, Any] | None, kind: str | None) -> PredicateResult:
        candidates = tuple(fact for fact in snapshot.facts if fact.key == expression.fact)
        selector = dict(expression.selector or {})
        aggregation = selector.get("aggregation", "single")
        selected, selector_issue = self._select(candidates, aggregation, selector, snapshot.as_of_at)
        if selector_issue:
            issue = DataIssue(expression.fact, selector_issue,
                              self._issue_message(selector_issue))
            return self._trace(expression, PredicateState.UNKNOWN, kind=kind,
                               facts=selected or candidates, reason=selector_issue,
                               issues=(issue,))
        if not selected and aggregation in {"count_within_days", "recently_completed"}:
            actual = 0 if aggregation == "count_within_days" else False
            state, reason = self._apply_operator(expression, actual, ())
            issues = ()
            if state is PredicateState.ERROR and reason:
                issues = (DataIssue(expression.fact, reason, self._issue_message(reason)),)
            return self._trace(expression, state, kind=kind, facts=(), actual=actual,
                               reason=reason, issues=issues)

        usable: list[ClinicalFact] = []
        issues: list[DataIssue] = []
        hard_errors: list[DataIssue] = []
        absent: list[ClinicalFact] = []
        for fact in selected:
            if fact.status is FactStatus.ABSENT:
                if fact.verification is VerificationStatus.CONFIRMED:
                    absent.append(fact)
                else:
                    issues.append(DataIssue(expression.fact, "UNVERIFIED",
                                            self._issue_message("UNVERIFIED")))
                continue
            if fact.status is not FactStatus.PRESENT:
                issue_code = _MISSING_STATUSES.get(fact.status, "UNKNOWN")
                if "SOURCE_UNAVAILABLE" in fact.warnings:
                    issue_code = "SOURCE_UNAVAILABLE"
                issues.append(DataIssue(expression.fact, issue_code,
                                        self._issue_message(issue_code)))
                continue
            if fact.value is None:
                hard_errors.append(DataIssue(expression.fact, "INVALID_TYPE",
                                              self._issue_message("INVALID_TYPE")))
                continue
            quality_issue = self._quality_issue(fact, policy, selector, snapshot.as_of_at)
            if quality_issue:
                issues.append(DataIssue(expression.fact, quality_issue,
                                        self._issue_message(quality_issue)))
            else:
                usable.append(fact)

        if hard_errors:
            issue_tuple = self._dedupe_issues(hard_errors)
            return self._trace(expression, PredicateState.ERROR, kind=kind,
                               facts=selected, reason="INVALID_TYPE", issues=issue_tuple)

        if not usable:
            if absent and not issues:
                return self._evaluate_absence(expression, absent, kind)
            issue_tuple = self._dedupe_issues(issues or (
                DataIssue(expression.fact, "MISSING", self._issue_message("MISSING")),
            ))
            return self._trace(expression, PredicateState.UNKNOWN, kind=kind,
                               facts=selected, reason=issue_tuple[0].issue,
                               issues=issue_tuple)

        if issues and aggregation in {"all", "count", "within_days",
                                      "count_within_days", "recently_completed"}:
            issue_tuple = self._dedupe_issues(issues)
            return self._trace(expression, PredicateState.UNKNOWN, kind=kind,
                               facts=selected, reason=issue_tuple[0].issue,
                               issues=issue_tuple)

        value = self._aggregate_values(usable, aggregation, selector, snapshot.as_of_at)
        state, reason = self._apply_operator(expression, value, usable)
        if state is PredicateState.ERROR and reason:
            issues.append(DataIssue(expression.fact, reason, self._issue_message(reason)))
        return self._trace(
            expression, state, kind=kind, facts=usable, actual=value,
            reason=reason, issues=self._dedupe_issues(issues),
        )

    def _select(self, facts, aggregation, selector, as_of_at):
        if not facts:
            return (), "MISSING"
        if aggregation == "single":
            if len(facts) != 1:
                return facts, "CONFLICTING"
            return facts, None
        if aggregation == "latest":
            latest_time = max(_local_naive(fact.effective_at) for fact in facts)
            latest = tuple(
                fact for fact in facts
                if _local_naive(fact.effective_at) == latest_time
            )
            if len(latest) != 1:
                return latest, "CONFLICTING"
            return latest, None
        if aggregation in {"within_days", "count_within_days", "recently_completed"}:
            days = selector.get("within_days")
            if days is None:
                return facts, "INVALID_SELECTOR"
            selected = tuple(
                fact for fact in facts
                if 0 <= _age_seconds(as_of_at, fact.effective_at) <= days * 86400
            )
            if selected:
                return selected, None
            if aggregation in {"count_within_days", "recently_completed"}:
                return (), None
            return facts, "STALE"
        if aggregation in {"all", "count"}:
            return facts, None
        return facts, "INVALID_SELECTOR"

    def _quality_issue(self, fact, policy, selector, as_of_at):
        if fact.verification in {VerificationStatus.REFUTED}:
            return "UNVERIFIED"
        minimum = (policy or {}).get("minimum_verification")
        if minimum:
            required = _VERIFICATION_RANK[VerificationStatus(minimum)]
            actual = _VERIFICATION_RANK.get(fact.verification, -1)
            if actual < required:
                return "UNVERIFIED"
        elif fact.verification is VerificationStatus.UNVERIFIED and not selector.get("allow_unverified", False):
            return "UNVERIFIED"

        if fact.conflict is not ConflictStatus.NONE and not selector.get("allow_conflicting", False):
            return "CONFLICTING"

        max_age = (policy or {}).get("max_age_days")
        if fact.freshness is FreshnessStatus.STALE and not selector.get("allow_stale", False):
            return "STALE"
        if max_age is not None and not selector.get("allow_stale", False):
            age_seconds = _age_seconds(as_of_at, fact.effective_at)
            if age_seconds < 0 or age_seconds > int(max_age) * 86400:
                return "STALE"
        elif _age_seconds(as_of_at, fact.effective_at) < 0:
            return "STALE"
        return None

    def _aggregate_values(self, facts, aggregation, selector, as_of_at):
        values = [fact.value for fact in facts]
        if aggregation in {"count", "count_within_days"}:
            return len(values)
        if aggregation == "recently_completed":
            return len(values) >= int(selector.get("minimum_count", 1))
        if aggregation in {"all", "within_days"}:
            return values
        return values[0]

    def _apply_operator(self, expression, actual, facts):
        op = expression.op
        expected = expression.value
        if expression.unit is not None:
            if any(_unit(fact.unit) != _unit(expression.unit) for fact in facts):
                return PredicateState.ERROR, "UNIT_MISMATCH"
        if op == "exists":
            return PredicateState.TRUE, None
        if op == "truthy":
            if not isinstance(actual, bool):
                return PredicateState.ERROR, "INVALID_TYPE"
            return (PredicateState.TRUE if actual else PredicateState.FALSE), None
        if op in {"has", "not_has"}:
            if not isinstance(actual, (list, tuple, set, frozenset)):
                return PredicateState.ERROR, "INVALID_TYPE"
            comparisons = tuple(_typed_equal(item, expected) for item in actual)
            if any(result is None for result in comparisons):
                return PredicateState.ERROR, "INVALID_TYPE"
            present = any(comparisons)
            if op == "not_has":
                present = not present
            return (PredicateState.TRUE if present else PredicateState.FALSE), None
        if op == "in":
            if not isinstance(expected, (list, tuple)):
                return PredicateState.ERROR, "INVALID_TYPE"
            comparisons = tuple(_typed_equal(actual, item) for item in expected)
            if any(result is None for result in comparisons):
                return PredicateState.ERROR, "INVALID_TYPE"
            return (PredicateState.TRUE if any(comparisons) else PredicateState.FALSE), None
        if op in {"==", "!="}:
            equal = _typed_equal(actual, expected)
            if equal is None:
                return PredicateState.ERROR, "INVALID_TYPE"
            if op == "!=":
                equal = not equal
            return (PredicateState.TRUE if equal else PredicateState.FALSE), None
        if op == "between":
            if not _is_number(actual) or not isinstance(expected, (list, tuple)) or len(expected) != 2:
                return PredicateState.ERROR, "INVALID_TYPE"
            if not all(_is_number(item) for item in expected):
                return PredicateState.ERROR, "INVALID_TYPE"
            result = float(expected[0]) <= float(actual) <= float(expected[1])
            return (PredicateState.TRUE if result else PredicateState.FALSE), None
        if op in {">=", "<=", ">", "<"}:
            if not _is_number(actual) or not _is_number(expected):
                return PredicateState.ERROR, "INVALID_TYPE"
            left, right = float(actual), float(expected)
            result = {">=": left >= right, "<=": left <= right,
                      ">": left > right, "<": left < right}[op]
            return (PredicateState.TRUE if result else PredicateState.FALSE), None
        return PredicateState.ERROR, "UNSUPPORTED_OPERATOR"

    def _evaluate_absence(self, expression, facts, kind):
        if expression.op in {"exists", "truthy"}:
            return self._trace(expression, PredicateState.FALSE, kind=kind, facts=facts,
                               actual=None, reason="EXPLICIT_ABSENCE")
        if expression.op == "has":
            return self._trace(expression, PredicateState.FALSE, kind=kind, facts=facts,
                               actual=[], reason="EXPLICIT_ABSENCE")
        if expression.op == "not_has":
            return self._trace(expression, PredicateState.TRUE, kind=kind, facts=facts,
                               actual=[], reason="EXPLICIT_ABSENCE")
        issue = DataIssue(expression.fact, "UNKNOWN", self._issue_message("UNKNOWN"))
        return self._trace(expression, PredicateState.UNKNOWN, kind=kind, facts=facts,
                           reason="EXPLICIT_ABSENCE", issues=(issue,))

    def _check_required_facts(self, required_facts, snapshot):
        issues: list[DataIssue] = []
        outcome = None
        by_key = defaultdict(list)
        for fact in snapshot.facts:
            by_key[fact.key].append(fact)
        for policy in required_facts:
            if policy["criticality"] == "OPTIONAL":
                continue
            key = policy["key"]
            candidates = by_key.get(key, [])
            usable = any(
                (
                    fact.status is FactStatus.ABSENT
                    and fact.verification is VerificationStatus.CONFIRMED
                )
                or (
                    fact.status is FactStatus.PRESENT
                    and fact.value is not None
                    and self._quality_issue(fact, policy, {}, snapshot.as_of_at) is None
                )
                for fact in candidates
            )
            if usable:
                continue
            code = "MISSING" if not candidates else self._required_issue(candidates, policy, snapshot)
            issues.append(DataIssue(key, code, policy.get("prompt_fa") or self._issue_message(code)))
            policy_outcome = {
                "NEEDS_DATA": RuleOutcome.NEEDS_DATA,
                "NOT_APPLICABLE": RuleOutcome.NOT_APPLICABLE,
                "CONTINUE_WITH_WARNING": None,
            }[policy["on_unusable"]]
            if policy_outcome is RuleOutcome.NEEDS_DATA:
                outcome = RuleOutcome.NEEDS_DATA
            elif policy_outcome is RuleOutcome.NOT_APPLICABLE and outcome is None:
                outcome = RuleOutcome.NOT_APPLICABLE
        return outcome, self._dedupe_issues(issues)

    def _required_issue(self, facts, policy, snapshot):
        for fact in facts:
            if "SOURCE_UNAVAILABLE" in fact.warnings:
                return "SOURCE_UNAVAILABLE"
            if fact.status is FactStatus.NOT_ASKED:
                return "NOT_ASKED"
            if fact.status is FactStatus.PRESENT and fact.value is None:
                return "INVALID_TYPE"
            issue = self._quality_issue(fact, policy, {}, snapshot.as_of_at)
            if issue:
                return issue
        return "UNKNOWN"

    def _branch(self, node_id, branch_kind, combiner, children, override_kind):
        issues = self._dedupe_issues(issue for child in children for issue in child.data_issues)
        return PredicateResult(
            node_id=node_id, state=combiner([child.state for child in children]),
            kind=override_kind or branch_kind, message=branch_kind,
            fact_keys=tuple(sorted({key for child in children for key in child.fact_keys})),
            fact_ids=tuple(sorted({fid for child in children for fid in child.fact_ids})),
            data_issues=issues, children=children,
        )

    def _trace(self, expression, state, *, kind, facts, actual=None, reason=None, issues=()):
        return PredicateResult(
            node_id=expression.node_id, state=state, kind=kind or "PREDICATE",
            message=self._state_message(state, reason), fact_keys=(expression.fact,),
            fact_ids=tuple(fact.fact_id for fact in facts), actual=actual,
            expected=expression.value, reason_code=reason,
            data_issues=self._dedupe_issues(issues),
        )

    def _result(self, compiled, outcome, predicate, *, data_issues=(),
                error_code=None, error_message=None):
        issues = self._dedupe_issues((*predicate.data_issues, *data_issues))
        return EvaluationResult(
            rule_code=compiled.definition.rule_code,
            rule_version=compiled.definition.version,
            phase=compiled.definition.phase,
            outcome=outcome,
            predicate=predicate,
            data_issues=issues,
            missing_facts=tuple(sorted({item.fact_key for item in issues})),
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _dedupe_issues(issues):
        seen = set()
        result = []
        for issue in issues:
            key = (issue.fact_key, issue.issue)
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return tuple(result)

    @staticmethod
    def _issue_message(issue):
        return {
            "MISSING": "داده ثبت نشده است.",
            "UNKNOWN": "وضعیت داده نامشخص است.",
            "NOT_ASKED": "این مورد هنوز پرسیده نشده است.",
            "STALE": "داده از بازهٔ زمانی مجاز قدیمی‌تر است.",
            "UNVERIFIED": "داده تأیید کافی ندارد.",
            "CONFLICTING": "داده‌های متعارض نیازمند بررسی هستند.",
            "UNIT_MISMATCH": "واحد داده با واحد قاعده سازگار نیست.",
            "INVALID_TYPE": "نوع داده برای این عملگر معتبر نیست.",
            "SOURCE_UNAVAILABLE": "منبع داده در دسترس نیست.",
            "INVALID_SELECTOR": "انتخاب‌گر قاعده معتبر نیست.",
        }.get(issue, "داده قابل استفاده نیست.")

    @staticmethod
    def _state_message(state, reason):
        if state is PredicateState.TRUE:
            return "شرط برقرار است."
        if state is PredicateState.FALSE:
            return "شرط برقرار نیست."
        if state is PredicateState.UNKNOWN:
            return RuleEvaluator._issue_message(reason or "UNKNOWN")
        return RuleEvaluator._issue_message(reason or "INVALID_TYPE")
