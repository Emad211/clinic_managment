# A12 governed diabetes monitoring tranche contract tests.
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.clinical_engine.release import CURRENT_BUNDLED_PACKAGE_VERSION
from src.services.clinical_engine.package_contract import load_rule_package
from src.services.clinical_engine.validation_harness import (
    GoldenCaseValidationHarness,
    package_directory,
)


EXPECTED_CODES = {
    "T2-REDFLAG-BP",
    "T2-SAFE-MET-STOP",
    "T2-SAFE-MET-REVIEW",
    "T2-MON-A1C-DUE",
    "T2-MON-EGFR-DUE",
    "T2-MON-UACR-DUE",
}


def _package():
    return load_rule_package(
        package_directory(),
        expected_version=CURRENT_BUNDLED_PACKAGE_VERSION,
    )


def test_a12_package_is_current_complete_and_still_not_approved():
    package = _package()

    assert CURRENT_BUNDLED_PACKAGE_VERSION == "2026.1-draft.3"
    assert set(package.rule_codes) == EXPECTED_CODES
    assert package.manifest["status"] == "DRAFT"
    assert package.manifest["clinical_use"] == "NOT_APPROVED"
    assert all(
        rule.definition.evidence["local_validation_status"] == "NOT_REVIEWED"
        for rule in package.compiled_rules
    )


def test_a12_monitoring_rules_have_exact_confirmed_canonical_completion_contracts():
    package = _package()
    rules = {
        rule.definition.rule_code: rule.definition
        for rule in package.compiled_rules
    }
    expected = {
        "T2-MON-A1C-DUE": ("observation.hba1c", 183),
        "T2-MON-EGFR-DUE": ("observation.egfr", 365),
        "T2-MON-UACR-DUE": ("observation.uacr", 365),
    }

    for code, (fact_key, max_days) in expected.items():
        definition = rules[code]
        recommendation = definition.recommendation
        params = recommendation["params"]
        contract = params["task_contract"]

        assert definition.action_type.value == "schedule_screening"
        assert definition.phase.value == "ROUTINE"
        assert recommendation["requires_clinician_confirmation"] is True
        assert recommendation["may_create_internal_task"] is True
        assert params["due_in_days"] == 30
        assert contract["required_fact_keys"] == (fact_key,)
        assert contract["minimum_verification"] == "CONFIRMED"
        assert contract["canonical_ingestion"] == "REQUIRED"
        fact_policy = next(
            item for item in definition.required_facts
            if item["key"] == fact_key
        )
        assert fact_policy["max_age_days"] == max_days


def test_a12_metformin_review_is_non_prescriptive_and_distinct_from_stop_rule():
    package = _package()
    rules = {
        rule.definition.rule_code: rule.definition
        for rule in package.compiled_rules
    }
    review = rules["T2-SAFE-MET-REVIEW"]
    stop = rules["T2-SAFE-MET-STOP"]

    assert review.phase.value == "SAFETY"
    assert review.recommendation["may_create_internal_task"] is False
    assert review.recommendation["params"]["do_not_modify_medication"] is True
    assert review.semantic_key != stop.semantic_key
    assert review.priority > stop.priority


def test_a12_golden_matrix_passes_without_error_or_false_classification():
    report = GoldenCaseValidationHarness().run()

    assert report["status"] == "PASS"
    assert report["checks"]["all_cases_pass"] is True
    assert report["checks"]["zero_errors"] is True
    assert report["checks"]["zero_false_positive"] is True
    assert report["checks"]["zero_false_negative"] is True
    assert set(report["metrics"]) == EXPECTED_CODES
    assert all(
        values["true_positive"] > 0 and values["true_negative"] > 0
        for values in report["metrics"].values()
    )
