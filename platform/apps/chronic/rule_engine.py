"""Clinical rule engine — ported from specialist_clinic/src/services/rule_engine.py.

Evaluates the editable ClinicalRule.trigger_json DSL (all/any/not + leaf
{var,op,value}) against a patient fact-bundle. Output is SUGGESTION-ONLY — the
physician confirms ("پیشنهاد — تأیید با پزشک"). The pure evaluator
(``_resolve``/``_leaf``/``_eval``) is decoupled from the DB: ``evaluate`` takes a
facts dict + an iterable of ClinicalRule, so it is trivially unit-testable.
``build_facts`` assembles the bundle from the ORM.

Trigger var vocabulary (from the real 57 rules): ``age``, ``condition`` (set,
op ``has``), ``med.class`` (set), ``bmi``, ``indicator.<key>.<attr>`` (attr
defaults to ``latest``), ``flag.<key>``.
"""

from datetime import date

# action_type -> UI section
SECTION = {
    "redflag": "redflags",
    "safety_alert": "safety",
    "suggest_med": "treatment",
    "flag_risk": "risk",
    "set_target": "assessment",
    "classify": "assessment",
    "create_followup": "monitoring",
    "schedule_screening": "monitoring",
    "vaccine": "vaccination",
    "educate": "lifestyle",
}
SECTION_LABELS = {
    "redflags": "🚨 هشدارهای فوری",
    "risk": "⚠️ ریسک",
    "treatment": "💊 پیشنهادهای درمان",
    "safety": "🛑 ایمنی و منع دارو",
    "assessment": "🎯 ارزیابی و اهداف",
    "monitoring": "📅 پایش و غربالگری",
    "vaccination": "💉 واکسیناسیون",
    "lifestyle": "🍎 سبک زندگی و آموزش",
}
SECTION_ORDER = ["redflags", "safety", "risk", "treatment", "assessment",
                 "monitoring", "vaccination", "lifestyle"]
_SEVERITY_RANK = {"urgent": 0, "warn": 1, "info": 2}


def _age_from_birthdate(bd):
    """Robust age: handles a date, or a gregorian/Jalali year string."""
    if not bd:
        return None
    if isinstance(bd, date):
        age = date.today().year - bd.year
        return age if 0 < age < 130 else None
    digits = "".join(ch for ch in str(bd) if ch.isdigit())
    if len(digits) < 4:
        return None
    year = int(digits[:4])
    now_g = date.today().year
    if year < 1500:  # Jalali year -> approximate gregorian
        year += 621
    age = now_g - year
    return age if 0 < age < 130 else None


def _truthy(v) -> bool:
    return v not in (None, "", "0", "false", "False", "no", "off")


def _resolve(var: str, facts: dict):
    if var == "age":
        return facts.get("age")
    if var == "condition":
        return facts.get("conditions")
    if var == "med.class":
        return facts.get("med_classes")
    if var == "bmi":
        return facts["indicator"].get("bmi", {}).get("latest")
    if var.startswith("indicator."):
        parts = var.split(".")
        key = parts[1]
        attr = parts[2] if len(parts) > 2 else "latest"
        return facts["indicator"].get(key, {}).get(attr)
    if var.startswith("flag."):
        return facts["flag"].get(var.split(".", 1)[1])
    return None


def _leaf(node: dict, facts: dict) -> bool:
    cur = _resolve(node["var"], facts)
    op = node["op"]
    val = node.get("value")
    if op == "has":
        return val in (cur or set())
    if op == "not_has":
        return val not in (cur or set())
    if op == "in":
        return cur in (val or [])
    if op == "truthy":
        return _truthy(cur)
    if op == "exists":
        return cur not in (None, "")
    if op in ("==", "!="):
        try:
            a, b = float(cur), float(val)
        except (TypeError, ValueError):
            a, b = (str(cur) if cur is not None else None), str(val)
        return (a == b) if op == "==" else (a != b)
    if cur is None or cur == "":
        return False
    if op == "between":
        try:
            return float(val[0]) <= float(cur) <= float(val[1])
        except (TypeError, ValueError, IndexError):
            return False
    try:
        a, b = float(cur), float(val)
    except (TypeError, ValueError):
        return False
    return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}.get(op, False)


def _eval(node, facts: dict) -> bool:
    if node is None:
        return True
    if "all" in node:
        return all(_eval(c, facts) for c in node["all"])
    if "any" in node:
        return any(_eval(c, facts) for c in node["any"])
    if "not" in node:
        return not _eval(node["not"], facts)
    if "var" in node:
        return _leaf(node, facts)
    return False


def evaluate(facts: dict, rules) -> list:
    """Return fired rules (suggestion-only) for the given facts. ``rules`` is an
    iterable of ClinicalRule instances. Rules without a trigger are reference-only
    (manager catalog) and skipped."""
    fired = []
    for r in rules:
        trig = r.trigger_json or None
        if not trig:
            continue
        try:
            if _eval(trig, facts):
                fired.append({
                    "code": r.code,
                    "title": r.title,
                    "category": r.category,
                    "severity": r.severity,
                    "priority": r.priority,
                    "recommendation": r.recommendation,
                    "dosage_titration": r.dosage_titration,
                    "monitoring": r.monitoring,
                    "contraindications": r.contraindications,
                    "evidence_level": r.evidence_level,
                    "source_ref": r.source_ref,
                    "action_type": r.action_type,
                    "params": r.action_params_json or {},
                    "section": SECTION.get(r.action_type, "lifestyle"),
                })
        except Exception:
            continue
    fired.sort(key=lambda x: (_SEVERITY_RANK.get(x.get("severity"), 3), x.get("priority", 100)))
    return fired


def grouped(facts: dict, rules) -> dict:
    """Fired rules grouped into UI sections, in display order."""
    fired = evaluate(facts, rules)
    groups = {}
    for r in fired:
        groups.setdefault(r["section"], []).append(r)
    return {
        "sections": [
            {"key": s, "label": SECTION_LABELS[s], "rules": groups[s]}
            for s in SECTION_ORDER if s in groups
        ],
        "count": len(fired),
        "has_redflag": any(r["section"] == "redflags" for r in fired),
    }


# ── ORM fact bundle ──────────────────────────────────────────────────────────

def _indicator_level(key, value):
    """Best-effort severity level for a reading, from the global ClinicalIndicator
    thresholds (direction high_bad/low_bad). Returns urgent|warn|normal|None."""
    from apps.chronic.models import ClinicalIndicator
    ind = ClinicalIndicator.objects.filter(clinic__isnull=True, key=key).first()
    if not ind or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    high_bad = ind.direction != "low_bad"
    warn, danger = ind.warn, ind.danger
    if high_bad:
        if danger is not None and v >= danger:
            return "urgent"
        if warn is not None and v >= warn:
            return "warn"
    else:
        if danger is not None and v <= danger:
            return "urgent"
        if warn is not None and v <= warn:
            return "warn"
    return "normal"


def build_facts(patient) -> dict:
    """Assemble the fact bundle for a Patient (tenant context must be set)."""
    from apps.chronic.models import (
        PatientCondition, PatientFlag, PatientMedication, VitalReading,
    )

    conditions = set(
        PatientCondition.objects.filter(patient=patient)
        .select_related("condition").values_list("condition__code", flat=True)
    )

    indicator = {}
    seen = set()
    for vr in (VitalReading.objects.filter(patient=patient)
               .order_by("indicator_key", "-measured_at")):
        if vr.indicator_key in seen:
            continue
        seen.add(vr.indicator_key)
        indicator[vr.indicator_key] = {
            "latest": float(vr.value),
            "level": _indicator_level(vr.indicator_key, vr.value),
        }

    flag = {}
    for pf in (PatientFlag.objects.filter(patient=patient, is_active=True)
               .select_related("flag")):
        flag[pf.flag.code] = pf.value or "present"

    med_classes = set(
        PatientMedication.objects.filter(patient=patient, is_active=True)
        .exclude(drug_class__isnull=True)
        .select_related("drug_class").values_list("drug_class__code", flat=True)
    )

    return {
        "age": _age_from_birthdate(patient.birthdate),
        "conditions": conditions,
        "indicator": indicator,
        "flag": flag,
        "med_classes": med_classes,
    }
