"""Characterization tests for the legacy (v1) clinical rule engine.

These tests deliberately pin unsafe or ambiguous *current* behaviour so the
v2 engine can be developed beside it without accidentally changing production
semantics.  They are not assertions of desired clinical behaviour.  Each test
should be replaced by a v2 safety/semantics test before the legacy engine is
retired.
"""

from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.services.clinical_rules_service import evaluate as evaluate_indicator
from src.services.rule_engine import RuleEngine
import src.services.rule_engine as rule_engine_module


def _facts(**overrides):
    facts = {
        "age": None,
        "conditions": set(),
        "indicator": {},
        "flag": {},
        "med_classes": set(),
    }
    facts.update(overrides)
    return facts


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _sql):
        return _Rows(self._rows)


def _engine_with_facts(monkeypatch, rows, facts=None):
    """Create an engine without constructing its Flask-bound repositories."""
    engine = RuleEngine.__new__(RuleEngine)
    engine.build_facts = lambda _pid: facts or _facts()
    monkeypatch.setattr(rule_engine_module, "get_db", lambda: _Db(rows))
    return engine


def _rule(code, action_type, trigger_json, *, severity="info", priority=100):
    return {
        "id": priority,
        "rule_code": code,
        "action_type": action_type,
        "trigger_json": trigger_json,
        "action_params_json": None,
        "severity": severity,
        "priority": priority,
    }


def test_v1_missing_collection_satisfies_not_has():
    """Known v1 defect: missing and verified absence are indistinguishable."""
    engine = RuleEngine.__new__(RuleEngine)

    result = engine._leaf(
        {"var": "med.class", "op": "not_has", "value": "insulin_basal"},
        _facts(med_classes=set()),
    )

    assert result is True


def test_v1_missing_scalar_satisfies_not_equal():
    """Known v1 defect: an unknown flag can satisfy a negative predicate."""
    engine = RuleEngine.__new__(RuleEngine)

    result = engine._leaf(
        {"var": "flag.pregnancy", "op": "!=", "value": "true"},
        _facts(),
    )

    assert result is True


def test_v1_invalid_or_missing_indicator_is_reported_as_ok():
    """Known v1 defect: invalid/missing measurements collapse to ``ok``."""
    indicator = {"direction": "high", "warn": 130, "danger": 140}

    assert evaluate_indicator(indicator, None) == "ok"
    assert evaluate_indicator(indicator, "not-a-number") == "ok"
    assert evaluate_indicator({}, 200) == "ok"


def test_v1_malformed_trigger_json_is_silently_skipped(monkeypatch):
    engine = _engine_with_facts(
        monkeypatch,
        [_rule("BROKEN-JSON", "redflag", "{not-valid-json")],
    )

    assert engine.evaluate(1) == []


def test_v1_unexpected_rule_runtime_error_is_silently_skipped(monkeypatch):
    engine = _engine_with_facts(
        monkeypatch,
        [_rule("BROKEN-RUNTIME", "redflag", '{"var":"age","op":">=","value":18}')],
        _facts(age=40),
    )
    monkeypatch.setattr(
        engine,
        "_eval",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert engine.evaluate(1) == []


def test_v1_redflag_does_not_suppress_routine_treatment(monkeypatch):
    always = '{"var":"condition","op":"has","value":"diabetes"}'
    engine = _engine_with_facts(
        monkeypatch,
        [
            _rule("RED-1", "redflag", always, severity="urgent", priority=1),
            _rule("MED-1", "suggest_med", always, severity="warn", priority=2),
        ],
        _facts(conditions={"diabetes"}),
    )

    grouped = engine.grouped(1)
    sections = {section["key"]: section for section in grouped["sections"]}

    assert grouped["has_redflag"] is True
    assert [rule["rule_code"] for rule in sections["redflags"]["rules"]] == ["RED-1"]
    assert [rule["rule_code"] for rule in sections["treatment"]["rules"]] == ["MED-1"]


@pytest.mark.parametrize("trigger", [None, ""])
def test_v1_rules_without_trigger_are_reference_only(monkeypatch, trigger):
    """Intentional v1 behaviour, pinned separately from malformed JSON."""
    engine = _engine_with_facts(
        monkeypatch,
        [_rule("REFERENCE-ONLY", "educate", trigger)],
    )

    assert engine.evaluate(1) == []
