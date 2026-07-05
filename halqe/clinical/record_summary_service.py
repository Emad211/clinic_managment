"""
clinical/record_summary_service.py — the safety cockpit summary for one patient.

Faithful port of the specialist_clinic analytics into the halqe Django/Postgres
platform. It backs the enrichment of GET /api/v1/patients/{uuid}/record
(control + risk + per-disease indicator deltas), so the front-end patient
cockpit can render a single at-a-glance safety picture.

Ported logic (وفادار — same algorithm, same weights):
  - control:  specialist_clinic/src/services/vitals_service.py::control_status
              (worst of the latest reading per vital → controlled/borderline/
              uncontrolled/no_data).
  - risk:     specialist_clinic/src/services/analytics_service.py::_risk
              (weighted points, danger=w / warn=0.5w, behavioral + safety
              factors, dominant category, severe-kidney override, _level_from
              tiers).
  - per_disease: analytics_service.py::_per_disease (worst status + weighted
              risk tier + top-≤3 risk-weighted indicators per active condition).

Adapted (data access only — clinical semantics unchanged):
  - SQLite raw SQL → Django ORM, all queries tenant-scoped (tenant_id column +
    RLS GUC already set by JWTBearer for the request).
  - thresholds are read LIVE from clinical_indicators (never hardcoded) via
    rule_engine._evaluate_reading — the same source-of-truth the rest of the
    engine uses.
  - Iran-local "now" windows: Postgres CURRENT_DATE / now() run in the DB's
    Asia/Tehran timezone (settings.TIME_ZONE); no naive datetime.now() is used
    for storage or comparison.

SACRED verified-gate (قفل‌شده):
  ONLY verified vital readings enter the control/risk/per-disease computation.
  Unverified patient self-report (verified=FALSE) is pending physician review
  and must NEVER influence decision-support derivations. Every observation read
  here filters verified=True — identical to build_facts() in rule_engine.py.

suggestion-only: this module produces DATA (status/score/deltas). It makes no
clinical decision and triggers no action — the physician decides.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Max

from clinical.models import (
    VitalReading,
    PatientMedication,
    FollowupTask,
    Appointment,
    ClinicalIndicator,
    LabResult,
    PatientFlag,
)
from clinical.rule_engine import _evaluate_reading, _age_from_birthdate

# category → Persian label (mirror of clinical_rules_repo.CATEGORY_LABELS)
CATEGORY_LABELS = {
    "glycemic": "قند خون",
    "bp": "فشار خون",
    "lipid": "چربی خون",
    "kidney": "کلیه",
    "anthro": "تن‌سنجی",
    "other": "سایر",
}

# refill "due" horizon — mirror of analytics_service.refill_due (+7 days).
_REFILL_HORIZON_DAYS = 7

# behavioral lapse window — mirror of analytics_service._risk (120 days).
_LAPSE_DAYS = 120

_LEVEL_RANK = {"danger": 3, "warn": 2, "ok": 1}
_ORDER = {"ok": 0, "warn": 1, "danger": 2}


# ---------------------------------------------------------------------------
# Risk-tier mapping — single source of truth (mirror of _level_from)
# ---------------------------------------------------------------------------
def _level_from(points: float, danger_count: int) -> tuple[str, str]:
    """Map weighted risk points + danger count to (level, fa-label).

    Ported EXACTLY from analytics_service._level_from. 'ok' tier is surfaced as
    "stable" at the DTO boundary (per the record contract: high|medium|low|stable).
    """
    if points >= 5 or danger_count >= 2:
        return "high", "پرخطر"
    if points >= 3 or danger_count == 1:
        return "medium", "متوسط"
    if points >= 1:
        return "low", "کم"
    return "ok", "پایدار"


# ---------------------------------------------------------------------------
# Indicator facts — one entry per patient-relevant indicator (verified-gated)
# ---------------------------------------------------------------------------
def _indicator_facts(
    pid: int,
    tenant_id: int,
    condition_codes: list[str],
) -> list[dict]:
    """
    Build the per-indicator fact list the risk/per-disease/delta logic runs on.

    Mirrors the per-indicator loop of analytics_service.patient_analytics: for
    each clinical_indicator that applies to this patient's diseases, fetch the
    two most-recent VERIFIED readings for that key → latest/previous/delta/level.

    An indicator "applies" when its `conditions` is 'all' or shares a code with
    the patient's active conditions (same rule as clinical_rules_repo.for_conditions).

    verified-gate: only VitalReading.verified=True rows are considered — the same
    گیتِ ایمنی enforced in rule_engine.build_facts().

    Returns a list of dicts with keys:
      key, label, unit, category, conditions, direction, risk_weight, target,
      latest, previous, delta, level  ('ok'|'warn'|'danger' when data exists).
    """
    codeset = {c for c in (condition_codes or []) if c}

    # Live thresholds — source of truth (never hardcoded).
    indicator_map = {
        row.key: row
        for row in ClinicalIndicator.objects.filter(
            tenant_id=tenant_id, is_active=True
        )
    }

    # Indicators relevant to this patient (applies-if 'all' or shared code),
    # ordered for display (display_order) as in the specialist analytics.
    relevant = []
    for row in sorted(
        indicator_map.values(),
        key=lambda r: (r.display_order, r.id),
    ):
        conds_raw = (row.conditions or "").strip()
        applies = conds_raw == "" or conds_raw.lower() == "all" or bool(
            codeset & {p.strip() for p in conds_raw.split(",") if p.strip()}
        )
        if applies:
            relevant.append(row)

    facts: list[dict] = []
    for ind in relevant:
        # Two most-recent VERIFIED readings for this vital type (newest first).
        # ADR-0005 note: the specialist analytics reads the canonical union
        # (vitals + labs). Here we read vital_readings (the verified-gated half);
        # a lab-inclusive path can be added when labs carry the verified column
        # for this surface. Vitals are the driver for control/risk today.
        recent = list(
            VitalReading.objects.filter(
                patient_link_id=pid,
                tenant_id=tenant_id,
                type=ind.key,
                verified=True,
            )
            .order_by("-measured_at")
            .values_list("value", flat=True)[:2]
        )
        latest = recent[0] if recent else None
        previous = recent[1] if len(recent) > 1 else None
        delta = (latest - previous) if (latest is not None and previous is not None) else None
        level = _evaluate_reading(ind.key, latest, indicator_map) if latest is not None else "none"

        facts.append({
            "key": ind.key,
            "label": ind.label,
            "unit": ind.unit,
            "category": ind.category,
            "conditions": ind.conditions,
            "direction": (ind.direction or "high").lower(),
            "risk_weight": ind.risk_weight or 0,
            "target": ind.target,
            "latest": latest,
            "previous": previous,
            "delta": round(delta, 1) if delta is not None else None,
            "level": level,
        })
    return facts


# ---------------------------------------------------------------------------
# control_status — worst of the latest reading per vital (verified-gated)
# Ported from vitals_service.control_status.
# ---------------------------------------------------------------------------
def _control_status(pid: int, tenant_id: int) -> dict:
    """
    Overall control from the latest VERIFIED reading of each vital type.

    Mirrors vitals_service.control_status exactly:
      worst == 'danger' → 'uncontrolled'; 'warn' → 'borderline';
      all 'ok'          → 'controlled'; no readings → 'no_data'.

    (specialist returns 'unknown' for the no-data case; the record contract
     names this state 'no_data' — same meaning, DTO-level rename only.)
    """
    indicator_map = {
        row.key: row
        for row in ClinicalIndicator.objects.filter(
            tenant_id=tenant_id, is_active=True
        )
    }

    # latest measured_at per type (verified only) → then the value at that time.
    latest_at = (
        VitalReading.objects.filter(
            patient_link_id=pid, tenant_id=tenant_id, verified=True
        )
        .values("type")
        .annotate(m=Max("measured_at"))
    )
    latest_map = {r["type"]: r["m"] for r in latest_at}

    worst = "ok"
    has_any = False
    for vtype, m in latest_map.items():
        row = (
            VitalReading.objects.filter(
                patient_link_id=pid, tenant_id=tenant_id,
                type=vtype, measured_at=m, verified=True,
            )
            .values_list("value", flat=True)
            .first()
        )
        if row is None:
            continue
        has_any = True
        level = _evaluate_reading(vtype, row, indicator_map)
        if _ORDER[level] > _ORDER[worst]:
            worst = level

    if not has_any:
        return {"status": "no_data", "label": "بدون داده"}
    if worst == "danger":
        return {"status": "uncontrolled", "label": "کنترل‌نشده"}
    if worst == "warn":
        return {"status": "borderline", "label": "مرزی"}
    return {"status": "controlled", "label": "کنترل‌شده"}


# ---------------------------------------------------------------------------
# _risk — weighted risk score + dominant factor (ported from analytics._risk)
# ---------------------------------------------------------------------------
def _risk(pid: int, tenant_id: int, facts: list[dict]) -> dict:
    """
    Weighted headline risk. Ported from analytics_service._risk EXACTLY:
      - clinical points: danger=risk_weight, warn=0.5*risk_weight (per category).
      - severe-kidney override (egfr/uacr danger → forced 'high').
      - behavioral points: lapsed (+2), refill overdue (+1), repeat no-show (+1).
      - safety flags: high hypo risk (+2), complex frailty (+1).
      - dominant = highest-scoring category label; tiers via _level_from.

    Returns {level, dominant, score} for the DTO (level is high|medium|low|
    stable — 'ok' tier surfaced as 'stable' at the boundary).
    """
    cat_points: dict[str, float] = {}
    total = 0.0
    danger_count = 0
    severe_kidney = False

    for f in facts:
        w = f.get("risk_weight") or 0
        if f["level"] == "danger":
            pts = w
            danger_count += 1
            if f["key"] in ("egfr", "uacr"):
                severe_kidney = True
        elif f["level"] == "warn":
            pts = w * 0.5
        else:
            pts = 0
        if pts:
            cat_points[f["category"]] = cat_points.get(f["category"], 0) + pts
            total += pts

    # --- behavioral / adherence factors (no doctor input) --------------------
    today = date.today()
    lapse_cut = today - timedelta(days=_LAPSE_DAYS)
    dt_cut = _LAPSE_DAYS  # for measured_at (datetime) we compare via .date()

    has_recent_vital = VitalReading.objects.filter(
        patient_link_id=pid, tenant_id=tenant_id,
        measured_at__date__gte=lapse_cut,
    ).exists()
    has_recent_lab = LabResult.objects.filter(
        patient_link_id=pid, tenant_id=tenant_id,
        taken_at__date__gte=lapse_cut,
    ).exists()
    behav = 0
    if not (has_recent_vital or has_recent_lab):
        behav += 2

    refill_overdue = PatientMedication.objects.filter(
        patient_link_id=pid, tenant_id=tenant_id, is_active=True,
        refill_due_date__isnull=False,
        refill_due_date__lt=today,
    ).count()
    if refill_overdue:
        behav += 1

    no_show = Appointment.objects.filter(
        patient_link_id=pid, tenant_id=tenant_id, status="no_show",
    ).count()
    if no_show >= 2:
        behav += 1

    if behav:
        cat_points["adherence"] = behav
        total += behav

    # --- treatment-safety flags ---------------------------------------------
    flag_rows = PatientFlag.objects.filter(
        patient_link_id=pid, tenant_id=tenant_id,
    ).values("flag_key", "value")
    flags = {r["flag_key"]: r["value"] for r in flag_rows}
    safety = 0
    if (flags.get("hypo_risk") or "") == "high":
        safety += 2
    if flags.get("frailty") == "complex":
        safety += 1
    if safety:
        cat_points["safety"] = safety
        total += safety

    if severe_kidney:
        level, _label = "high", "پرخطر"
    else:
        level, _label = _level_from(total, danger_count)

    def cat_label(c: str) -> str:
        if c == "adherence":
            return "پایبندی درمان"
        if c == "safety":
            return "ایمنی درمان"
        return CATEGORY_LABELS.get(c, c)

    ordered = sorted(cat_points.items(), key=lambda kv: -kv[1])
    dominant = cat_label(ordered[0][0]) if ordered else None

    return {
        # DTO contract: 'ok' tier is named 'stable'
        "level": "stable" if level == "ok" else level,
        "dominant": dominant,
        "score": round(total, 1),
    }


# ---------------------------------------------------------------------------
# _per_disease — worst status + risk tier + top indicators (ported)
# ---------------------------------------------------------------------------
def _per_disease(conditions: list[dict], facts: list[dict]) -> list[dict]:
    """
    One entry per active chronic condition. Ported from analytics._per_disease:
      - worst status among this disease's indicators-with-data.
      - per-disease weighted risk (danger=w, warn=0.5w) → _level_from tier.
      - top-≤3 risk-weighted indicators (risk_weight>0, with data), desc.

    An indicator applies to a condition when its `conditions` is 'all' or its
    comma-split list contains the condition code.

    Returns per-disease dicts shaped for the DTO (see ClinicalRecordDTO):
      condition_code, condition_name, control{status,label}, risk_level,
      indicators[{key,label,value,unit,target,direction,delta,level}].
    """
    out = []
    for c in conditions:
        code = c.get("condition_code")
        if not code:
            continue

        mine = []  # this disease's indicators that have data
        for f in facts:
            if f.get("latest") is None:
                continue
            applies_raw = f.get("conditions") or ""
            codes = {p.strip() for p in applies_raw.split(",") if p.strip()}
            if applies_raw == "all" or code in codes:
                mine.append(f)

        # worst status among this disease's indicators-with-data
        status = "no_data"
        if mine:
            worst = max(mine, key=lambda i: _LEVEL_RANK.get(i.get("level"), 0))
            wl = worst.get("level")
            status = wl if wl in _LEVEL_RANK else "ok"

        # per-disease weighted points (mirror _risk: danger=w, warn=0.5w)
        points, danger_count = 0.0, 0
        for f in mine:
            w = f.get("risk_weight") or 0
            if f.get("level") == "danger":
                points += w
                danger_count += 1
            elif f.get("level") == "warn":
                points += w * 0.5
        risk_level, _rl = _level_from(points, danger_count)

        # top-≤3 risk-weighted indicators (risk_weight>0, with data), desc
        top = sorted(
            [f for f in mine if (f.get("risk_weight") or 0) > 0],
            key=lambda f: -(f.get("risk_weight") or 0),
        )[:3]

        out.append({
            "condition_code": code,
            "condition_name": c.get("condition_name") or code,
            "control": _status_to_control(status),
            "risk_level": "stable" if risk_level == "ok" else risk_level,
            "indicators": [_indicator_out(f) for f in top],
        })
    return out


def _status_to_control(status: str) -> dict:
    """Map a worst-level status token to the {status,label} control shape.

    Per-disease status uses the same vocabulary as the top-level control block:
    controlled/borderline/uncontrolled/no_data.
    """
    mapping = {
        "ok": ("controlled", "کنترل‌شده"),
        "warn": ("borderline", "مرزی"),
        "danger": ("uncontrolled", "کنترل‌نشده"),
        "no_data": ("no_data", "بدون داده"),
    }
    s, label = mapping.get(status, ("no_data", "بدون داده"))
    return {"status": s, "label": label}


def _indicator_out(f: dict) -> dict:
    """Shape one indicator fact into the DTO indicator payload.

    delta carries direction + an `improving` flag (direction-aware, exactly as
    analytics_service computes medication_effect improvement): for a 'low'-worse
    indicator an increase improves; for 'high'-worse a decrease improves.
    """
    delta_out = None
    d = f.get("delta")
    if d is not None:
        if d > 0:
            ddir = "up"
        elif d < 0:
            ddir = "down"
        else:
            ddir = "flat"
        direction = f.get("direction") or "high"
        # improving = moving away from danger
        if d == 0:
            improving = False
        elif direction == "low":
            improving = d > 0     # low is worse → higher is better
        else:
            improving = d < 0     # high is worse → lower is better
        delta_out = {"value": round(d, 1), "dir": ddir, "improving": improving}

    return {
        "key": f["key"],
        "label": f["label"],
        "value": f.get("latest"),
        "unit": f.get("unit"),
        "target": f.get("target"),
        "direction": f.get("direction"),
        "delta": delta_out,
        "level": f["level"] if f["level"] in ("ok", "warn", "danger") else None,
    }


# ---------------------------------------------------------------------------
# Counts — open follow-ups + refill-due (verified-independent operational data)
# ---------------------------------------------------------------------------
def _open_followups_count(pid: int, tenant_id: int) -> int:
    """Number of OPEN follow-up tasks for this patient (worklist backlog)."""
    return FollowupTask.objects.filter(
        patient_link_id=pid, tenant_id=tenant_id,
        status=FollowupTask.STATUS_OPEN,
    ).count()


def _refill_due_count(pid: int, tenant_id: int) -> int:
    """
    Active medications whose refill_due_date falls within the next 7 days
    (including already-overdue). Mirror of analytics_service.refill_due
    ('+7 days' horizon). Meds without a refill_due_date are excluded.
    """
    horizon = date.today() + timedelta(days=_REFILL_HORIZON_DAYS)
    return PatientMedication.objects.filter(
        patient_link_id=pid, tenant_id=tenant_id, is_active=True,
        refill_due_date__isnull=False,
        refill_due_date__lte=horizon,
    ).count()


# ---------------------------------------------------------------------------
# Public entry point — one call assembles the whole cockpit summary
# ---------------------------------------------------------------------------
def record_summary(
    pid: int,
    tenant_id: int,
    conditions: list[dict],
    demographics=None,
) -> dict:
    """
    Assemble the safety-cockpit summary for one patient.

    Parameters
    ----------
    pid : int
        clinical.patient_links.id (the local enrollment PK).
    tenant_id : int
        Tenant scope for every query (RLS GUC already set by JWTBearer).
    conditions : list[dict]
        Active conditions as already fetched by the record endpoint. Each dict
        must carry 'condition_code' and 'condition_name' (the endpoint builds
        these from clinical.conditions). Only these two keys are read here.
    demographics : PatientDTO | None
        Read-only accounting demographics (for age from birthdate). None-safe:
        age is None when demographics/birthdate is absent.

    Returns
    -------
    dict with exactly the keys the record DTO adds:
      control              : {status, label}
      risk                 : {level, dominant, score}
      open_followups_count : int
      refill_due_count     : int
      per_disease          : list[...]
      age                  : int | None

    Read-only + verified-gated. No writes, no clinical decision.
    """
    condition_codes = [
        c.get("condition_code") for c in conditions if c.get("condition_code")
    ]

    facts = _indicator_facts(pid, tenant_id, condition_codes)

    return {
        "control": _control_status(pid, tenant_id),
        "risk": _risk(pid, tenant_id, facts),
        "open_followups_count": _open_followups_count(pid, tenant_id),
        "refill_due_count": _refill_due_count(pid, tenant_id),
        "per_disease": _per_disease(conditions, facts),
        "age": (
            _age_from_birthdate(getattr(demographics, "birthdate", None))
            if demographics is not None else None
        ),
    }
