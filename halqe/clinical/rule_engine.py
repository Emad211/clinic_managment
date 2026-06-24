"""
Faithful port of specialist_clinic/src/services/rule_engine.py
into the halqe Django/Postgres platform.

The trigger_json DSL evaluator (_eval / _leaf) is ported EXACTLY — same
operators, same semantics — because this is safety-relevant decision support.

Output is SUGGESTION-ONLY: "پیشنهاد — تأیید با پزشک".
Every fired rule carries `suggestion_only=True`.

Facts assembled from Postgres via Django ORM:
  - latest observations per obs_key  (clinical.observations VIEW — UNION of
    vital_readings + lab_results; ADR-0005)
  - active condition codes             (patient_conditions → conditions)
  - patient_flags (categorical/bool)  (patient_flags)
  - active medications' drug_class set (patient_medications)
  - thresholds from clinical_indicators (NOT hardcoded; static map = fallback)

Deferred (not yet wired):
  - age: patient birthdate lives in accounting.patients — wired via the port
    if demographics are available; falls back to None (rules that need age
    simply won't fire; no wrong suggestions).
"""
import json
from datetime import datetime

from clinical.models import (
    Observation,
    PatientCondition,
    PatientMedication,
    ClinicalRule,
    ClinicalIndicator,
    PatientFlag,
    Condition,
)

# ---------------------------------------------------------------------------
# Section / label maps — identical to rule_engine.py in specialist_clinic
# ---------------------------------------------------------------------------
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
    "redflags": "هشدارهای فوری",
    "risk": "ریسک",
    "treatment": "پیشنهادهای درمان",
    "safety": "ایمنی و منع دارو",
    "assessment": "ارزیابی و اهداف",
    "monitoring": "پایش و غربالگری",
    "vaccination": "واکسیناسیون",
    "lifestyle": "سبک زندگی و آموزش",
}
SECTION_ORDER = [
    "redflags", "safety", "risk", "treatment", "assessment",
    "monitoring", "vaccination", "lifestyle",
]
_SEVERITY_RANK = {"urgent": 0, "warn": 1, "info": 2}

# ---------------------------------------------------------------------------
# Static fallback thresholds (last resort — same as vitals_service.THRESHOLDS)
# Only used when clinical_indicators row is missing for the key.
# ---------------------------------------------------------------------------
_FALLBACK_THRESHOLDS = {
    "hba1c":        {"warn": 7.0,  "danger": 8.0,  "direction": "high"},
    "fbs":          {"warn": 130,  "danger": 180,   "direction": "high"},
    "bp_systolic":  {"warn": 130,  "danger": 140,   "direction": "high"},
    "bp_diastolic": {"warn": 80,   "danger": 90,    "direction": "high"},
}


# ---------------------------------------------------------------------------
# Indicator-driven reading evaluation (direction-aware)
# Mirrors clinical_rules_service.evaluate() exactly.
# ---------------------------------------------------------------------------
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _evaluate_indicator(indicator_row, value) -> str:
    """Return 'danger' | 'warn' | 'ok' for a value against one indicator.

    Ported from specialist_clinic/src/services/clinical_rules_service.py::evaluate.
    Honors `direction`: 'high' = larger is worse, 'low' = smaller is worse.
    """
    val = _num(value)
    if val is None or not indicator_row:
        return "ok"
    warn = _num(indicator_row.get("warn") if isinstance(indicator_row, dict) else indicator_row.warn)
    danger = _num(indicator_row.get("danger") if isinstance(indicator_row, dict) else indicator_row.danger)
    direction = (
        (indicator_row.get("direction") if isinstance(indicator_row, dict) else indicator_row.direction)
        or "high"
    ).lower()
    if direction == "low":
        if danger is not None and val <= danger:
            return "danger"
        if warn is not None and val <= warn:
            return "warn"
        return "ok"
    # default: high is worse
    if danger is not None and val >= danger:
        return "danger"
    if warn is not None and val >= warn:
        return "warn"
    return "ok"


def _evaluate_reading(vtype: str, value, indicator_map: dict) -> str:
    """
    Return 'danger' | 'warn' | 'ok' from clinical_indicators (live source).
    Falls back to static map if indicator not found.
    Mirrors vitals_service.evaluate_reading().
    """
    if value is None:
        return "ok"
    ind = indicator_map.get(vtype)
    if ind:
        return _evaluate_indicator(ind, value)
    fb = _FALLBACK_THRESHOLDS.get(vtype)
    if fb:
        return _evaluate_indicator(fb, value)
    return "ok"


# ---------------------------------------------------------------------------
# Age helper — same logic as rule_engine.py::_age_from_birthdate
# ---------------------------------------------------------------------------
def _age_from_birthdate(bd) -> int | None:
    """Robust age: handles gregorian or Jalali year in birthdate string."""
    if not bd:
        return None
    digits = "".join(ch for ch in str(bd) if ch.isdigit())
    if len(digits) < 4:
        return None
    year = int(digits[:4])
    now_g = datetime.now().year
    if year < 1500:  # Jalali year → approximate gregorian
        year += 621
    age = now_g - year
    return age if 0 < age < 130 else None


def _truthy(v) -> bool:
    return v not in (None, "", "0", "false", "False", "no", "off")


# ---------------------------------------------------------------------------
# Fact assembly — build_facts(patient_link_id)
# ---------------------------------------------------------------------------
def build_facts(patient_link_id: int, demographics=None, tenant_id: int = 1) -> dict:
    """
    Assemble the fact bundle for one patient from Postgres.

    Parameters
    ----------
    patient_link_id : int
        clinical.patient_links.id — the local enrollment PK.
    demographics : PatientDTO | None
        Optional accounting demographics (provides birthdate for age).
    tenant_id : int
        Tenant scope for all queries.

    Returns
    -------
    dict with keys:
        age         : int | None
        conditions  : set[str]   — active condition codes
        indicator   : dict[str, {"latest": float, "level": str}]
        flag        : dict[str, str | None]   — patient flag values
        med_classes : set[str]  — active medication drug_class values
    """
    # --- age ------------------------------------------------------------------
    age = None
    if demographics is not None:
        age = _age_from_birthdate(getattr(demographics, "birthdate", None))

    # --- conditions -----------------------------------------------------------
    # Fetch active patient_conditions → join conditions to get code
    active_pcs = PatientCondition.objects.filter(
        patient_link_id=patient_link_id,
        tenant_id=tenant_id,
        is_active=True,
    ).values_list("condition_id", flat=True)

    condition_codes: set[str] = set()
    if active_pcs:
        cond_rows = Condition.objects.filter(
            id__in=list(active_pcs),
            tenant_id=tenant_id,
        ).values("code")
        condition_codes = {r["code"] for r in cond_rows if r["code"]}

    # --- clinical_indicators map (keyed by indicator.key) ---------------------
    indicator_map: dict = {
        row.key: row
        for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
    }

    # --- observations (vitals + labs, latest per obs_key) ---------------------
    # ADR-0005: read from the canonical VIEW clinical.observations which UNION
    # ALLs vital_readings and lab_results into one source-agnostic stream.
    #
    # obs_key is namespace-prefixed since slice4a:
    #   vitals → 'vital:<type>'           e.g. 'vital:hba1c'
    #   labs   → 'lab:<test_key or name>' e.g. 'lab:egfr', 'lab:اسم آزاد'
    #
    # DISTINCT ON obs_key (Postgres-specific ORM distinct("obs_key")) gives the
    # latest observation per namespaced-key across BOTH sources after ordering by
    # (obs_key, -observed_at).  Vitals still appear exactly as before (they're in
    # the VIEW); labs now appear too.
    #
    # We strip the 'vital:'/'lab:' prefix before indexing indicator_facts because:
    #   - The indicator_map (clinical_indicators.key) uses bare keys ('hba1c', 'egfr')
    #   - The DSL trigger resolver (_resolve) looks up indicator_facts['hba1c'] etc.
    #
    # For obs_keys WITHOUT a matching clinical_indicators row (e.g. a free-text lab
    # whose test_key is NULL → obs_key = 'lab:<Persian test_name>'), _evaluate_reading
    # returns the fail-safe level='ok' — but the value still lands in indicator_facts
    # so value-based DSL leaves (indicator.X.latest >=/>/<...) still fire correctly.
    latest_per_obs_key_qs = (
        Observation.objects.filter(
            patient_link_id=patient_link_id,
            tenant_id=tenant_id,
        )
        .order_by("obs_key", "-observed_at")
        .distinct("obs_key")
    )

    indicator_facts: dict = {}
    for obs in latest_per_obs_key_qs:
        # obs_key is namespace-prefixed since slice4a: 'vital:<type>' or 'lab:<key>'.
        # The indicator map (clinical_indicators.key) and DSL triggers use bare keys
        # (e.g. 'hba1c', 'egfr'). Strip the prefix to get the canonical bare key.
        raw_key = obs.obs_key or ""
        if raw_key.startswith("vital:"):
            bare_key = raw_key[len("vital:"):]
        elif raw_key.startswith("lab:"):
            bare_key = raw_key[len("lab:"):]
        else:
            bare_key = raw_key  # no prefix (legacy / unexpected) — use as-is
        if not bare_key:
            continue
        level = _evaluate_reading(bare_key, obs.value, indicator_map)
        indicator_facts[bare_key] = {"latest": obs.value, "level": level}

    # --- patient_flags --------------------------------------------------------
    flag_rows = PatientFlag.objects.filter(
        patient_link_id=patient_link_id,
        tenant_id=tenant_id,
    ).values("flag_key", "value")
    flags: dict = {r["flag_key"]: r["value"] for r in flag_rows}

    # --- active medication drug_classes ---------------------------------------
    med_classes: set[str] = set()
    med_rows = PatientMedication.objects.filter(
        patient_link_id=patient_link_id,
        tenant_id=tenant_id,
        is_active=True,
    ).values("drug_class")
    for m in med_rows:
        if m["drug_class"]:
            med_classes.add(m["drug_class"])

    return {
        "age": age,
        "conditions": condition_codes,
        "indicator": indicator_facts,
        "flag": flags,
        "med_classes": med_classes,
    }


# ---------------------------------------------------------------------------
# DSL Evaluator — ported EXACTLY from rule_engine.py
# Operators: all / any / not (combinators) + var/op/value leaf nodes
# ---------------------------------------------------------------------------

def _resolve(var: str, facts: dict):
    """Resolve a variable name from the fact bundle.

    Mirrors RuleEngine._resolve() exactly — same var names, same structure.
    """
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
    """Evaluate a leaf node. Ported EXACTLY from RuleEngine._leaf()."""
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
    """Recursive combinator evaluation. Ported EXACTLY from RuleEngine._eval()."""
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate(patient_link_id: int, demographics=None, tenant_id: int = 1) -> list[dict]:
    """
    Return the list of fired rules for a patient (suggestion-only).

    Loads clinical_rules from Postgres filtered to:
      - is_active=True
      - condition_code matches the patient's active conditions OR condition_code='all'
      - trigger_json is not NULL (NULL = informational/reference-only, not fireable)

    Each returned rule dict carries:
      - all clinical_rules columns
      - section: str   — UI bucket key
      - suggestion_only: True   — always present (safety marker)
    """
    facts = build_facts(patient_link_id, demographics=demographics, tenant_id=tenant_id)
    patient_conditions = facts["conditions"]

    # Load only rules whose condition_code is relevant (+ 'all' cross-disease)
    # This mirrors evaluate() in rule_engine.py which loads ALL rules but
    # conditions gating happens inside trigger_json. We pre-filter for efficiency
    # while still evaluating trigger_json for the {not: DM} style gating.
    condition_filter = list(patient_conditions) + ["all"]
    rules_qs = ClinicalRule.objects.filter(
        tenant_id=tenant_id,
        is_active=True,
        condition_code__in=condition_filter,
    ).exclude(trigger_json=None).order_by("priority", "id")

    fired = []
    for rule in rules_qs:
        try:
            trig = rule.trigger_json  # JSONB — already a dict from Django ORM
            if trig is None:
                continue
            # trigger_json may come as string if driver doesn't auto-decode
            if isinstance(trig, str):
                try:
                    trig = json.loads(trig)
                except (ValueError, TypeError):
                    continue
        except Exception:
            continue

        try:
            if _eval(trig, facts):
                try:
                    params = rule.action_params_json or {}
                    if isinstance(params, str):
                        params = json.loads(params)
                except (ValueError, TypeError):
                    params = {}
                section = SECTION.get(rule.action_type, "lifestyle")
                fired.append({
                    "id": rule.id,
                    "rule_code": rule.rule_code,
                    "title": rule.title,
                    "category": rule.category,
                    "condition_code": rule.condition_code,
                    "recommendation": rule.recommendation,
                    "dosage_titration": rule.dosage_titration,
                    "monitoring": rule.monitoring,
                    "contraindications": rule.contraindications,
                    "evidence_level": rule.evidence_level,
                    "action_type": rule.action_type,
                    "params": params,
                    "severity": rule.severity,
                    "priority": rule.priority,
                    "source_ref": rule.source_ref,
                    "section": section,
                    "suggestion_only": True,  # safety marker — always present
                })
        except Exception:
            continue

    fired.sort(
        key=lambda x: (
            _SEVERITY_RANK.get(x.get("severity"), 3),
            x.get("priority", 100),
        )
    )
    return fired


def grouped(patient_link_id: int, demographics=None, tenant_id: int = 1) -> dict:
    """
    Fired rules grouped into UI sections, in display order.

    Mirrors RuleEngine.grouped() exactly.
    """
    fired = evaluate(patient_link_id, demographics=demographics, tenant_id=tenant_id)
    groups: dict = {}
    for r in fired:
        groups.setdefault(r["section"], []).append(r)
    return {
        "sections": [
            {"key": s, "label": SECTION_LABELS[s], "rules": groups[s]}
            for s in SECTION_ORDER
            if s in groups
        ],
        "count": len(fired),
        "has_redflag": any(r["section"] == "redflags" for r in fired),
    }
