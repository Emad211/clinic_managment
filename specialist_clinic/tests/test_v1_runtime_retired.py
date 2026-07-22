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


def test_patient_template_has_no_v1_decision_surface():
    template = (ROOT / "templates" / "patients" / "detail.html").read_text(encoding="utf-8")
    assert "clinical_support" not in template
    assert "suggestion_action" not in template
