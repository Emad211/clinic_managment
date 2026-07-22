"""Regression guards proving Clinical Engine v1 cannot return to production."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src"


def test_production_runtime_has_no_v1_rule_engine_consumer():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if path.name == "rule_engine.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "RuleEngine" in source or "services.rule_engine" in source:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_retired_v1_shell_never_reads_or_interprets_legacy_rules():
    source = (ROOT / "services" / "rule_engine.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "get_db",
        "trigger_json",
        "action_params_json",
        "SELECT * FROM clinical_rules",
        "def _eval(",
        "def _leaf(",
    )
    assert all(token not in source for token in forbidden)


def test_retired_v1_api_is_inert_without_shadow_capture():
    from src.services.rule_engine import RuleEngine

    engine = RuleEngine(capture_shadow=False)

    assert engine.build_facts(17) == {
        "engine": "v1-retired",
        "facts": (),
    }
    assert engine.evaluate(17) == []
    assert engine.grouped(17) == {
        "sections": [],
        "count": 0,
        "has_redflag": False,
        "retired": True,
    }


def test_legacy_rule_seed_is_a_no_write_tombstone():
    from src.adapters.sqlite.clinical_rules_seed import seed_clinical_rules

    class ExplodingDatabase:
        def __getattr__(self, name):
            raise AssertionError(f"legacy seed attempted database access: {name}")

    assert seed_clinical_rules(ExplodingDatabase()) == 0


def test_legacy_dosage_guidance_is_inert_without_database_access():
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository

    assert ClinicalRulesRepository().dosage_guidance(["ckd", "hypertension"]) == []


def test_patient_template_has_no_v1_decision_surface():
    template = (
        ROOT / "templates" / "patients" / "detail.html"
    ).read_text(encoding="utf-8")
    assert "clinical_support" not in template
    assert "suggestion_action" not in template
