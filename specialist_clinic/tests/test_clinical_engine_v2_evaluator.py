"""PR-05 executable semantics for the four-state Clinical Engine v2 evaluator."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

import pytest
from jsonschema import Draft202012Validator, FormatChecker


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.domain.clinical_engine import (
    ActionType,
    AllExpression,
    AnyExpression,
    ClinicalFact,
    ClinicalPhase,
    CompiledRule,
    ConflictStatus,
    FactKind,
    FactSnapshot,
    FactSource,
    FactStatus,
    FreshnessStatus,
    LeafExpression,
    NotExpression,
    PredicateState,
    RuleDefinition,
    RuleOutcome,
    RuleSeverity,
    VerificationStatus,
)
from src.services.clinical_engine.evaluator import (
    RuleEvaluator,
    combine_all,
    combine_any,
    evaluation_payload,
    negate,
)


AS_OF = datetime(2026, 7, 21, 12, 0, 0)


def fact(
    key="test.value", value=True, *, status=FactStatus.PRESENT,
    effective_at=AS_OF, unit=None, verification=VerificationStatus.CONFIRMED,
    freshness=FreshnessStatus.UNKNOWN, conflict=ConflictStatus.NONE, fact_id="fact-1",
    warnings=(),
):
    return ClinicalFact(
        schema_version="2.0", fact_id=fact_id, patient_link_id=1,
        kind=FactKind.OBSERVATION, key=key, status=status, value=value,
        effective_at=effective_at, recorded_at=effective_at,
        source=FactSource("pytest", fact_id), verification=verification,
        freshness=freshness, conflict=conflict, unit=unit, warnings=tuple(warnings),
    )


def snapshot(*facts):
    return FactSnapshot("2.0", 1, AS_OF, tuple(facts), "snapshot-hash")


def leaf(key="test.value", op="truthy", value=None, *, selector=None, unit=None, node="condition"):
    return LeafExpression(node, key, op, value=value, unit=unit,
                          selector=selector or {"aggregation": "single"})


def compiled(condition, *, eligibility=None, required=None, phase=ClinicalPhase.ROUTINE):
    eligibility = eligibility or leaf("scope.allowed", "truthy", node="eligibility")
    required = required if required is not None else (
        {"key": "scope.allowed", "criticality": "REQUIRED", "max_age_days": None,
         "minimum_verification": "CONFIRMED", "on_unusable": "NEEDS_DATA",
         "prompt_fa": "دامنه را مشخص کنید."},
    )
    definition = RuleDefinition(
        schema_version="2.0", dsl_version="2.0", rule_code="TEST-EVAL-01",
        version="2.0.0", title="Evaluator test", phase=phase,
        action_type=ActionType.EDUCATE, severity=RuleSeverity.INFO, priority=100,
        scope={}, required_facts=tuple(required), eligibility=eligibility,
        condition=condition, safety={}, recommendation={}, evidence={}, governance={},
    )
    return CompiledRule(definition, frozenset(), frozenset(), "{}", "rule-hash")


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([PredicateState.TRUE, PredicateState.TRUE], PredicateState.TRUE),
        ([PredicateState.TRUE, PredicateState.UNKNOWN], PredicateState.UNKNOWN),
        ([PredicateState.FALSE, PredicateState.UNKNOWN], PredicateState.FALSE),
        ([PredicateState.FALSE, PredicateState.ERROR], PredicateState.ERROR),
    ],
)
def test_all_truth_table_error_false_unknown_true_precedence(states, expected):
    assert combine_all(states) is expected


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([PredicateState.FALSE, PredicateState.FALSE], PredicateState.FALSE),
        ([PredicateState.FALSE, PredicateState.UNKNOWN], PredicateState.UNKNOWN),
        ([PredicateState.TRUE, PredicateState.UNKNOWN], PredicateState.TRUE),
        ([PredicateState.TRUE, PredicateState.ERROR], PredicateState.ERROR),
    ],
)
def test_any_truth_table_error_true_unknown_false_precedence(states, expected):
    assert combine_any(states) is expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (PredicateState.TRUE, PredicateState.FALSE),
        (PredicateState.FALSE, PredicateState.TRUE),
        (PredicateState.UNKNOWN, PredicateState.UNKNOWN),
        (PredicateState.ERROR, PredicateState.ERROR),
    ],
)
def test_not_preserves_unknown_and_error(state, expected):
    assert negate(state) is expected


@pytest.mark.parametrize(
    ("op", "actual", "expected", "state"),
    [
        ("truthy", True, None, PredicateState.TRUE),
        ("truthy", False, None, PredicateState.FALSE),
        ("has", ["diabetes", "ckd"], "ckd", PredicateState.TRUE),
        ("not_has", ["diabetes"], "ckd", PredicateState.TRUE),
        ("in", "female", ["female", "male"], PredicateState.TRUE),
        ("==", 7.0, 7, PredicateState.TRUE),
        ("!=", "G3b", "G2", PredicateState.TRUE),
        ("between", 7.0, [6.5, 7.5], PredicateState.TRUE),
        (">=", 180, 180, PredicateState.TRUE),
        ("<", 179, 180, PredicateState.TRUE),
    ],
)
def test_current_operators_have_typed_deterministic_semantics(op, actual, expected, state):
    result = RuleEvaluator().evaluate_expression(
        leaf(op=op, value=expected), snapshot(fact(value=actual))
    )
    assert result.state is state


def test_missing_not_has_is_unknown_but_verified_absence_is_true():
    expression = leaf("medication.classes", "not_has", "metformin")
    missing = RuleEvaluator().evaluate_expression(expression, snapshot())
    absent = RuleEvaluator().evaluate_expression(
        expression,
        snapshot(fact("medication.classes", None, status=FactStatus.ABSENT)),
    )
    assert missing.state is PredicateState.UNKNOWN
    assert missing.reason_code == "MISSING"
    assert absent.state is PredicateState.TRUE


def test_verified_absence_is_false_for_exists_truthy_and_has():
    absent_snapshot = snapshot(fact(status=FactStatus.ABSENT, value=None))
    for expression in (leaf(op="exists"), leaf(op="truthy"), leaf(op="has", value="x")):
        assert RuleEvaluator().evaluate_expression(expression, absent_snapshot).state is PredicateState.FALSE


def test_source_unavailable_not_has_is_unknown_gc22():
    result = RuleEvaluator().evaluate_expression(
        leaf("medication.classes", "not_has", "metformin"),
        snapshot(fact("medication.classes", None, status=FactStatus.UNKNOWN,
                      warnings=("SOURCE_UNAVAILABLE",))),
    )
    assert result.state is PredicateState.UNKNOWN
    assert result.reason_code == "SOURCE_UNAVAILABLE"


def test_unknown_and_not_asked_never_become_false():
    expression = leaf("flag.pregnancy", "==", False)
    for status in (FactStatus.UNKNOWN, FactStatus.NOT_ASKED):
        result = RuleEvaluator().evaluate_expression(
            expression, snapshot(fact("flag.pregnancy", None, status=status))
        )
        assert result.state is PredicateState.UNKNOWN


def test_invalid_runtime_type_and_unmapped_unit_are_errors_with_data_issues():
    invalid_type = RuleEvaluator().evaluate_expression(
        leaf(op=">=", value=7), snapshot(fact(value="seven"))
    )
    unit_mismatch = RuleEvaluator().evaluate_expression(
        leaf(op=">=", value=126, unit="mg/dL"),
        snapshot(fact(value=7.2, unit="mmol/L")),
    )
    assert invalid_type.state is PredicateState.ERROR
    assert invalid_type.reason_code == "INVALID_TYPE"
    assert invalid_type.data_issues[0].issue == "INVALID_TYPE"
    assert unit_mismatch.state is PredicateState.ERROR
    assert unit_mismatch.reason_code == "UNIT_MISMATCH"
    assert unit_mismatch.data_issues[0].issue == "UNIT_MISMATCH"


@pytest.mark.parametrize(
    ("expression", "actual"),
    [
        (leaf(op="in", value=[1, 2]), "1"),
        (leaf(op="has", value=1), ["1", "2"]),
        (leaf(op="not_has", value=1), ["1", "2"]),
    ],
)
def test_membership_operators_reject_runtime_type_mismatches(expression, actual):
    result = RuleEvaluator().evaluate_expression(expression, snapshot(fact(value=actual)))
    assert result.state is PredicateState.ERROR
    assert result.reason_code == "INVALID_TYPE"


def test_registered_unit_aliases_compare_without_false_mismatch():
    result = RuleEvaluator().evaluate_expression(
        leaf(op=">=", value=180, unit="mm[Hg]"),
        snapshot(fact(value=181, unit="mmHg")),
    )
    assert result.state is PredicateState.TRUE


def test_boolean_is_not_silently_accepted_as_a_number():
    result = RuleEvaluator().evaluate_expression(
        leaf(op=">", value=0), snapshot(fact(value=True))
    )
    assert result.state is PredicateState.ERROR


def test_latest_selector_is_deterministic_and_exact_time_tie_is_conflicting():
    expression = leaf(op=">=", value=7, selector={"aggregation": "latest"})
    older = fact(value=6.5, effective_at=AS_OF - timedelta(days=10), fact_id="old")
    latest = fact(value=7.2, effective_at=AS_OF - timedelta(days=1), fact_id="new")
    assert RuleEvaluator().evaluate_expression(expression, snapshot(older, latest)).state is PredicateState.TRUE
    tie = fact(value=8.1, effective_at=latest.effective_at, fact_id="tie")
    result = RuleEvaluator().evaluate_expression(expression, snapshot(latest, tie))
    assert result.state is PredicateState.UNKNOWN
    assert result.reason_code == "CONFLICTING"


def test_latest_selector_normalizes_aware_and_naive_tehran_timestamps():
    expression = leaf(op=">=", value=7, selector={"aggregation": "latest"})
    aware = fact(
        value=7.2,
        effective_at=datetime(2026, 7, 21, 12, tzinfo=timezone(timedelta(hours=3, minutes=30))),
        fact_id="aware",
    )
    naive_older = fact(value=6.5, effective_at=AS_OF - timedelta(hours=1), fact_id="naive")
    result = RuleEvaluator().evaluate_expression(expression, snapshot(aware, naive_older))
    assert result.state is PredicateState.TRUE
    assert result.fact_ids == ("aware",)


def test_latest_selector_enforces_its_optional_within_days_window():
    expression = leaf(
        op=">=", value=7,
        selector={"aggregation": "latest", "within_days": 30},
    )
    old = fact(value=8.2, effective_at=AS_OF - timedelta(days=31), fact_id="old")
    result = RuleEvaluator().evaluate_expression(expression, snapshot(old))
    assert result.state is PredicateState.UNKNOWN
    assert result.reason_code == "STALE"


def test_temporal_selectors_distinguish_no_source_from_no_recent_event():
    old = fact(value=True, effective_at=AS_OF - timedelta(days=120))
    recently = leaf(op="truthy", selector={"aggregation": "recently_completed", "within_days": 90})
    count_recent = leaf(op="==", value=0,
                        selector={"aggregation": "count_within_days", "within_days": 90})
    within = leaf(op="has", value=True, selector={"aggregation": "within_days", "within_days": 90})
    evaluator = RuleEvaluator()
    assert evaluator.evaluate_expression(recently, snapshot(old)).state is PredicateState.FALSE
    assert evaluator.evaluate_expression(count_recent, snapshot(old)).state is PredicateState.TRUE
    assert evaluator.evaluate_expression(within, snapshot(old)).state is PredicateState.UNKNOWN
    assert evaluator.evaluate_expression(recently, snapshot()).state is PredicateState.UNKNOWN


def test_stale_unverified_and_conflicting_facts_are_unusable_by_default():
    evaluator = RuleEvaluator()
    expression = leaf(op=">=", value=7)
    policy = {"test.value": {"max_age_days": 90, "minimum_verification": "CONFIRMED"}}
    cases = (
        fact(value=8, effective_at=AS_OF - timedelta(days=91)),
        fact(value=8, verification=VerificationStatus.UNVERIFIED),
        fact(value=8, conflict=ConflictStatus.PRESENT),
    )
    expected = ("STALE", "UNVERIFIED", "CONFLICTING")
    for candidate, issue in zip(cases, expected):
        result = evaluator.evaluate_expression(expression, snapshot(candidate), policies=policy)
        assert result.state is PredicateState.UNKNOWN
        assert result.reason_code == issue


def test_multi_fact_aggregation_does_not_ignore_an_unusable_candidate():
    expression = leaf(op="has", value=8, selector={"aggregation": "all"})
    usable = fact(value=8, fact_id="usable")
    unverified = fact(value=9, fact_id="unverified",
                      verification=VerificationStatus.UNVERIFIED)
    result = RuleEvaluator().evaluate_expression(expression, snapshot(usable, unverified))
    assert result.state is PredicateState.UNKNOWN
    assert result.reason_code == "UNVERIFIED"


def test_timezone_aware_as_of_and_naive_fact_time_compare_deterministically():
    aware_snapshot = FactSnapshot(
        "2.0", 1, datetime(2026, 7, 21, 12, 0, tzinfo=timezone(timedelta(hours=3, minutes=30))),
        (fact(value=8, effective_at=AS_OF - timedelta(days=91)),), "hash",
    )
    result = RuleEvaluator().evaluate_expression(
        leaf(op=">", value=7), aware_snapshot,
        policies={"test.value": {"max_age_days": 90, "minimum_verification": "CONFIRMED"}},
    )
    assert result.state is PredicateState.UNKNOWN
    assert result.reason_code == "STALE"


def test_present_null_is_a_malformed_fact_error_even_for_exists():
    result = RuleEvaluator().evaluate_expression(
        leaf(op="exists"), snapshot(fact(value=None))
    )
    assert result.state is PredicateState.ERROR
    assert result.reason_code == "INVALID_TYPE"


def test_all_branch_keeps_complete_trace_and_error_dominates_false():
    expression = AllExpression("all-root", (
        leaf("a", "truthy", node="a-node"),
        leaf("b", ">", 0, node="b-node"),
    ))
    result = RuleEvaluator().evaluate_expression(
        expression, snapshot(fact("a", False, fact_id="a"), fact("b", "bad", fact_id="b"))
    )
    assert result.state is PredicateState.ERROR
    assert len(result.children) == 2
    assert [child.state for child in result.children] == [PredicateState.FALSE, PredicateState.ERROR]


def test_eligibility_false_unknown_error_map_to_explicit_rule_outcomes():
    evaluator = RuleEvaluator()
    condition = leaf("condition.diabetes", "truthy")
    allowed = fact("scope.allowed", False)
    diabetes = fact("condition.diabetes", True, fact_id="dm")
    assert evaluator.evaluate(compiled(condition), snapshot(allowed, diabetes)).outcome is RuleOutcome.NOT_APPLICABLE

    unknown = fact("scope.allowed", None, status=FactStatus.NOT_ASKED)
    assert evaluator.evaluate(compiled(condition), snapshot(unknown, diabetes)).outcome is RuleOutcome.NEEDS_DATA

    bad = fact("scope.allowed", "yes")
    assert evaluator.evaluate(compiled(condition), snapshot(bad, diabetes)).outcome is RuleOutcome.ERROR


def test_condition_states_map_to_fired_not_fired_needs_data_and_error():
    evaluator = RuleEvaluator()
    rule = compiled(leaf("condition.diabetes", "truthy"))
    scope = fact("scope.allowed", True, fact_id="scope")
    cases = (
        (fact("condition.diabetes", True, fact_id="dm"), RuleOutcome.FIRED),
        (fact("condition.diabetes", False, fact_id="dm"), RuleOutcome.NOT_FIRED),
        (fact("condition.diabetes", None, status=FactStatus.UNKNOWN, fact_id="dm"), RuleOutcome.NEEDS_DATA),
        (fact("condition.diabetes", "yes", fact_id="dm"), RuleOutcome.ERROR),
    )
    for candidate, outcome in cases:
        assert evaluator.evaluate(rule, snapshot(scope, candidate)).outcome is outcome


def test_required_fact_policy_can_require_data_or_mark_not_applicable():
    scope = fact("scope.allowed", True)
    condition = leaf("condition.diabetes", "truthy")
    for policy, expected in (("NEEDS_DATA", RuleOutcome.NEEDS_DATA),
                             ("NOT_APPLICABLE", RuleOutcome.NOT_APPLICABLE)):
        required = (
            {"key": "scope.allowed", "criticality": "REQUIRED", "max_age_days": None,
             "minimum_verification": "CONFIRMED", "on_unusable": "NEEDS_DATA"},
            {"key": "lab.egfr", "criticality": "REQUIRED", "max_age_days": 90,
             "minimum_verification": "CONFIRMED", "on_unusable": policy,
             "prompt_fa": "eGFR جدید لازم است."},
        )
        result = RuleEvaluator().evaluate(compiled(condition, required=required), snapshot(scope))
        assert result.outcome is expected
        assert result.data_issues[0].fact_key == "lab.egfr"


def test_present_null_never_satisfies_a_required_fact_gate():
    required = (
        {"key": "scope.allowed", "criticality": "REQUIRED", "max_age_days": None,
         "minimum_verification": "CONFIRMED", "on_unusable": "NEEDS_DATA"},
        {"key": "lab.egfr", "criticality": "REQUIRED", "max_age_days": 90,
         "minimum_verification": "CONFIRMED", "on_unusable": "NEEDS_DATA"},
    )
    result = RuleEvaluator().evaluate(
        compiled(leaf("condition.diabetes", "truthy"), required=required),
        snapshot(fact("scope.allowed", True), fact("lab.egfr", None, fact_id="egfr-null")),
    )
    assert result.outcome is RuleOutcome.NEEDS_DATA
    assert result.data_issues[0].issue == "INVALID_TYPE"


def test_confirmed_absence_satisfies_required_fact_and_remains_known_absence():
    required = (
        {"key": "scope.allowed", "criticality": "REQUIRED", "max_age_days": None,
         "minimum_verification": "CONFIRMED", "on_unusable": "NEEDS_DATA"},
        {"key": "allergy.substances", "criticality": "REQUIRED", "max_age_days": None,
         "minimum_verification": "CONFIRMED", "on_unusable": "NEEDS_DATA"},
    )
    rule = compiled(leaf("allergy.substances", "not_has", "aspirin"), required=required)
    result = RuleEvaluator().evaluate(
        rule,
        snapshot(fact("scope.allowed", True),
                 fact("allergy.substances", None, status=FactStatus.ABSENT, fact_id="allergy-none")),
    )
    assert result.outcome is RuleOutcome.FIRED


@pytest.mark.parametrize(
    ("key", "expression", "candidate", "expected_outcome", "expected_issue"),
    [
        (
            "flag.pregnancy", leaf("flag.pregnancy", "==", False),
            fact("flag.pregnancy", None, status=FactStatus.NOT_ASKED),
            RuleOutcome.NEEDS_DATA, "NOT_ASKED",
        ),
        (
            "observation.fbs", leaf("observation.fbs", ">=", 126, unit="mg/dL"),
            fact("observation.fbs", 7.2, unit="mmol/L"),
            RuleOutcome.ERROR, "UNIT_MISMATCH",
        ),
        (
            "observation.egfr", leaf("observation.egfr", "<", 45),
            fact("observation.egfr", 42, effective_at=AS_OF - timedelta(days=91)),
            RuleOutcome.NEEDS_DATA, "STALE",
        ),
        (
            "observation.bp_systolic", leaf("observation.bp_systolic", ">=", 140),
            fact("observation.bp_systolic", 172, conflict=ConflictStatus.PRESENT),
            RuleOutcome.NEEDS_DATA, "CONFLICTING",
        ),
        (
            "demographic.age_years", leaf("demographic.age_years", ">=", 18),
            fact("demographic.age_years", None, status=FactStatus.UNKNOWN),
            RuleOutcome.NEEDS_DATA, "UNKNOWN",
        ),
    ],
)
def test_golden_data_quality_cases_map_to_explicit_outcomes(
    key, expression, candidate, expected_outcome, expected_issue
):
    required = (
        {"key": "scope.allowed", "criticality": "REQUIRED", "max_age_days": None,
         "minimum_verification": "CONFIRMED", "on_unusable": "NEEDS_DATA"},
        {"key": key, "criticality": "REQUIRED",
         "max_age_days": 90 if key == "observation.egfr" else None,
         "minimum_verification": "CONFIRMED", "on_unusable": "NEEDS_DATA"},
    )
    result = RuleEvaluator().evaluate(
        compiled(expression, required=required),
        snapshot(fact("scope.allowed", True), candidate),
    )
    assert result.outcome is expected_outcome
    assert expected_issue in {issue.issue for issue in result.data_issues}


def test_unexpected_runtime_failure_is_contained_as_error():
    rule = compiled(object())
    result = RuleEvaluator().evaluate(rule, snapshot(fact("scope.allowed", True)))
    assert result.outcome is RuleOutcome.ERROR
    assert result.error_code == "UNEXPECTED_EVALUATION_ERROR"


def test_evaluation_payload_is_json_serializable_and_schema_valid():
    scope = fact("scope.allowed", True)
    result = RuleEvaluator().evaluate(
        compiled(leaf("condition.diabetes", "truthy")),
        snapshot(scope, fact("condition.diabetes", True, fact_id="dm")),
    )
    payload = evaluation_payload(result)
    document = {
        "schema_version": "2.0", "run_id": "run-1", "patient_link_id": 1,
        "encounter_key": None, "as_of_at": "2026-07-21T12:00:00+03:30",
        "engine_version": "2.0.0", "ruleset": {
            "ruleset_id": "general-outpatient", "version": "2026.1", "hash": "hash"
        },
        "fact_snapshot": {"hash": "snapshot-hash", "facts": []},
        "run_status": "COMPLETED", "rule_results": [payload], "summary": {},
    }
    schema = json.loads((SPECIALIST_ROOT / "src" / "domain" / "clinical_engine" /
                         "schemas" / "evaluation-result.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document))
    assert errors == []
    json.dumps(document, ensure_ascii=False, allow_nan=False)


@pytest.fixture()
def shadow_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True, "DATABASE_PATH": str(tmp_path / "shadow-evaluator.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"), "SECRET_KEY": "shadow-evaluator-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def test_silent_ruleset_contains_routine_error_without_losing_independent_result(shadow_app):
    tests_path = str(SPECIALIST_ROOT / "tests")
    if tests_path not in sys.path:
        sys.path.insert(0, tests_path)
    from test_clinical_engine_v2_storage import _valid_rule
    from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_engine.compiler import RuleCompiler
    from src.services.rule_engine import RuleEngine

    db = get_db()
    patient_id = int(db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, gender, birthdate, enrolled_by, enrolled_at, updated_at)
           VALUES ('SHADOWEVAL01', 'Shadow Evaluation Patient', 'female', '1988-08-01',
                   'pytest', '2026-01-01 09:00:00', '2026-01-01 09:00:00')"""
    ).lastrowid)
    db.execute(
        """INSERT INTO patient_conditions
           (patient_link_id, condition_id, is_active, diagnosed_at)
           VALUES (?, 1, 1, '2025-01-01 09:00:00')""",
        (patient_id,),
    )
    db.execute("UPDATE settings SET value='off' WHERE key='clinical_engine_v2_mode'")
    db.commit()

    compiled_rule = RuleCompiler().compile(_valid_rule())
    invalid_runtime_raw = deepcopy(_valid_rule())
    invalid_runtime_raw["rule_code"] = "TEST-STORAGE-02"
    invalid_runtime_raw["version"] = "2.0.1"
    invalid_runtime_raw["semantic_key"] = "test:storage:runtime-error"
    invalid_runtime_raw["required_facts"].append({
        "key": "demographic.age_years", "criticality": "REQUIRED",
        "max_age_days": None, "minimum_verification": "CONFIRMED",
        "on_unusable": "NEEDS_DATA", "prompt_fa": "سن لازم است.",
    })
    invalid_runtime_raw["condition"] = {
        "node_id": "condition-age-invalid-truthy",
        "fact": "demographic.age_years",
        "selector": {"aggregation": "single"},
        "op": "truthy",
        "unit": None,
    }
    invalid_runtime_rule = RuleCompiler().compile(invalid_runtime_raw)
    rules = ClinicalEngineRulesRepository()
    rule_id = rules.create_rule_version(compiled_rule, created_by="pytest")
    error_rule_id = rules.create_rule_version(invalid_runtime_rule, created_by="pytest")
    rules.mark_validated(rule_id, compiled_rule)
    rules.mark_validated(error_rule_id, invalid_runtime_rule)
    rules.approve_rule_version(rule_id, approved_by="physician")
    rules.approve_rule_version(error_rule_id, approved_by="physician")
    ruleset_id = rules.create_ruleset(
        "general-outpatient", "2026.1",
        [{"rule_version_id": rule_id}, {"rule_version_id": error_rule_id}],
        created_by="release-manager",
    )
    rules.activate_ruleset(ruleset_id, activated_by="release-manager", silent=True)

    engine = RuleEngine()
    legacy_off = engine.evaluate(patient_id)
    assert db.execute("SELECT COUNT(*) c FROM clinical_engine_runs").fetchone()["c"] == 0
    db.execute("UPDATE settings SET value='shadow' WHERE key='clinical_engine_v2_mode'")
    db.commit()
    legacy_shadow = engine.evaluate(patient_id)
    assert legacy_shadow == legacy_off
    run_id = db.execute(
        "SELECT run_id FROM clinical_engine_runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()["run_id"]
    run = db.execute("SELECT * FROM clinical_engine_runs WHERE run_id=?", (run_id,)).fetchone()
    evaluations = db.execute(
        "SELECT * FROM clinical_rule_evaluations WHERE run_id=? ORDER BY rule_version_id", (run_id,)
    ).fetchall()
    assert run["ruleset_id"] == ruleset_id
    assert run["run_status"] == "COMPLETED_WITH_ERRORS"
    assert [(row["predicate_state"], row["outcome"]) for row in evaluations] == [
        ("TRUE", "FIRED"), ("ERROR", "ERROR")
    ]
    assert json.loads(run["summary_json"])["counts"] == {"ERROR": 1, "FIRED": 1}
    assert json.loads(run["summary_json"])["recommendations"] == 1
    recommendation = json.loads(evaluations[0]["recommendation_json"])
    assert recommendation["suggestion_only"] is True
    assert recommendation["presentation"] == "NON_INTERRUPTIVE"
    assert evaluations[1]["recommendation_json"] is None
    assert db.execute(
        "SELECT COUNT(*) c FROM clinical_recommendation_events WHERE run_id=?", (run_id,)
    ).fetchone()["c"] == 0
    assert engine.build_facts(patient_id) == RuleEngine().build_facts(patient_id)


def test_audit_failure_marks_shadow_run_failed_and_never_returns_a_result():
    from src.services.clinical_engine.fact_builder import ShadowFactCapture

    rule = compiled(leaf("condition.diabetes", "truthy"))
    snap = snapshot(fact("scope.allowed", True), fact("condition.diabetes", True, fact_id="dm"))

    class Repository:
        def get_mode(self):
            return "shadow"

    class Builder:
        def build(self, *args, **kwargs):
            return snap

    class Rules:
        def active_ruleset(self, code):
            return {"id": 7, "members": [{"rule_version_id": 11, "rule_json": "{}"}]}

    class Compiler:
        def compile(self, raw):
            return rule

    class Audit:
        def __init__(self):
            self.completions = []

        def start_run(self, **kwargs):
            return "run-audit-failure"

        def append_evaluation(self, **kwargs):
            raise RuntimeError("disk full")

        def complete_run(self, run_id, **kwargs):
            self.completions.append((run_id, kwargs))

    audit = Audit()
    capture = ShadowFactCapture(
        repository=Repository(), builder=Builder(), audit=audit, rules=Rules(),
        compiler=Compiler(), evaluator=RuleEvaluator(),
    )
    with pytest.raises(RuntimeError, match="disk full"):
        capture.capture(1, as_of_at=AS_OF)
    assert audit.completions[-1][1]["status"].value == "AUDIT_FAILED"
