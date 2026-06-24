"""
Control Room service — prioritized cohort targeting.

Faithful port of specialist_clinic/src/services/control_room_service.py
into the halqe Django/Postgres platform.

DESIGN DIFFERENCES from the Flask source (all required by ADR-0007):
  1. NO demographics mirror on patient_links. Full names / phones come from
     accounting_port.get_patients_by_ids() (one batched call). patient_link.patient_id
     IS the accounting patient id.
  2. Control vitals read from the unified `observations` VIEW (clinical.observations),
     which UNION ALLs vital_readings + lab_results. This is the same source
     build_facts() uses — so the Control Room is consistent with the engine.
     obs_key is namespace-prefixed: 'vital:<type>' or 'lab:<key>'.
     We strip the prefix to match bare keys in CONTROL_VITALS.
  3. Revenue via accounting_port.get_revenue_by_patient_ids() (read-only, keyed by
     accounting patient_id, mapped back to patient_link.id). Called ONCE, only when
     show_value is True (manager gate).
  4. timezone.now() (Django timezone-aware, Tehran-compatible via USE_TZ=True).
     Lapsed threshold: 120 days.
  5. Tenant-scoped throughout.
  6. Performance: set-based Postgres queries for the whole panel —
     NOT per-patient rule engine evaluation. Threshold evaluation uses
     rule_engine._evaluate_reading() over clinical_indicators (consistent with engine).

SCORING (clinical-first, value is seasoning only for managers):
  danger flags  : +3 per flag
  warn flags    : +1 per warn
  lapsed        : +2 (if assessable and >120 days since last vital)
  no baseline   : +1 (if no observations at all)
  open followups: +min(count, 3)
  valuable       : +1 (only if show_value AND value > median AND median > 0)
  upcoming appt  : −2

  score <= 0 → excluded from the panel.

COHORTS (clinical-first):
  uncontrolled_lapsed   : control='uncontrolled' AND lapsed
  valuable_drifting     : manager-only; value > median AND lapsed
  overdue_care          : open_fu > 0
  uncontrolled          : control='uncontrolled' (all)
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.utils import timezone

from accounting_port.port import get_patients_by_ids, get_revenue_by_patient_ids
from clinical.models import (
    PatientLink,
    Observation,
    PatientCondition,
    Condition,
    FollowupTask,
    Appointment,
    ClinicalIndicator,
)
from clinical.rule_engine import _evaluate_reading


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LAPSED_DAYS = 120

# Control-vital bare keys (without namespace prefix).
# These are the keys looked up in the observations VIEW (after stripping 'vital:' / 'lab:')
# and in clinical_indicators to get the threshold level.
CONTROL_VITALS = ["hba1c", "fbs", "bp_systolic", "bp_diastolic", "ldl", "egfr", "uacr"]

COHORT_DEFS = [
    ("uncontrolled_lapsed",  "کنترل‌نشده و بی‌مراجعه"),
    ("valuable_drifting",    "ارزشمندِ در حالِ ریزش"),
    ("overdue_care",         "مراقبتِ سررسیده"),
    ("uncontrolled",         "کنترل‌نشده (همه)"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_indicator_map(tenant_id: int) -> dict:
    """
    Return {bare_key: ClinicalIndicator} for all active indicators in this tenant.
    Used by _evaluate_reading() to apply live thresholds (same as rule_engine).
    """
    return {
        row.key: row
        for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
    }


def _classify_level(bare_key: str, value, indicator_map: dict) -> str:
    """Return 'danger' | 'warn' | 'ok' for a bare key + numeric value."""
    return _evaluate_reading(bare_key, value, indicator_map)


def _median(values: list[int]) -> int:
    """Median of a non-empty list of ints. Returns 0 for empty."""
    if not values:
        return 0
    sv = sorted(values)
    return sv[len(sv) // 2]


# ---------------------------------------------------------------------------
# Core panel builder
# ---------------------------------------------------------------------------

def panel(tenant_id: int, show_value: bool) -> dict:
    """
    Build the prioritized control-room panel for the given tenant.

    Parameters
    ----------
    tenant_id  : int  — tenant scope
    show_value : bool — True for manager (includes revenue + valuable_drifting cohort)

    Returns
    -------
    {
        patients : list[dict]   — scored + sorted patient records (score > 0 only)
        cohorts  : list[dict]   — [{key, label, count, ids}]
        median_rev : int        — median revenue over positive values (0 if n/a)
        total    : int          — len(patients)
        show_value : bool
    }
    """
    now = timezone.now()
    lapsed_cutoff = now - timedelta(days=LAPSED_DAYS)

    # ── 1. All active patient links for this tenant ───────────────────────────
    active_links = list(
        PatientLink.objects.filter(tenant_id=tenant_id, is_active=True)
        .values("id", "patient_id", "enrolled_at", "sms_opt_out")
    )
    if not active_links:
        return {
            "patients": [], "cohorts": [], "median_rev": 0,
            "total": 0, "show_value": show_value,
        }

    link_ids = [lnk["id"] for lnk in active_links]
    patient_ids = [lnk["patient_id"] for lnk in active_links]

    # ── 2. Threshold map (live clinical_indicators, same as build_facts) ──────
    indicator_map = _build_indicator_map(tenant_id)

    # ── 3. Latest observation per (patient_link_id, bare_key) ─────────────────
    # The observations VIEW uses obs_key like 'vital:hba1c' or 'lab:egfr'.
    # We need DISTINCT ON (patient_link_id, obs_key) ordered by -observed_at.
    # Postgres DISTINCT ON is not directly expressible in Django ORM, so we use
    # a raw SQL strategy: build a set-based query that gets the latest value per
    # (patient_link_id, obs_key) for the CONTROL_VITALS obs_keys only.
    # We include both namespace prefixes for each key.
    control_obs_keys = (
        [f"vital:{k}" for k in CONTROL_VITALS]
        + [f"lab:{k}" for k in CONTROL_VITALS]
    )

    # Fetch latest observation per (patient_link_id, obs_key) — Postgres DISTINCT ON
    # We build a set of (patient_link_id, bare_key) → (value, observed_at) for the panel.
    from django.db import connection as _conn

    link_ids_tuple = tuple(link_ids)
    obs_keys_tuple = tuple(control_obs_keys)

    # patient_link_id → {bare_key: value}  and  patient_link_id → last_observed_at
    latest_obs: dict[int, dict[str, float]] = {}
    last_obs_at: dict[int, object] = {}

    with _conn.cursor() as cur:
        # DISTINCT ON in Postgres: pick the most-recent row per (patient_link_id, obs_key)
        cur.execute(
            """
            SELECT DISTINCT ON (patient_link_id, obs_key)
                   patient_link_id, obs_key, value, observed_at
            FROM   clinical.observations
            WHERE  patient_link_id = ANY(%s)
              AND  tenant_id = %s
              AND  obs_key   = ANY(%s)
              AND  value IS NOT NULL
            ORDER  BY patient_link_id, obs_key, observed_at DESC
            """,
            [list(link_ids_tuple), tenant_id, list(obs_keys_tuple)],
        )
        for row in cur.fetchall():
            plid, obs_key, value, observed_at = row
            # Strip prefix to get bare key
            if obs_key.startswith("vital:"):
                bare = obs_key[len("vital:"):]
            elif obs_key.startswith("lab:"):
                bare = obs_key[len("lab:"):]
            else:
                bare = obs_key
            if bare not in CONTROL_VITALS:
                continue
            latest_obs.setdefault(plid, {})[bare] = value

        # Also fetch the overall latest observation timestamp per patient link
        # (for lapsed detection — any observation, not just CONTROL_VITALS)
        cur.execute(
            """
            SELECT patient_link_id, MAX(observed_at)
            FROM   clinical.observations
            WHERE  patient_link_id = ANY(%s)
              AND  tenant_id = %s
            GROUP  BY patient_link_id
            """,
            [list(link_ids_tuple), tenant_id],
        )
        for row in cur.fetchall():
            plid, max_at = row
            last_obs_at[plid] = max_at

    # ── 4. Active conditions per patient ──────────────────────────────────────
    cond_rows = (
        PatientCondition.objects.filter(
            tenant_id=tenant_id,
            patient_link_id__in=link_ids,
            is_active=True,
        )
        .values("patient_link_id", "condition_id")
    )
    cond_ids_all = list({r["condition_id"] for r in cond_rows})
    cond_name_map: dict[int, str] = {}
    if cond_ids_all:
        for c in Condition.objects.filter(id__in=cond_ids_all, tenant_id=tenant_id).values("id", "name"):
            cond_name_map[c["id"]] = c["name"]

    patient_conds: dict[int, list[str]] = {}
    for r in cond_rows:
        plid = r["patient_link_id"]
        cname = cond_name_map.get(r["condition_id"], "")
        if cname:
            patient_conds.setdefault(plid, []).append(cname)

    # ── 5. Open follow-up counts per patient ──────────────────────────────────
    open_fu_counts: dict[int, int] = {}
    for row in (
        FollowupTask.objects.filter(
            tenant_id=tenant_id,
            patient_link_id__in=link_ids,
            status=FollowupTask.STATUS_OPEN,
        )
        .values("patient_link_id")
    ):
        plid = row["patient_link_id"]
        open_fu_counts[plid] = open_fu_counts.get(plid, 0) + 1

    # ── 6. Upcoming appointments (scheduled, in the future) ───────────────────
    upcoming_link_ids: set[int] = set()
    for row in (
        Appointment.objects.filter(
            tenant_id=tenant_id,
            patient_link_id__in=link_ids,
            status=Appointment.STATUS_SCHEDULED,
            scheduled_at__gt=now,
        )
        .values("patient_link_id")
        .distinct()
    ):
        upcoming_link_ids.add(row["patient_link_id"])

    # ── 7. Revenue (manager-only, one batched call) ────────────────────────────
    rev: dict[int, int] = {}  # patient_link_id → Toman
    median_rev = 0
    if show_value and patient_ids:
        # get_revenue_by_patient_ids is keyed by accounting patient_id
        rev_by_accounting_pid = get_revenue_by_patient_ids(patient_ids)
        # Map back to patient_link_id via the active_links list
        pid_to_link: dict[int, int] = {lnk["patient_id"]: lnk["id"] for lnk in active_links}
        for acc_pid, amount in rev_by_accounting_pid.items():
            link_id = pid_to_link.get(acc_pid)
            if link_id is not None and amount > 0:
                rev[link_id] = amount
        positive_vals = sorted(v for v in rev.values() if v > 0)
        median_rev = _median(positive_vals)

    # ── 8. Demographics (one batched call) ────────────────────────────────────
    demos_list = get_patients_by_ids(patient_ids)
    demos_by_pid: dict[int, object] = {d.id: d for d in demos_list}

    # ── 9. Score + build patient records ──────────────────────────────────────
    # Index active_links by id for O(1) lookup
    links_by_id: dict[int, dict] = {lnk["id"]: lnk for lnk in active_links}

    patients = []
    for lnk in active_links:
        plid = lnk["id"]
        acc_pid = lnk["patient_id"]
        demo = demos_by_pid.get(acc_pid)

        # Control-vital evaluation
        obs_map = latest_obs.get(plid, {})
        flags, warns = [], []
        for key in CONTROL_VITALS:
            val = obs_map.get(key)
            if val is None:
                continue
            level = _classify_level(key, val, indicator_map)
            ind = indicator_map.get(key)
            label = ind.label if ind else key
            if level == "danger":
                flags.append({"label": label, "value": val})
            elif level == "warn":
                warns.append({"label": label, "value": val})

        assessable = bool(obs_map)  # any CONTROL_VITALS observation present
        if flags:
            control = "uncontrolled"
        elif warns:
            control = "borderline"
        elif assessable:
            control = "controlled"
        else:
            control = "unknown"

        # Lapsed: last_obs_at missing OR older than 120 days
        last_at = last_obs_at.get(plid)
        if last_at is None:
            lapsed = True
            days_since = None
        else:
            # last_at is timezone-aware from Postgres TIMESTAMPTZ
            delta = now - last_at
            days_since = delta.days
            lapsed = days_since > LAPSED_DAYS

        open_fu = open_fu_counts.get(plid, 0)
        value = rev.get(plid, 0)

        # ── Priority score (clinical-first) ───────────────────────────────────
        score = 0
        breakdown = []

        if flags:
            pts = 3 * len(flags)
            score += pts
            breakdown.append(("کنترل‌نشده", pts))
        if warns:
            score += len(warns)
            breakdown.append(("مرزی", len(warns)))
        if assessable and lapsed:
            score += 2
            breakdown.append(("بی‌مراجعه", 2))
        elif not assessable:
            score += 1
            breakdown.append(("بدون قرائتِ پایه", 1))
        if open_fu:
            pts = min(open_fu, 3)
            score += pts
            breakdown.append((f"{open_fu} پیگیریِ باز", pts))
        if show_value and median_rev > 0 and value > median_rev:
            score += 1
            breakdown.append(("بیمارِ ارزشمند", 1))
        if plid in upcoming_link_ids:
            score = max(0, score - 2)
            breakdown.append(("نوبتِ پیش‌رو", -2))

        if score <= 0:
            continue

        patients.append({
            "id": plid,
            "patient_id": acc_pid,
            "full_name": demo.full_name if demo else None,
            "phone_number": demo.phone_number if demo else None,
            "opt_out": bool(lnk.get("sms_opt_out", False)),
            "control": control,
            "flags": flags,
            "warns": warns,
            "lapsed": lapsed,
            "days_since_last": days_since,
            "last_observed_at": last_at.isoformat() if last_at else None,
            "open_fu": open_fu,
            "value": value if show_value else None,
            "score": score,
            "breakdown": breakdown,
            "conditions": patient_conds.get(plid, []),
            "upcoming": plid in upcoming_link_ids,
        })

    # Sort by score descending
    patients.sort(key=lambda p: -p["score"])

    # ── 10. Cohort segmentation ───────────────────────────────────────────────
    def _in_cohort(p: dict, key: str) -> bool:
        if key == "uncontrolled_lapsed":
            return p["control"] == "uncontrolled" and p["lapsed"]
        if key == "valuable_drifting":
            return median_rev > 0 and (p["value"] or 0) > median_rev and p["lapsed"]
        if key == "overdue_care":
            return p["open_fu"] > 0
        if key == "uncontrolled":
            return p["control"] == "uncontrolled"
        return False

    cohorts = []
    for key, label in COHORT_DEFS:
        if key == "valuable_drifting" and not show_value:
            continue
        ids = [p["id"] for p in patients if _in_cohort(p, key)]
        cohorts.append({"key": key, "label": label, "count": len(ids), "ids": ids})

    return {
        "patients": patients,
        "cohorts": cohorts,
        "median_rev": median_rev,
        "total": len(patients),
        "show_value": show_value,
    }


def cohort_ids(cohort_key: str, tenant_id: int, show_value: bool) -> list[int]:
    """
    Recompute a cohort's patient_link_ids server-side (never trust posted ids).

    Returns an empty list if the cohort key is unknown or not visible.
    """
    data = panel(tenant_id=tenant_id, show_value=show_value)
    return next(
        (c["ids"] for c in data["cohorts"] if c["key"] == cohort_key),
        [],
    )


def conversion(tenant_id: int) -> dict:
    """
    Follow-up → visit conversion funnel for this tenant.

    Of all RESOLVED (status='done') follow-ups, the share linked to a visit
    (appointment_id IS NOT NULL) measures whether the recall funnel actually
    lands patients in a scheduled appointment.

    Returns: {resolved, to_visit, rate}
    """
    done_qs = FollowupTask.objects.filter(tenant_id=tenant_id, status=FollowupTask.STATUS_DONE)
    resolved = done_qs.count()
    to_visit = done_qs.exclude(appointment_id=None).count()
    rate = round(to_visit * 100 / resolved, 1) if resolved else 0.0
    return {"resolved": resolved, "to_visit": to_visit, "rate": rate}
