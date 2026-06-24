"""
clinical/followup_engine.py — Rule-driven follow-up generation for halqe.

Faithful port of specialist_clinic/src/services/followup_engine.py into the
halqe Django/Postgres platform.

Clinical semantics are preserved EXACTLY — recall intervals, due logic, and the
"last done" definition (ADR-0005: a reading OR a lab closes the recall) are
not changed. The adaptation touches only the data access layer (ORM instead of
raw SQL) and the engine entry point (evaluate_for_patient via suggestion_service
instead of RuleEngine().evaluate() directly — Step 6 guard).

STEP 12: closes the care loop diagnosis→funnel by turning fired monitoring /
screening / vaccine rules into clinical.followup_tasks — but ONLY when actually
DUE (interval elapsed or never done).

Public API
----------
due_clinical_events(pid, tenant_id) -> list[dict]
    Clinically-due items as plain data. NO side effects. Shared by the worklist
    generator and any future engagement dispatcher.

generate_for_patient(pid, tenant_id) -> int
    Create due follow-up tasks for one patient. Idempotent (dedup by source_rule
    + recall window). Returns the count of tasks created.

generate_all(tenant_id) -> int
    Run generate_for_patient over all active PatientLinks for a tenant. Returns
    total tasks created.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from django.utils import timezone as dj_timezone

from clinical.models import (
    PatientLink,
    VitalReading,
    LabResult,
    PatientFlag,
    FollowupTask,
)
from clinical import audit
from clinical.suggestion_service import evaluate_for_patient as _engine_evaluate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Maps action_type → reason string stored in followup_tasks.reason
# Faithful port of specialist_clinic REASON_BY_ACTION
# ---------------------------------------------------------------------------
REASON_BY_ACTION: dict[str, str] = {
    "create_followup": "monitoring",
    "schedule_screening": "screening",
    "vaccine": "vaccine",
}

# ---------------------------------------------------------------------------
# Default recall interval (months) per item; None = one-time / on-demand.
# Faithful port of specialist_clinic ITEM_DEFAULT_MONTHS
# ---------------------------------------------------------------------------
ITEM_DEFAULT_MONTHS: dict[str, Optional[int]] = {
    "a1c":            6,
    "renal":          12,
    "lipid":          12,
    "eye":            12,
    "foot":           12,
    "neuropathy":     12,
    "masld":          12,
    "renal_function": 12,
    "potassium":      None,
    "influenza":      12,
    "tdap":           120,
    "zoster":         None,
    "pneumococcal":   None,
    "rsv":            None,
    "covid19":        None,
    "tsh":            12,
}

# ---------------------------------------------------------------------------
# Canonical observation keys whose "last done" date closes each item's recall.
# Spans BOTH vital_readings.type AND lab_results.test_key (ADR-0005).
# Faithful port of specialist_clinic ITEM_VITALS
# ---------------------------------------------------------------------------
ITEM_VITALS: dict[str, list[str]] = {
    "a1c":            ["hba1c"],
    "renal":          ["egfr", "uacr"],
    "lipid":          ["ldl"],
    "renal_function": ["egfr"],
    "tsh":            ["tsh"],
}

# ---------------------------------------------------------------------------
# Flag items: item name → patient_flags.flag_key whose value stores "last done".
# Faithful port of specialist_clinic ITEM_FLAGS
# ---------------------------------------------------------------------------
ITEM_FLAGS: dict[str, str] = {
    "eye":  "eye_exam_date",
    "foot": "foot_exam_date",
}


# ---------------------------------------------------------------------------
# _last_done — ORM port of specialist_clinic _last_done
# ---------------------------------------------------------------------------

def _last_done(
    pid: int,
    item: str,
    flags: dict,
    tenant_id: int,
) -> Optional[str]:
    """
    Return the ISO date string of the most recent observation that closes
    this item's recall window, or None if never done.

    ADR-0005: for ITEM_VITALS items, the latest of vital_readings.type IN keys
    UNION lab_results.test_key IN keys closes the recall — a lab-entered HbA1c
    satisfies the HbA1c monitoring recall just as a clinic vital does.

    For ITEM_FLAGS items, the flag value (a date string) is used directly.
    """
    keys = ITEM_VITALS.get(item)
    if keys:
        # Vital readings max measured_at
        vr_qs = VitalReading.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=pid,
            type__in=keys,
        ).order_by("-measured_at").values_list("measured_at", flat=True)
        vital_max: Optional[datetime] = vr_qs.first()

        # Lab results max taken_at
        lr_qs = LabResult.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=pid,
            test_key__in=keys,
        ).order_by("-taken_at").values_list("taken_at", flat=True)
        lab_max: Optional[datetime] = lr_qs.first()

        # Take the most recent across both channels
        candidates = [d for d in (vital_max, lab_max) if d is not None]
        if not candidates:
            return None
        latest_dt = max(candidates)
        # Normalize to ISO date string (YYYY-MM-DD) for _months_since
        if hasattr(latest_dt, "date"):
            return latest_dt.date().isoformat()
        return str(latest_dt)[:10]

    fk = ITEM_FLAGS.get(item)
    if fk:
        return flags.get(fk)

    return None


# ---------------------------------------------------------------------------
# _months_since — Tehran-aware elapsed months calculation
# Faithful port of specialist_clinic _months_since (uses aware timezone now)
# ---------------------------------------------------------------------------
_TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def _months_since(date_str: str) -> Optional[int]:
    """
    Return the number of elapsed calendar months since date_str (YYYY-MM-DD).
    Uses the Tehran-aware current time (UTC+3:30) per project convention.
    Returns None on parse failure.
    """
    try:
        d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    # Use Django's timezone.now() (aware) — the project always stores Tehran time
    now = dj_timezone.now().astimezone(_TEHRAN_TZ)
    return (now.year - d.year) * 12 + (now.month - d.month)


# ---------------------------------------------------------------------------
# due_clinical_events — pure data, NO side effects
# Faithful port of specialist_clinic due_clinical_events
# ---------------------------------------------------------------------------

def due_clinical_events(pid: int, tenant_id: int) -> list[dict]:
    """
    Return clinically-due monitoring / screening / vaccine / redflag items for
    a patient as plain data with NO side effects.

    'Due' = the recall interval has elapsed or the item was never done. This
    function does NOT deduplicate against prior tasks — callers apply their own
    dedup (the worklist via generate_for_patient; future dispatchers via an
    engagement ledger).

    STEP 6 guard: calls evaluate_for_patient (from suggestion_service) instead
    of rule_engine.evaluate() directly, so demographics are always resolved and
    age-gated rules fire correctly.

    Each returned dict: {action, rule_code, title, item, months}
    """
    # STEP 6: MUST use suggestion_service.evaluate_for_patient — NOT rule_engine.evaluate
    fired: list[dict] = _engine_evaluate(pid, tenant_id)

    # Fetch flags once (used by _last_done for ITEM_FLAGS items)
    flag_rows = PatientFlag.objects.filter(
        tenant_id=tenant_id,
        patient_link_id=pid,
    ).values("flag_key", "value")
    flags: dict = {r["flag_key"]: r["value"] for r in flag_rows}

    out: list[dict] = []
    for r in fired:
        act = r.get("action_type")

        # Redflags surface in the patient panel — emit them for callers but
        # generate_for_patient will skip them (they don't become worklist items).
        if act == "redflag":
            out.append({
                "action": "redflag",
                "rule_code": r["rule_code"],
                "title": r["title"],
                "item": r["rule_code"],
                "months": None,
            })
            continue

        if act not in REASON_BY_ACTION:
            continue

        params: dict = r.get("params") or {}
        # item: explicit param, or vaccine param, or fall back to rule_code
        item: str = params.get("item") or params.get("vaccine") or r["rule_code"]
        months: Optional[int] = params.get("interval_months")
        if months is None:
            months = ITEM_DEFAULT_MONTHS.get(item)

        # 0-interval = "every visit" — handled by the panel, not the worklist
        if months == 0:
            continue

        last = _last_done(pid, item, flags, tenant_id)
        if last and months and (_months_since(last) or 0) < months:
            continue  # done recently — not due

        out.append({
            "action": act,
            "rule_code": r["rule_code"],
            "title": r["title"],
            "item": item,
            "months": months,
        })

    return out


# ---------------------------------------------------------------------------
# _recently_handled — dedup guard for generate_for_patient
# ---------------------------------------------------------------------------

def _recently_handled(
    pid: int,
    rule_code: str,
    months: Optional[int],
    tenant_id: int,
) -> bool:
    """
    Return True if there is already an open or recent task for this
    (patient, source_rule) pair within the recall window.

    Logic mirrors specialist_clinic FollowupRepository.recently_handled_source:
      - Any open task with this source_rule → block (still pending resolution)
      - Any task (any status) created within the recall window → block (cooldown)
    If months is None (one-time / on-demand), only open tasks block re-creation.
    """
    # Open task for same rule → still pending, don't duplicate
    open_exists = FollowupTask.objects.filter(
        tenant_id=tenant_id,
        patient_link_id=pid,
        source_rule=rule_code,
        status="open",
    ).exists()
    if open_exists:
        return True

    # Within recall window → cooldown (regardless of status)
    if months:
        window_start = dj_timezone.now() - timedelta(days=months * 30)
        within_window = FollowupTask.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=pid,
            source_rule=rule_code,
            created_at__gte=window_start,
        ).exists()
        if within_window:
            return True

    return False


# ---------------------------------------------------------------------------
# generate_for_patient — idempotent worklist population for one patient
# ---------------------------------------------------------------------------

def generate_for_patient(pid: int, tenant_id: int) -> int:
    """
    Create due monitoring / screening / vaccine follow-up tasks for one patient.

    Idempotent: running twice on the same patient without new clinical data or
    resolved tasks creates zero duplicate tasks.

    Returns the count of tasks actually created.
    """
    created = 0
    today = dj_timezone.now().date()

    for ev in due_clinical_events(pid, tenant_id):
        if ev["action"] == "redflag":
            # Red-flags surface in the patient panel, not the worklist
            continue

        if _recently_handled(pid, ev["rule_code"], ev["months"], tenant_id):
            continue

        reason = REASON_BY_ACTION[ev["action"]]
        FollowupTask.objects.create(
            tenant_id=tenant_id,
            patient_link_id=pid,
            due_date=today,
            reason=reason,
            detail=ev["title"],
            status="open",
            source_rule=ev["rule_code"],
            created_at=dj_timezone.now(),
        )

        # Audit — one row per created task (best-effort, light)
        audit.log_activity(
            tenant_id=tenant_id,
            user_id=None,
            username="system",
            action_type="followup_generated",
            action_category="followup",
            description=f"auto-generated followup for rule {ev['rule_code']}",
            target_table="followup_tasks",
            patient_link_id=pid,
        )

        created += 1
        logger.debug(
            "generate_for_patient: created followup task for patient_link_id=%s "
            "rule=%s reason=%s tenant=%s",
            pid, ev["rule_code"], reason, tenant_id,
        )

    return created


# ---------------------------------------------------------------------------
# generate_all — batch worklist population across all active patients
# ---------------------------------------------------------------------------

def generate_all(tenant_id: int) -> int:
    """
    Run generate_for_patient over all active PatientLinks for the given tenant.

    This is the entry point for the scheduler (Steps 16-18) and the
    generate_followups management command. Returns total tasks created.
    """
    links = PatientLink.objects.filter(
        tenant_id=tenant_id,
        is_active=True,
    ).values_list("id", flat=True)

    total = 0
    for pid in links:
        try:
            count = generate_for_patient(pid, tenant_id)
            total += count
        except Exception as exc:
            logger.error(
                "generate_all: error for patient_link_id=%s tenant=%s: %s",
                pid, tenant_id, exc,
            )
            # Continue with remaining patients — don't abort the whole batch

    logger.info(
        "generate_all: tenant=%s created=%s tasks from %s active patients",
        tenant_id, total, len(links),
    )
    return total
