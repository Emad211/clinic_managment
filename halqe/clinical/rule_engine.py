"""
Faithful port of specialist_clinic/src/services/rule_engine.py
into the halqe Django/Postgres platform.

The trigger_json DSL evaluator (_eval / _leaf) is ported EXACTLY — same
operators, same semantics — because this is safety-relevant decision support.

Output is SUGGESTION-ONLY: "پیشنهاد — تأیید با پزشک".
Every fired rule carries `suggestion_only=True`.

Facts assembled from Postgres via Django ORM:
  - latest observations per obs_key  (clinical.observations VIEW — UNION of
    vital_readings + lab_results; ADR-0005). Wired since cluster-B (slice4a).
  - active condition codes             (patient_conditions → conditions)
  - patient_flags (categorical/bool)  (patient_flags)
  - active medications' drug_class set (patient_medications)
  - thresholds from clinical_indicators (NOT hardcoded; static map = fallback)
  - age: derived from demographics.birthdate (PatientDTO), supplied by the
    caller (suggestion_service.grouped_for_patient / evaluate_for_patient
    fetch it from the read-only accounting Port). When demographics is None,
    age=None — age-gated rules are fail-closed (they don't fire rather than
    producing wrong suggestions). This is intentional safe behaviour, not a bug.

Data-gap transparency (data_gaps()):
  A helper that identifies which vars required by active rules are absent from
  the current fact bundle. Covers only `age` and `indicator.*` vars — flags,
  conditions, and med.class are patient state (not missing data). The result
  list powers the UI "قاعدهٔ خاموش" banner without changing fire behaviour.
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
    DdiPair,
)
from clinical.population_service import patient_populations, apply_population_overrides

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
    # slice13 safety gate: ONLY verified observations enter the engine.
    # verified=FALSE rows are patient self-report pending physician review.
    # They must NEVER influence clinical decision support until a physician
    # explicitly verifies them (step 47). This filter is the "گیتِ ایمنی".
    latest_per_obs_key_qs = (
        Observation.objects.filter(
            patient_link_id=patient_link_id,
            tenant_id=tenant_id,
            verified=True,
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

    # --- population-specific threshold overrides (Step 39) --------------------
    # Only 'approved' + bound='high' overrides are applied; 'draft' are inert.
    # This runs AFTER indicator_map and observations are assembled so that
    # _evaluate_reading in the loop above still uses the base indicator_map.
    # The effective indicator_map for DSL evaluation (used by _resolve in _leaf)
    # is produced here and stored in facts["_indicator_map_effective"]:
    #   - Before any override is approved: same as base indicator_map.
    #   - After an override is approved: only the approved fields are swapped.
    # NOTE: indicator_facts (the per-patient observation level/value dict) is
    # recomputed after the override so that level evaluation also honours
    # population thresholds.
    populations = patient_populations(flags, age)
    effective_indicator_map = apply_population_overrides(
        indicator_map, populations, tenant_id
    )

    # Re-evaluate levels for indicator_facts using the effective map.
    # This re-pass is cheap (small dict; no extra DB query) and ensures that
    # if an override is approved, the 'level' in indicator_facts reflects it.
    if effective_indicator_map is not indicator_map:
        # At least one override was applied — re-evaluate levels
        for bare_key, fact_entry in indicator_facts.items():
            new_level = _evaluate_reading(
                bare_key, fact_entry.get("latest"), effective_indicator_map
            )
            fact_entry["level"] = new_level

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
        # Internal: effective indicator_map after population overrides.
        # Used by _resolve() for threshold-gated DSL leaves (indicator.X.level).
        # Callers outside rule_engine should not depend on this key.
        "_indicator_map": effective_indicator_map,
        # Track which populations were detected (useful for tests + future UI)
        "_populations": populations,
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
# Data-gap helpers — "قاعدهٔ خاموش" transparency
# ---------------------------------------------------------------------------

def _referenced_vars(node) -> set[str]:
    """
    Recursively collect all `var` values from a trigger_json node tree.

    Walks the all/any/not combinator tree and returns every leaf `var` string
    found. Used by data_gaps() to determine which fact keys a rule depends on.

    Parameters
    ----------
    node : dict | None
        A trigger_json node: {"all": [...]} / {"any": [...]} / {"not": ...} /
        {"var": "...", "op": "...", "value": ...}.

    Returns
    -------
    set[str]  — all var strings referenced anywhere in the subtree.
    """
    if node is None:
        return set()
    if "all" in node:
        result: set[str] = set()
        for child in node["all"]:
            result |= _referenced_vars(child)
        return result
    if "any" in node:
        result = set()
        for child in node["any"]:
            result |= _referenced_vars(child)
        return result
    if "not" in node:
        return _referenced_vars(node["not"])
    if "var" in node:
        return {node["var"]}
    return set()


def _compute_data_gaps(
    facts: dict,
    rules_qs,
    tenant_id: int,
) -> list[dict]:
    """
    Internal: compute data gaps given an already-assembled facts bundle and rules queryset.

    Separated so grouped() can call this with the same rules_qs it already iterated,
    avoiding redundant DB queries.

    Parameters
    ----------
    facts     : dict from build_facts()
    rules_qs  : evaluated queryset of ClinicalRule rows (already fetched)
    tenant_id : for label_map query

    Returns
    -------
    list[dict] — same shape as data_gaps() public API.
    """
    # Collect all referenced vars across ALL active rules (one pass over the list)
    var_rule_counts: dict[str, int] = {}
    for rule in rules_qs:
        try:
            trig = rule.trigger_json
            if trig is None:
                continue
            if isinstance(trig, str):
                try:
                    trig = json.loads(trig)
                except (ValueError, TypeError):
                    continue
        except Exception:
            continue
        for var in _referenced_vars(trig):
            var_rule_counts[var] = var_rule_counts.get(var, 0) + 1

    # Label map for indicator keys — minimal DB projection (key + label only)
    label_map: dict[str, str] = {
        row["key"]: row["label"]
        for row in ClinicalIndicator.objects.filter(
            tenant_id=tenant_id, is_active=True
        ).values("key", "label")
    }

    # Build gap entries (before dedup)
    raw_gaps: list[dict] = []
    for var, count in var_rule_counts.items():
        if var == "age":
            if facts.get("age") is None:
                raw_gaps.append({"datum": "age", "label": "سن", "affected_rules": count})
        elif var.startswith("indicator."):
            parts = var.split(".")
            bare_key = parts[1] if len(parts) > 1 else ""
            if not bare_key:
                continue
            if bare_key not in facts["indicator"]:
                label = label_map.get(bare_key, bare_key)
                raw_gaps.append({
                    "datum": bare_key,
                    "label": label,
                    "affected_rules": count,
                })
        # flag.*, condition, med.class — patient state, not data gaps

    # Deduplicate by datum (indicator.egfr.latest + indicator.egfr.level → "egfr")
    merged: dict[str, dict] = {}
    for g in raw_gaps:
        d = g["datum"]
        if d in merged:
            merged[d]["affected_rules"] += g["affected_rules"]
        else:
            merged[d] = dict(g)

    return sorted(merged.values(), key=lambda x: -x["affected_rules"])


def data_gaps(
    patient_link_id: int,
    demographics=None,
    tenant_id: int = 1,
) -> list[dict]:
    """
    Identify which data items are missing and affect how many active rules fire.

    This function is DISPLAY-ONLY — it never changes which rules fire.
    It surfaces the "قاعدهٔ خاموش" (silent-rule) banner in the UI so physicians
    understand *why* certain rules were not evaluated.

    Scope of «missing data» (per طراحیِ قفل‌شده):
      - `age`              : None when demographics.birthdate is unavailable.
      - `indicator.<key>` : key absent from the latest observation facts.
      *** Excluded from gap detection ***:
        - `flag.*`         — patient state / categorical decision input, not missing data.
        - `condition`      — always a set (empty = no conditions registered, not a gap).
        - `med.class`      — always a set (empty = no active meds, not a gap).
        - `bmi`            — mapped through `indicator.bmi`; covered by indicator path.

    Returns
    -------
    list[dict]:
        {"datum": str, "label": str, "affected_rules": int}
    Sorted descending by affected_rules. Empty list when all required data present.
    """
    facts = build_facts(patient_link_id, demographics=demographics, tenant_id=tenant_id)
    patient_conditions = facts["conditions"]
    condition_filter = list(patient_conditions) + ["all"]
    rules_qs = list(
        ClinicalRule.objects.filter(
            tenant_id=tenant_id,
            is_active=True,
            condition_code__in=condition_filter,
        ).exclude(trigger_json=None).order_by("id")
    )
    return _compute_data_gaps(facts, rules_qs, tenant_id)


# ---------------------------------------------------------------------------
# DDI surface — موازیِ data_gaps، مستقل از evaluate/_eval
# ---------------------------------------------------------------------------

def ddi_alerts(med_classes: set, tenant_id: int = 1) -> list[dict]:
    """
    Return active DDI pairs where BOTH drug classes are present in med_classes.

    Lookup is order-independent: we canonicalize each (class_a, class_b) pair
    from the patient's medication set using tuple(sorted(...)), then filter
    clinical.ddi_pairs for rows where both classes are in med_classes.

    Parameters
    ----------
    med_classes : set[str]
        Active medication drug_class values for one patient
        (from build_facts()["med_classes"]).
    tenant_id : int
        Tenant scope.

    Returns
    -------
    list[dict] — sorted by severity (contraindicated > major > moderate > minor):
        {
            "class_a":        str,
            "class_b":        str,
            "severity":       str,   # contraindicated|major|moderate|minor
            "message_fa":     str,   # verbatim Persian clinical message
            "evidence":       str | None,
            "suggestion_only": True,  # always (safety framing)
        }
    Empty list when no active interactions found (no false-positives).

    Design notes:
    - Does NOT touch evaluate() / _eval() / triggered rule catalog.
    - is_active=False → excluded (manager-edit respects clinical decision).
    - Only fires when BOTH classes in a pair are in med_classes (no false-positive).
    - canonical check: class_a < class_b (enforced by DB CHECK; we also filter
      by class_a__in + class_b__in to leverage the index on (tenant_id, is_active)).
    """
    if not med_classes:
        return []

    # Query only active pairs where BOTH classes are present in the patient's set.
    # DB canonical order (class_a < class_b) + Python set membership check.
    qs = DdiPair.objects.filter(
        tenant_id=tenant_id,
        is_active=True,
        class_a__in=med_classes,
        class_b__in=med_classes,
    ).order_by("class_a", "class_b")

    _rank = DdiPair.SEVERITY_RANK

    alerts = [
        {
            "class_a": pair.class_a,
            "class_b": pair.class_b,
            "severity": pair.severity,
            "message_fa": pair.message_fa,
            "evidence": pair.evidence,
            "suggestion_only": True,
        }
        for pair in qs
    ]

    # Sort: contraindicated first → major → moderate → minor
    alerts.sort(key=lambda x: _rank.get(x["severity"], 99))
    return alerts


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

    Mirrors RuleEngine.grouped() — extended with `data_gaps` for
    "قاعدهٔ خاموش" UI transparency (display-only; does not change fire behaviour).

    Returns
    -------
    dict:
      sections     : list of {key, label, rules[]}
      count        : int — total fired rules
      has_redflag  : bool
      data_gaps    : list[{datum, label, affected_rules}] — empty when all data present.
                     Identifies fact vars that are absent and affect active rules,
                     so the UI can surface "N قانون به‌خاطر کمبود داده بررسی نشد".
    """
    # Assemble facts once — shared by both fire-evaluation and gap detection
    facts = build_facts(patient_link_id, demographics=demographics, tenant_id=tenant_id)
    patient_conditions = facts["conditions"]

    condition_filter = list(patient_conditions) + ["all"]
    # Materialise the queryset into a list — iterated twice (fire + gap detection)
    # without hitting the DB a second time.
    rules_list = list(
        ClinicalRule.objects.filter(
            tenant_id=tenant_id,
            is_active=True,
            condition_code__in=condition_filter,
        ).exclude(trigger_json=None).order_by("priority", "id")
    )

    fired = []
    for rule in rules_list:
        try:
            trig = rule.trigger_json
            if trig is None:
                continue
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
                    "suggestion_only": True,
                })
        except Exception:
            continue

    fired.sort(
        key=lambda x: (
            _SEVERITY_RANK.get(x.get("severity"), 3),
            x.get("priority", 100),
        )
    )

    groups: dict = {}
    for r in fired:
        groups.setdefault(r["section"], []).append(r)

    # Gap detection — reuses the already-materialised rules list (no extra DB query)
    gaps = _compute_data_gaps(facts, rules_list, tenant_id)

    # DDI surface — parallel to data_gaps, independent of the rule engine
    ddi = ddi_alerts(facts["med_classes"], tenant_id=tenant_id)

    return {
        "sections": [
            {"key": s, "label": SECTION_LABELS[s], "rules": groups[s]}
            for s in SECTION_ORDER
            if s in groups
        ],
        "count": len(fired),
        "has_redflag": any(r["section"] == "redflags" for r in fired),
        "data_gaps": gaps,
        "ddi": ddi,
    }
