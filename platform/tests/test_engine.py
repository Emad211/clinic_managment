from apps.chronic import rule_engine
from apps.chronic.models import ClinicalRule


def test_build_facts(diabetic_patient):
    facts = rule_engine.build_facts(diabetic_patient)
    assert facts["age"] and facts["age"] > 60
    assert "diabetes" in facts["conditions"]
    assert facts["indicator"]["hba1c"]["latest"] == 9.0


def test_engine_fires_expected_rule(diabetic_patient):
    facts = rule_engine.build_facts(diabetic_patient)
    fired = rule_engine.evaluate(facts, ClinicalRule.objects.filter(is_active=True))
    codes = {f["code"] for f in fired}
    assert "T2-DX-01" in codes          # hba1c >= 6.5 -> fires
    assert "REF-ONLY" not in codes      # no trigger -> reference-only, never fires


def test_grouped_sections(diabetic_patient):
    facts = rule_engine.build_facts(diabetic_patient)
    g = rule_engine.grouped(facts, ClinicalRule.objects.filter(is_active=True))
    assert g["count"] >= 1
    assert any(s["key"] == "assessment" for s in g["sections"])  # classify -> assessment


def test_leaf_operators():
    facts = {"age": 50, "conditions": {"diabetes"}, "indicator": {"hba1c": {"latest": 8.0}},
             "flag": {"frailty": "robust"}, "med_classes": {"metformin"}}
    assert rule_engine._eval({"var": "indicator.hba1c.latest", "op": ">", "value": 7}, facts)
    assert rule_engine._eval({"var": "condition", "op": "has", "value": "diabetes"}, facts)
    assert rule_engine._eval({"var": "flag.frailty", "op": "==", "value": "robust"}, facts)
    assert not rule_engine._eval({"var": "med.class", "op": "has", "value": "insulin"}, facts)
    assert rule_engine._eval({"all": [
        {"var": "age", "op": ">=", "value": 40},
        {"not": {"var": "med.class", "op": "has", "value": "insulin"}},
    ]}, facts)
