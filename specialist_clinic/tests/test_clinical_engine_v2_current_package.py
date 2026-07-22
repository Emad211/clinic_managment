"""Executable semantics of the current immutable bundled safety package."""
from __future__ import annotations

import json
from pathlib import Path
import sys


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
tests_path = str(SPECIALIST_ROOT / "tests")
if tests_path not in sys.path:
    sys.path.insert(0, tests_path)

from test_clinical_engine_v2_evaluator import fact, snapshot
from src.domain.clinical_engine import RuleOutcome
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.safety import SafetyKernel


CURRENT_PACKAGE = (
    SPECIALIST_ROOT
    / "src"
    / "domain"
    / "clinical_engine"
    / "rule_artifacts"
    / "2026.1-draft.2"
)


def _rules():
    compiler = RuleCompiler()
    return [
        compiler.compile(json.loads((CURRENT_PACKAGE / filename).read_text(encoding="utf-8")))
        for filename in ("T2-REDFLAG-BP.json", "T2-SAFE-MET-STOP.json")
    ]


def _by_code(run):
    return {
        item.compiled.definition.rule_code: item.result
        for item in run.evaluations
    }


def test_current_package_compiles_and_fires_both_positive_controls():
    run = SafetyKernel().evaluate(
        _rules(),
        snapshot(
            fact("condition.codes", ["diabetes"], fact_id="conditions"),
            fact("demographic.age_years", 58, fact_id="age"),
            fact("observation.bp_systolic", 185, unit="mmHg", fact_id="sbp"),
            fact("medication.classes", ["metformin"], fact_id="medications"),
            fact(
                "observation.egfr",
                24,
                unit="mL/min/1.73m2",
                fact_id="egfr",
            ),
        ),
    )

    results = _by_code(run)
    assert results["T2-REDFLAG-BP"].outcome is RuleOutcome.FIRED
    assert results["T2-SAFE-MET-STOP"].outcome is RuleOutcome.FIRED
    assert run.redflag_rule_codes == ("T2-REDFLAG-BP",)


def test_non_diabetic_patient_is_not_applicable_instead_of_needing_diabetes_data():
    run = SafetyKernel().evaluate(
        _rules(),
        snapshot(
            fact("condition.codes", ["hypertension"], fact_id="conditions"),
            fact("demographic.age_years", 58, fact_id="age"),
            fact("observation.bp_systolic", 185, unit="mmHg", fact_id="sbp"),
            fact("medication.classes", ["metformin"], fact_id="medications"),
            fact(
                "observation.egfr",
                24,
                unit="mL/min/1.73m2",
                fact_id="egfr",
            ),
        ),
    )

    results = _by_code(run)
    assert results["T2-REDFLAG-BP"].outcome is RuleOutcome.NOT_APPLICABLE
    assert results["T2-SAFE-MET-STOP"].outcome is RuleOutcome.NOT_APPLICABLE


def test_metformin_rule_does_not_demand_egfr_when_metformin_is_not_active():
    metformin_rule = next(
        rule for rule in _rules()
        if rule.definition.rule_code == "T2-SAFE-MET-STOP"
    )
    run = SafetyKernel().evaluate(
        [metformin_rule],
        snapshot(
            fact("condition.codes", ["diabetes"], fact_id="conditions"),
            fact("demographic.age_years", 58, fact_id="age"),
            fact("medication.classes", [], fact_id="medications"),
        ),
    )

    result = run.evaluations[0].result
    assert result.outcome is RuleOutcome.NOT_APPLICABLE
    assert all(issue.fact_key != "observation.egfr" for issue in result.data_issues)


def test_bundled_adult_rules_are_not_applicable_to_a_minor():
    run = SafetyKernel().evaluate(
        _rules(),
        snapshot(
            fact("condition.codes", ["diabetes"], fact_id="conditions"),
            fact("demographic.age_years", 17, fact_id="age"),
            fact("observation.bp_systolic", 185, unit="mmHg", fact_id="sbp"),
            fact("medication.classes", ["metformin"], fact_id="medications"),
            fact(
                "observation.egfr",
                24,
                unit="mL/min/1.73m2",
                fact_id="egfr",
            ),
        ),
    )

    assert {
        item.result.outcome for item in run.evaluations
    } == {RuleOutcome.NOT_APPLICABLE}
