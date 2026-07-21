"""PR-07 semantic deduplication and conservative conflict tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
tests_path = str(SPECIALIST_ROOT / "tests")
if tests_path not in sys.path:
    sys.path.insert(0, tests_path)

from test_clinical_engine_v2_compiler import valid_rule
from test_clinical_engine_v2_evaluator import fact, snapshot
from src.domain.clinical_engine import RuleOutcome
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.conflicts import ConflictResolver
from src.services.clinical_engine.safety import SafetyKernel


def _compiled(code, semantic_key, *, action_type="suggest_med", priority=50,
              severity="WARN", title=None):
    raw = deepcopy(valid_rule())
    raw.update({
        "rule_code": code,
        "version": "2.0.0-draft.1",
        "title": title or code,
        "phase": "PREFLIGHT" if action_type == "redflag" else "ROUTINE",
        "action_type": action_type,
        "priority": priority,
        "severity": severity,
    })
    if semantic_key is None:
        raw.pop("semantic_key", None)
    else:
        raw["semantic_key"] = semantic_key
    raw["recommendation"].update({
        "text_fa": f"پیشنهاد {code}",
        "requires_clinician_confirmation": action_type in {
            "suggest_med", "set_target", "classify"
        },
        "may_create_internal_task": False,
    })
    return RuleCompiler().compile(raw)


def _resolve(*rules):
    evaluated = SafetyKernel().evaluate(
        list(rules), snapshot(fact("condition.diabetes", True, fact_id="dm"))
    )
    return ConflictResolver().resolve(evaluated.evaluations)


def test_gc12_same_semantic_medication_is_presented_once_and_trace_is_merged():
    lower = _compiled("STATIN-LOW", "med:statin", priority=80, title="قاعده دوم")
    winner = _compiled(
        "STATIN-HIGH", "med:statin", priority=10, severity="URGENT",
        title="قاعده اول",
    )
    by_code = {
        item.compiled.definition.rule_code: item for item in _resolve(lower, winner)
    }

    assert by_code["STATIN-HIGH"].result.outcome is RuleOutcome.FIRED
    assert by_code["STATIN-HIGH"].merged_rule_codes == (
        "STATIN-HIGH", "STATIN-LOW"
    )
    assert by_code["STATIN-HIGH"].merged_titles == ("قاعده اول", "قاعده دوم")
    duplicate = by_code["STATIN-LOW"].result
    assert duplicate.outcome is RuleOutcome.SUPPRESSED
    assert duplicate.suppression.reason_code == "DEDUPLICATED"
    assert duplicate.suppression.caused_by_rule_code == "STATIN-HIGH"


def test_gc11_distinct_medication_options_are_not_collapsed_semantically():
    result = _resolve(
        _compiled("ASCVD", "med:ascvd"), _compiled("HF", "med:hf"),
        _compiled("CKD", "med:ckd"), _compiled("OBESITY", "med:obesity"),
    )
    assert [item.result.outcome for item in result] == [RuleOutcome.FIRED] * 4
    assert all(not item.merged_rule_codes for item in result)


def test_gc17_same_key_with_incompatible_actions_is_explicitly_withheld():
    result = _resolve(
        _compiled("DM-TARGET", "glycaemia:next-step", action_type="set_target"),
        _compiled("CKD-MED", "glycaemia:next-step", action_type="suggest_med"),
    )
    assert all(item.result.outcome is RuleOutcome.SUPPRESSED for item in result)
    assert {item.result.suppression.reason_code for item in result} == {
        "UNRESOLVED_CONFLICT"
    }


def test_rules_without_semantic_key_are_never_implicitly_merged():
    result = _resolve(_compiled("ONE", None), _compiled("TWO", None))
    assert [item.result.outcome for item in result] == [RuleOutcome.FIRED] * 2


def test_resolver_never_revives_a_redflag_suppressed_routine_output():
    redflag = _compiled(
        "RED", "urgent:red", action_type="redflag", severity="CRITICAL"
    )
    routine = _compiled("ROUTINE", "urgent:red")
    by_code = {
        item.compiled.definition.rule_code: item.result
        for item in _resolve(redflag, routine)
    }
    assert by_code["RED"].outcome is RuleOutcome.FIRED
    assert by_code["ROUTINE"].outcome is RuleOutcome.SUPPRESSED
    assert by_code["ROUTINE"].suppression.reason_code == "ACTIVE_REDFLAG"
