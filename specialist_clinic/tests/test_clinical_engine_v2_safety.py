"""PR-06 executable safety ordering, fail-closed policy, and composition tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
tests_path = str(SPECIALIST_ROOT / "tests")
if tests_path not in sys.path:
    sys.path.insert(0, tests_path)

from test_clinical_engine_v2_compiler import valid_rule
from test_clinical_engine_v2_evaluator import fact, snapshot
from src.domain.clinical_engine import (
    ActionType,
    ClinicalPhase,
    FactStatus,
    RuleOutcome,
    RunStatus,
)
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.composer import RecommendationComposer
from src.services.clinical_engine.evaluator import RuleEvaluator
from src.services.clinical_engine.safety import SafetyKernel
from src.services.clinical_engine.fact_builder import ShadowFactCapture


SAFETY_ARTIFACT_DIR = (
    SPECIALIST_ROOT / "src" / "domain" / "clinical_engine" /
    "rule_artifacts" / "2026.1-draft.1"
)


def _leaf(node_id, key, op="truthy", value=None, unit=None):
    expression = {
        "node_id": node_id,
        "fact": key,
        "selector": {"aggregation": "single"},
        "op": op,
        "unit": unit,
    }
    if op not in {"truthy", "exists"}:
        expression["value"] = value
    return expression


def _declare(raw, key, *, criticality="REQUIRED", on_unusable="NEEDS_DATA"):
    if any(item["key"] == key for item in raw["required_facts"]):
        return
    declaration = {
        "key": key,
        "criticality": criticality,
        "max_age_days": None,
        "on_unusable": on_unusable,
        "prompt_fa": f"{key} لازم است.",
    }
    if criticality != "OPTIONAL":
        declaration["minimum_verification"] = "CONFIRMED"
    raw["required_facts"].append(declaration)


def _rule(code, phase, action_type, condition, *, safety=None, text=None):
    raw = deepcopy(valid_rule())
    raw.update({
        "rule_code": code,
        "version": "2.0.0-draft.1",
        "phase": phase,
        "action_type": action_type,
        "semantic_key": f"test:{code.lower()}",
    })
    raw["condition"] = condition
    raw["safety"] = safety or {
        "redflag_exclusions": [],
        "hard_exclusions": [],
        "on_safety_error": "BLOCK_ROUTINE_OUTPUTS",
    }
    raw["recommendation"].update({
        "text_fa": text or f"پیشنهاد آزمایشی {code}",
        "requires_clinician_confirmation": action_type in {
            "suggest_med", "set_target", "classify"
        },
        "may_create_internal_task": False,
    })
    return raw


def _compiled(raw):
    return RuleCompiler().compile(raw)


def _by_code(run):
    return {item.compiled.definition.rule_code: item for item in run.evaluations}


def test_versioned_draft_safety_artefacts_execute_their_golden_thresholds():
    compiler = RuleCompiler()
    rules = [
        compiler.compile(json.loads(path.read_text(encoding="utf-8")))
        for path in (
            SAFETY_ARTIFACT_DIR / "T2-REDFLAG-BP.json",
            SAFETY_ARTIFACT_DIR / "T2-SAFE-MET-STOP.json",
        )
    ]
    run = SafetyKernel().evaluate(
        rules,
        snapshot(
            fact("condition.diabetes", True, fact_id="dm"),
            fact("observation.bp_systolic", 185, unit="mmHg", fact_id="sbp"),
            fact("medication.classes", ["metformin"], fact_id="med"),
            fact("observation.egfr", 24, unit="mL/min/1.73m2", fact_id="egfr"),
        ),
    )
    results = _by_code(run)
    assert results["T2-REDFLAG-BP"].result.outcome is RuleOutcome.FIRED
    assert results["T2-SAFE-MET-STOP"].result.outcome is RuleOutcome.FIRED
    assert run.redflag_rule_codes == ("T2-REDFLAG-BP",)


def test_gc01_preflight_redflag_runs_first_and_suppresses_fired_routine_outputs():
    redflag = _rule(
        "T2-REDFLAG-BP", "PREFLIGHT", "redflag",
        _leaf("rf-sbp", "observation.bp_systolic", ">=", 180, "mm[Hg]"),
    )
    routine_med = _rule(
        "T2-BP-RX-01", "ROUTINE", "suggest_med",
        _leaf("rx-sbp", "observation.bp_systolic", ">=", 130, "mm[Hg]"),
    )
    routine_target = _rule(
        "T2-BP-TARGET-01", "ROUTINE", "set_target",
        _leaf("target-sbp", "observation.bp_systolic", ">=", 130, "mm[Hg]"),
    )
    for raw in (redflag, routine_med, routine_target):
        _declare(raw, "observation.bp_systolic")

    run = SafetyKernel().evaluate(
        [_compiled(routine_med), _compiled(routine_target), _compiled(redflag)],
        snapshot(
            fact("condition.diabetes", True, fact_id="dm"),
            fact("observation.bp_systolic", 185, unit="mmHg", fact_id="sbp"),
        ),
    )
    results = _by_code(run)
    assert [item.compiled.definition.phase for item in run.evaluations] == [
        ClinicalPhase.PREFLIGHT, ClinicalPhase.ROUTINE, ClinicalPhase.ROUTINE
    ]
    assert results["T2-REDFLAG-BP"].result.outcome is RuleOutcome.FIRED
    for code in ("T2-BP-RX-01", "T2-BP-TARGET-01"):
        assert results[code].result.outcome is RuleOutcome.SUPPRESSED
        assert results[code].result.suppression.reason_code == "ACTIVE_REDFLAG"
        assert results[code].result.suppression.caused_by_rule_code == "T2-REDFLAG-BP"
    assert run.redflag_rule_codes == ("T2-REDFLAG-BP",)
    assert run.routine_outputs_blocked is True
    assert run.status is RunStatus.COMPLETED


def test_gc03_unknown_hard_exclusion_abstains_with_needs_data():
    safety = {
        "redflag_exclusions": [],
        "hard_exclusions": [{
            "exclusion_id": "aspirin-allergy",
            "condition": _leaf("allergy-aspirin", "allergy.substances", "has", "aspirin"),
            "effect": "BLOCK_ACTION",
            "message_fa": "به دلیل آلرژی آسپرین اقدام متوقف شد.",
        }],
        "on_safety_error": "BLOCK_ROUTINE_OUTPUTS",
    }
    aspirin = _rule(
        "T2-ASA-01", "ROUTINE", "suggest_med",
        _leaf("ascvd", "condition.ascvd"), safety=safety,
    )
    _declare(aspirin, "condition.ascvd")
    _declare(aspirin, "allergy.substances", criticality="OPTIONAL")

    run = SafetyKernel().evaluate(
        [_compiled(aspirin)],
        snapshot(
            fact("condition.diabetes", True, fact_id="dm"),
            fact("condition.ascvd", True, fact_id="ascvd"),
            fact("allergy.substances", None, status=FactStatus.UNKNOWN, fact_id="allergy"),
        ),
    )
    result = run.evaluations[0].result
    assert result.outcome is RuleOutcome.NEEDS_DATA
    assert result.predicate.state.value == "UNKNOWN"
    assert {issue.fact_key for issue in result.data_issues} == {"allergy.substances"}
    assert result.suppression is None


def test_gc04_fired_safety_alert_and_true_hard_exclusion_suppress_dependent_rule():
    egfr_low = _leaf("egfr-low", "observation.egfr", "<", 30, "mL/min/{1.73_m2}")
    safety_alert = _rule(
        "T2-SAFE-MET-STOP", "SAFETY", "safety_alert", deepcopy(egfr_low)
    )
    _declare(safety_alert, "observation.egfr")
    routine = _rule(
        "T2-MET-CONTINUE", "ROUTINE", "suggest_med",
        _leaf("metformin-active", "medication.classes", "has", "metformin"),
        safety={
            "redflag_exclusions": [],
            "hard_exclusions": [{
                "exclusion_id": "metformin-egfr-low",
                "condition": deepcopy(egfr_low),
                "effect": "BLOCK_ACTION",
                "message_fa": "به دلیل eGFR پایین، ادامهٔ متفورمین متوقف شد.",
            }],
            "on_safety_error": "BLOCK_ROUTINE_OUTPUTS",
        },
    )
    _declare(routine, "medication.classes")
    _declare(routine, "observation.egfr")

    run = SafetyKernel().evaluate(
        [_compiled(routine), _compiled(safety_alert)],
        snapshot(
            fact("condition.diabetes", True, fact_id="dm"),
            fact("observation.egfr", 24, unit="mL/min/1.73m2", fact_id="egfr"),
            fact("medication.classes", ["metformin"], fact_id="med"),
        ),
    )
    results = _by_code(run)
    assert results["T2-SAFE-MET-STOP"].result.outcome is RuleOutcome.FIRED
    assert results["T2-MET-CONTINUE"].result.outcome is RuleOutcome.SUPPRESSED
    assert results["T2-MET-CONTINUE"].result.suppression.reason_code == "HARD_SAFETY"
    assert run.status is RunStatus.COMPLETED


def test_gc09_safety_error_sets_safety_failed_and_blocks_fired_routine():
    broken_safety = _rule(
        "T2-SAFE-BROKEN", "SAFETY", "safety_alert",
        _leaf("invalid-safety", "demographic.age_years", "truthy"),
    )
    _declare(broken_safety, "demographic.age_years")
    routine = _rule(
        "T2-ROUTINE-INDEPENDENT", "ROUTINE", "educate",
        _leaf("routine-dm", "condition.diabetes"),
    )

    class ExplodingSafetyEvaluator(RuleEvaluator):
        def evaluate(self, compiled, frozen_snapshot):
            if compiled.definition.phase is ClinicalPhase.SAFETY:
                raise RuntimeError("simulated safety subsystem failure")
            return super().evaluate(compiled, frozen_snapshot)

    run = SafetyKernel(ExplodingSafetyEvaluator()).evaluate(
        [_compiled(routine), _compiled(broken_safety)],
        snapshot(
            fact("condition.diabetes", True, fact_id="dm"),
            fact("demographic.age_years", 58, fact_id="age"),
        ),
    )
    results = _by_code(run)
    assert results["T2-SAFE-BROKEN"].result.outcome is RuleOutcome.ERROR
    assert results["T2-ROUTINE-INDEPENDENT"].result.outcome is RuleOutcome.SUPPRESSED
    assert results["T2-ROUTINE-INDEPENDENT"].result.suppression.reason_code == "SAFETY_SUBSYSTEM_FAILED"
    assert run.status is RunStatus.SAFETY_FAILED
    assert run.routine_outputs_blocked is True


def test_routine_runtime_error_is_contained_without_marking_safety_failed():
    routine_error = _rule(
        "T2-ROUTINE-ERROR", "ROUTINE", "educate",
        _leaf("routine-error", "condition.diabetes"),
    )
    routine_ok = _rule(
        "T2-ROUTINE-OK", "ROUTINE", "educate",
        _leaf("routine-ok", "condition.diabetes"),
    )

    class OneRoutineExplodes(RuleEvaluator):
        def evaluate(self, compiled, frozen_snapshot):
            if compiled.definition.rule_code == "T2-ROUTINE-ERROR":
                raise RuntimeError("simulated routine failure")
            return super().evaluate(compiled, frozen_snapshot)

    run = SafetyKernel(OneRoutineExplodes()).evaluate(
        [_compiled(routine_error), _compiled(routine_ok)],
        snapshot(fact("condition.diabetes", True, fact_id="dm")),
    )
    results = _by_code(run)
    assert results["T2-ROUTINE-ERROR"].result.outcome is RuleOutcome.ERROR
    assert results["T2-ROUTINE-OK"].result.outcome is RuleOutcome.FIRED
    assert run.status is RunStatus.COMPLETED_WITH_ERRORS
    assert run.routine_outputs_blocked is False


def test_local_safety_error_dominates_an_active_exclusion_and_blocks_other_routines():
    guarded = _rule(
        "T2-GUARDED", "ROUTINE", "suggest_med",
        _leaf("guarded-dm", "condition.diabetes"),
        safety={
            "redflag_exclusions": [],
            "hard_exclusions": [
                {
                    "exclusion_id": "known-pregnancy",
                    "condition": _leaf("pregnant", "flag.pregnancy", "==", True),
                    "effect": "SUPPRESS",
                    "message_fa": "منع شناخته‌شده فعال است.",
                },
                {
                    "exclusion_id": "malformed-runtime-value",
                    "condition": _leaf("bad-age", "demographic.age_years", "truthy"),
                    "effect": "BLOCK_ACTION",
                    "message_fa": "این بررسی نباید به‌صورت بولی اجرا شود.",
                },
            ],
            "on_safety_error": "BLOCK_ROUTINE_OUTPUTS",
        },
    )
    _declare(guarded, "flag.pregnancy")
    _declare(guarded, "demographic.age_years")
    independent = _rule(
        "T2-INDEPENDENT", "ROUTINE", "educate",
        _leaf("independent-dm", "condition.diabetes"),
    )
    run = SafetyKernel().evaluate(
        [_compiled(guarded), _compiled(independent)],
        snapshot(
            fact("condition.diabetes", True, fact_id="dm"),
            fact("flag.pregnancy", True, fact_id="preg"),
            fact("demographic.age_years", 58, fact_id="age"),
        ),
    )
    results = _by_code(run)
    assert results["T2-GUARDED"].result.outcome is RuleOutcome.ERROR
    assert results["T2-INDEPENDENT"].result.outcome is RuleOutcome.SUPPRESSED
    assert run.status is RunStatus.SAFETY_FAILED


def test_uncleared_preflight_redflag_yields_needs_data_not_false_reassurance():
    redflag = _rule(
        "T2-REDFLAG-UNKNOWN", "PREFLIGHT", "redflag",
        _leaf("rf-sbp", "observation.bp_systolic", ">=", 180, "mm[Hg]"),
    )
    _declare(redflag, "observation.bp_systolic", criticality="OPTIONAL")
    routine = _rule(
        "T2-ROUTINE", "ROUTINE", "educate",
        _leaf("routine-dm", "condition.diabetes"),
    )
    run = SafetyKernel().evaluate(
        [_compiled(routine), _compiled(redflag)],
        snapshot(fact("condition.diabetes", True, fact_id="dm")),
    )
    results = _by_code(run)
    assert results["T2-REDFLAG-UNKNOWN"].result.outcome is RuleOutcome.NEEDS_DATA
    assert results["T2-ROUTINE"].result.outcome is RuleOutcome.NEEDS_DATA
    assert results["T2-ROUTINE"].result.suppression is None
    assert run.status is RunStatus.COMPLETED
    assert run.routine_outputs_blocked is True


@pytest.mark.parametrize(
    ("phase", "action_type", "presentation"),
    [
        ("PREFLIGHT", "redflag", "INTERRUPTIVE"),
        ("SAFETY", "safety_alert", "PROMINENT"),
        ("ROUTINE", "educate", "NON_INTERRUPTIVE"),
    ],
)
def test_composer_creates_only_suggestion_only_dtos_for_fired_results(
    phase, action_type, presentation
):
    raw = _rule(
        f"TEST-{action_type.upper()}", phase, action_type,
        _leaf(f"condition-{action_type}", "condition.diabetes"),
    )
    compiled = _compiled(raw)
    evaluated = RuleEvaluator().evaluate(
        compiled, snapshot(fact("condition.diabetes", True, fact_id="dm"))
    )
    recommendation = RecommendationComposer().compose(compiled, evaluated)
    assert recommendation.presentation == presentation
    assert recommendation.suggestion_only is True
    assert recommendation.action_type is ActionType(action_type)
    assert recommendation.recommendation_key == (
        f"rec:{compiled.definition.rule_code}:{compiled.definition.version}"
    )


def test_composer_abstains_for_suppressed_needs_data_and_error_results():
    raw = _rule(
        "TEST-COMPOSE-ABSTAIN", "ROUTINE", "educate",
        _leaf("condition-dm", "condition.diabetes"),
    )
    compiled = _compiled(raw)
    evaluator = RuleEvaluator()
    needs_data = evaluator.evaluate(compiled, snapshot())
    assert RecommendationComposer().compose(compiled, needs_data) is None


class _ShadowRepository:
    def get_mode(self):
        return "shadow"


class _ShadowBuilder:
    def __init__(self, frozen_snapshot):
        self.frozen_snapshot = frozen_snapshot

    def build(self, *args, **kwargs):
        return self.frozen_snapshot


class _ShadowRules:
    def __init__(self, members):
        self.members = members

    def active_ruleset(self, code):
        return {"id": 17, "members": self.members}


class _ShadowAudit:
    def __init__(self):
        self.evaluations = []
        self.completions = []

    def start_run(self, **kwargs):
        return "safety-shadow-run"

    def append_evaluation(self, **kwargs):
        self.evaluations.append(kwargs)

    def complete_run(self, run_id, **kwargs):
        self.completions.append((run_id, kwargs))


def _member(rule_version_id, raw, phase):
    return {
        "rule_version_id": rule_version_id,
        "rule_json": json.dumps(raw, ensure_ascii=False),
        "phase": phase,
    }


def test_shadow_capture_persists_suppression_and_inert_recommendation_without_events():
    redflag = _rule(
        "T2-REDFLAG-BP", "PREFLIGHT", "redflag",
        _leaf("rf-sbp", "observation.bp_systolic", ">=", 180, "mm[Hg]"),
    )
    routine = _rule(
        "T2-BP-RX-01", "ROUTINE", "suggest_med",
        _leaf("rx-sbp", "observation.bp_systolic", ">=", 130, "mm[Hg]"),
    )
    for raw in (redflag, routine):
        _declare(raw, "observation.bp_systolic")
    snap = snapshot(
        fact("condition.diabetes", True, fact_id="dm"),
        fact("observation.bp_systolic", 185, unit="mmHg", fact_id="sbp"),
    )
    audit = _ShadowAudit()
    capture = ShadowFactCapture(
        repository=_ShadowRepository(), builder=_ShadowBuilder(snap), audit=audit,
        rules=_ShadowRules([
            _member(1, redflag, "PREFLIGHT"),
            _member(2, routine, "ROUTINE"),
        ]),
    )
    assert capture.capture(1, as_of_at=snap.as_of_at) == "safety-shadow-run"
    by_id = {item["rule_version_id"]: item for item in audit.evaluations}
    assert by_id[1]["outcome"] is RuleOutcome.FIRED
    assert by_id[1]["recommendation"]["presentation"] == "INTERRUPTIVE"
    assert by_id[2]["outcome"] is RuleOutcome.SUPPRESSED
    assert by_id[2]["recommendation"] is None
    assert by_id[2]["suppression"]["reason_code"] == "ACTIVE_REDFLAG"
    completion = audit.completions[-1][1]
    assert completion["status"] is RunStatus.COMPLETED
    assert completion["summary"]["recommendations"] == 1
    assert completion["summary"]["redflag_active"] is True
    assert completion["summary"]["routine_outputs_blocked"] is True


def test_corrupt_stored_safety_rule_fails_closed_and_blocks_valid_routine():
    routine = _rule(
        "T2-ROUTINE", "ROUTINE", "educate",
        _leaf("routine-dm", "condition.diabetes"),
    )
    snap = snapshot(fact("condition.diabetes", True, fact_id="dm"))
    audit = _ShadowAudit()
    capture = ShadowFactCapture(
        repository=_ShadowRepository(), builder=_ShadowBuilder(snap), audit=audit,
        rules=_ShadowRules([
            _member(1, {}, "SAFETY"),
            _member(2, routine, "ROUTINE"),
        ]),
    )
    capture.capture(1, as_of_at=snap.as_of_at)
    by_id = {item["rule_version_id"]: item for item in audit.evaluations}
    assert by_id[1]["outcome"] == "ERROR"
    assert by_id[2]["outcome"] is RuleOutcome.SUPPRESSED
    assert by_id[2]["suppression"]["reason_code"] == "SAFETY_SUBSYSTEM_FAILED"
    assert audit.completions[-1][1]["status"] is RunStatus.SAFETY_FAILED
