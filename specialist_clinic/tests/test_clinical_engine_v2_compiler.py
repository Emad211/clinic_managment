"""PR-02 tests: isolated Clinical Engine v2 schemas, DTOs and compiler."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys

import pytest
from jsonschema import Draft202012Validator


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.domain.clinical_engine import (
    ActionType,
    ClinicalFact,
    ClinicalPhase,
    CompiledRule,
    ConflictStatus,
    FactKind,
    FactSource,
    FactStatus,
    FreshnessStatus,
    LeafExpression,
    RuleCompilationError,
    VerificationStatus,
)
from src.services.clinical_engine.compiler import RuleCompiler


SCHEMA_DIR = SPECIALIST_ROOT / "src" / "domain" / "clinical_engine" / "schemas"


def valid_rule():
    return {
        "schema_version": "2.0",
        "dsl_version": "2.0",
        "rule_code": "TEST-RULE-01",
        "version": "2.0.0-draft.1",
        "title": "قاعدهٔ آزمایشی",
        "phase": "ROUTINE",
        "action_type": "educate",
        "severity": "INFO",
        "priority": 100,
        "semantic_key": "test:education",
        "scope": {
            "population": "بزرگسال سرپایی",
            "age_min": 18,
            "age_max": None,
            "sex": ["any"],
            "care_settings": ["outpatient"],
            "encounter_types": ["office_visit"],
            "condition_codes": ["diabetes"],
            "out_of_scope": [],
        },
        "required_facts": [
            {
                "key": "condition.diabetes",
                "criticality": "REQUIRED",
                "max_age_days": None,
                "minimum_verification": "CONFIRMED",
                "on_unusable": "NEEDS_DATA",
                "prompt_fa": "تشخیص دیابت باید تأیید شود.",
            }
        ],
        "eligibility": {
            "node_id": "eligibility-diabetes",
            "fact": "condition.diabetes",
            "selector": {"aggregation": "single"},
            "op": "==",
            "value": True,
            "unit": None,
        },
        "condition": {
            "node_id": "condition-diabetes",
            "fact": "condition.diabetes",
            "selector": {"aggregation": "single"},
            "op": "truthy",
            "unit": None,
        },
        "safety": {
            "redflag_exclusions": [],
            "hard_exclusions": [],
            "on_safety_error": "BLOCK_ROUTINE_OUTPUTS",
        },
        "recommendation": {
            "text_fa": "آموزش عمومی با تأیید پزشک معالج.",
            "suggestion_only": True,
            "requires_clinician_confirmation": False,
            "may_create_internal_task": False,
            "params": {},
        },
        "evidence": {
            "source_title": "Test guideline",
            "issuing_organization": "Test organization",
            "publication_date": "2026-01-01",
            "source_version": "2026",
            "source_locator": "Section 1",
            "source_url": "https://example.org/guideline",
            "evidence_certainty": "NOT_GRADED",
            "recommendation_strength": "NOT_GRADED",
            "local_validation_status": "NOT_REVIEWED",
            "local_adaptation_note": "فقط برای تست",
        },
        "governance": {
            "status": "DRAFT",
            "author": "test-suite",
            "clinical_reviewer": None,
            "technical_reviewer": None,
            "review_due_date": "2026-12-31",
            "supersedes": None,
            "change_note": "initial draft",
        },
    }


def diagnostic_codes(compiler, rule):
    return {item.code for item in compiler.validate(rule)}


def test_all_v2_schemas_are_valid_draft_2020_12():
    names = {
        "clinical-rule.schema.json",
        "clinical-fact.schema.json",
        "evaluation-result.schema.json",
    }
    assert {path.name for path in SCHEMA_DIR.glob("*.json")} == names
    for name in names:
        schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_valid_draft_compiles_to_immutable_typed_plan():
    compiled = RuleCompiler().compile(valid_rule())

    assert isinstance(compiled, CompiledRule)
    assert compiled.definition.phase is ClinicalPhase.ROUTINE
    assert compiled.definition.action_type is ActionType.EDUCATE
    assert isinstance(compiled.definition.condition, LeafExpression)
    assert compiled.referenced_fact_keys == frozenset({"condition.diabetes"})
    assert compiled.node_ids == frozenset({"eligibility-diabetes", "condition-diabetes"})
    assert len(compiled.content_hash) == 64
    with pytest.raises(TypeError):
        compiled.definition.scope["population"] = "changed"


def test_hash_is_deterministic_across_mapping_order():
    rule = valid_rule()
    reordered = dict(reversed(list(deepcopy(rule).items())))

    assert RuleCompiler().compile(rule).content_hash == RuleCompiler().compile(reordered).content_hash


def test_canonical_fact_contract_is_immutable_and_keeps_quality_axes_separate():
    fact = ClinicalFact(
        schema_version="2.0",
        fact_id="observation:1",
        patient_link_id=1,
        kind=FactKind.OBSERVATION,
        key="observation.hba1c",
        status=FactStatus.PRESENT,
        value=7.2,
        unit="%",
        effective_at=datetime(2026, 7, 20, 8, 0),
        recorded_at=datetime(2026, 7, 20, 8, 5),
        source=FactSource(system="specialist", record_id="1"),
        verification=VerificationStatus.CONFIRMED,
        freshness=FreshnessStatus.FRESH,
        conflict=ConflictStatus.NONE,
    )

    assert fact.value == 7.2
    assert fact.verification is VerificationStatus.CONFIRMED
    with pytest.raises(Exception):
        fact.value = 8.0


def test_non_json_native_payload_is_rejected_before_hashing():
    rule = valid_rule()
    rule["recommendation"]["params"]["bad"] = {1, 2}

    diagnostics = RuleCompiler().validate(rule)

    assert diagnostics[0].code == "NOT_JSON_SERIALIZABLE"
    with pytest.raises(RuleCompilationError):
        RuleCompiler().compile(rule)


def test_malformed_serialized_json_has_typed_diagnostic():
    compiler = RuleCompiler()

    diagnostics = compiler.validate_json('{"rule_code":')

    assert diagnostics[0].code == "MALFORMED_JSON"
    assert diagnostics[0].path == "$"
    with pytest.raises(RuleCompilationError):
        compiler.compile_json('{"rule_code":')


def test_valid_serialized_json_compiles():
    compiled = RuleCompiler().compile_json(json.dumps(valid_rule(), ensure_ascii=False))

    assert compiled.definition.rule_code == "TEST-RULE-01"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda r: r.update(schema_version="1.0"), "SCHEMA_VALIDATION_ERROR"),
        (lambda r: r.update(action_type="prescribe"), "SCHEMA_VALIDATION_ERROR"),
        (lambda r: r["condition"].update(op="approximately"), "SCHEMA_VALIDATION_ERROR"),
        (lambda r: r["safety"].update(on_safety_error="IGNORE"), "SCHEMA_VALIDATION_ERROR"),
        (lambda r: r["condition"].update(value="high", op=">="), "INVALID_NUMERIC_COMPARISON"),
        (lambda r: r["condition"].update(unit="psi"), "UNSUPPORTED_UNIT"),
    ],
)
def test_invalid_version_operator_action_unit_type_or_safety_is_rejected(mutation, expected_code):
    rule = valid_rule()
    mutation(rule)

    diagnostics = RuleCompiler().validate(rule)

    assert expected_code in {item.code for item in diagnostics}
    with pytest.raises(RuleCompilationError):
        RuleCompiler().compile(rule)


def test_every_expression_fact_must_be_declared():
    rule = valid_rule()
    rule["condition"]["fact"] = "flag.pregnancy"

    assert "UNDECLARED_FACT_REFERENCE" in diagnostic_codes(RuleCompiler(), rule)


def test_node_ids_are_unique_across_the_entire_rule():
    rule = valid_rule()
    rule["condition"]["node_id"] = rule["eligibility"]["node_id"]

    assert "DUPLICATE_NODE_ID" in diagnostic_codes(RuleCompiler(), rule)


def test_redflag_must_be_preflight_and_medication_requires_confirmation():
    redflag = valid_rule()
    redflag.update(action_type="redflag", phase="ROUTINE")
    assert "ACTION_PHASE_MISMATCH" in diagnostic_codes(RuleCompiler(), redflag)

    medication = valid_rule()
    medication["action_type"] = "suggest_med"
    assert "CLINICIAN_CONFIRMATION_REQUIRED" in diagnostic_codes(RuleCompiler(), medication)


def test_only_due_workflow_actions_may_create_internal_tasks():
    rule = valid_rule()
    rule["recommendation"]["may_create_internal_task"] = True

    assert "AUTOMATIC_TASK_NOT_ALLOWED" in diagnostic_codes(RuleCompiler(), rule)


def test_critical_fact_cannot_continue_when_unusable():
    rule = valid_rule()
    fact = rule["required_facts"][0]
    fact["criticality"] = "CRITICAL"
    fact["on_unusable"] = "CONTINUE_WITH_WARNING"

    assert "UNSAFE_CRITICAL_FACT_POLICY" in diagnostic_codes(RuleCompiler(), rule)


def test_active_rule_requires_approval_reviewers_and_semantic_key():
    rule = valid_rule()
    rule["governance"]["status"] = "ACTIVE"
    rule.pop("semantic_key")

    codes = diagnostic_codes(RuleCompiler(), rule)

    assert {
        "ACTIVE_RULE_NOT_CLINICALLY_APPROVED",
        "ACTIVE_RULE_MISSING_REVIEWERS",
        "ACTIVE_RULE_MISSING_SEMANTIC_KEY",
    } <= codes


def test_structural_diagnostic_includes_json_path():
    rule = valid_rule()
    rule["recommendation"]["suggestion_only"] = False

    diagnostic = RuleCompiler().validate(rule)[0]

    assert diagnostic.code == "SCHEMA_VALIDATION_ERROR"
    assert diagnostic.path == "$.recommendation.suggestion_only"


def test_temporal_selector_requires_an_explicit_window():
    rule = valid_rule()
    rule["condition"]["selector"] = {"aggregation": "recently_completed"}

    assert "MISSING_SELECTOR_WINDOW" in diagnostic_codes(RuleCompiler(), rule)


def test_latest_selector_may_use_a_freshness_window_from_reference_artefacts():
    rule = valid_rule()
    rule["condition"]["selector"] = {"aggregation": "latest", "within_days": 30}

    assert RuleCompiler().validate(rule) == ()


def test_minimum_count_is_rejected_for_non_count_selector():
    rule = valid_rule()
    rule["condition"]["selector"] = {"aggregation": "single", "minimum_count": 2}

    assert "INCOMPATIBLE_SELECTOR_MINIMUM_COUNT" in diagnostic_codes(RuleCompiler(), rule)
