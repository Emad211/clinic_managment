"""
clinical/engagement_service.py — Step 18: SMS provider + Engagement Dispatcher.

Faithful port of specialist_clinic/src/services/engagement_service.py into the
halqe Django/Postgres platform.

Overview
--------
The dispatcher collects DUE clinical events for each active patient (from
followup_engine.due_clinical_events + the engagement_events routing config),
then routes each event to the correct channel:

  worklist / both  → create a followup_task (deduplicated) + record a dispatch.
  sms / both       → enqueue an approval row (physician must approve before send).
  off              → skip.

SMS is NEVER sent here.  The send path is:
  dispatch → enqueue_approval (pending) → manager approves → send_approved_sms().

All guardrails from the source are preserved:
  - Phone comes from the accounting Port (PatientLink has NO phone — ADR-0007).
  - Opt-out from patient_links.sms_opt_out.
  - Idempotency: UNIQUE(tenant, patient, event_key, period_key, channel) on
    engagement_dispatch.  A second attempt for the same bucket is silently skipped.
  - Cooldown: no repeat SMS within cooldown_days.
  - period_key is always non-null (ROADMAP risk #9).
  - run_all is single-threaded (no concurrent dispatch for the same tenant).

Quiet hours (default 08:00–21:00 Tehran) are enforced at SEND TIME, not dispatch
time — see send_approved_sms() below.

KAVENEGAR KYC GATE
------------------
The live Kavenegar API key is valid but returns code 430 (KYC not completed)
until the clinic owner finishes identity verification.  NullProvider is used
in ALL tests and in development — it logs to stdout and returns SIMULATED.
No real SMS is ever sent until KYC is complete.

Public API
----------
dispatch_patient(tenant_id, patient_link_id, *, dry_run, worklist_only) -> dict
    Dispatch one patient.  Returns counts: {sms, worklist, skipped, queued}.

run_all(tenant_id, *, dry_run, worklist_only) -> dict
    Run dispatch_patient for all active PatientLinks in a tenant.
    Single-threaded — call from the scheduler; do not parallelize.

send_approved_sms(approval_id, tenant_id, *, decided_by, override_quiet) -> dict
    Send the SMS for an approved approval row.
    Called from the approve endpoint AFTER the manager approves.
    Re-checks opt-out + phone (auto-rejects if opted out).
    Enforces quiet hours (08:00–21:00 Tehran) — blocks outside window unless
    override_quiet=True.
    Uses get_provider() (NullProvider when no key; KavenegarProvider when key).
    Records dispatch + marks sent_at + status='sent'.
    Returns {'ok': bool, 'reason': str|None, 'provider_msgid': str|None}.
"""
from __future__ import annotations

import logging
from datetime import timedelta, timezone as _tz
from typing import Optional

from django.db import IntegrityError
from django.utils import timezone as dj_timezone

from clinical.models import (
    PatientLink,
    EngagementEvent,
    EngagementDispatch,
    EngagementApproval,
    FollowupTask,
)
from clinical.followup_engine import due_clinical_events
from clinical.engagement_approval_service import enqueue_approval
from clinical.sms.provider import get_provider, NullProvider, SendResult
from clinical.sms.compliance import sanitize, find_phi
from clinical.audit import log_activity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tehran timezone (UTC+3:30) — for quiet-hours check
# ---------------------------------------------------------------------------
_TEHRAN = _tz(timedelta(hours=3, minutes=30))

# Guardrail defaults — could be made per-tenant settings later
QUIET_START_DEFAULT = "08:00"
QUIET_END_DEFAULT = "21:00"

# event_key → followup_tasks.reason mapping (faithful port of specialist_clinic)
REASON_BY_EVENT: dict[str, str] = {
    "monitoring_due": "monitoring",
    "screening_due": "screening",
    "vaccine_due": "vaccine",
    "lapsed": "lapsed",
    "uncontrolled": "uncontrolled",
    "red_flag": "uncontrolled",
    "appointment_reminder": "visit_due",
    "refill_due": "refill",
}


# ---------------------------------------------------------------------------
# Quiet-hours guard
# ---------------------------------------------------------------------------

def _quiet_now(
    quiet_start: str = QUIET_START_DEFAULT,
    quiet_end: str = QUIET_END_DEFAULT,
) -> bool:
    """Return True if the current Tehran time is OUTSIDE the allowed send window."""
    now_tehran = dj_timezone.now().astimezone(_TEHRAN).strftime("%H:%M")
    return not (quiet_start <= now_tehran <= quiet_end)


# ---------------------------------------------------------------------------
# Phone lookup via AccountingPort (PatientLink has no phone — ADR-0007)
# ---------------------------------------------------------------------------

def _get_patient_phone(patient_link_id: int, tenant_id: int) -> Optional[str]:
    """
    Look up the phone number for a PatientLink via the AccountingPort.

    PatientLink stores NO demographics (ADR-0007).  Phone is in accounting.patients,
    reachable only via the read-only Port.  Returns None if not found.
    """
    try:
        link = PatientLink.objects.get(id=patient_link_id, tenant_id=tenant_id)
        from accounting_port.port import get_patients_by_ids
        dtos = get_patients_by_ids([link.patient_id])
        if dtos:
            return dtos[0].phone_number
    except PatientLink.DoesNotExist:
        pass
    except Exception as exc:
        logger.warning(
            "_get_patient_phone: failed for patient_link_id=%s tenant=%s: %s",
            patient_link_id, tenant_id, exc,
        )
    return None


# ---------------------------------------------------------------------------
# Internal helpers — dispatch / cooldown / worklist dedup
# ---------------------------------------------------------------------------

def _already_dispatched(
    tenant_id: int,
    patient_link_id: int,
    event_key: str,
    period_key: str,
    channel: str,
) -> bool:
    """Return True if this (tenant, patient, event, period, channel) bucket is done."""
    return EngagementDispatch.objects.filter(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        event_key=event_key,
        period_key=period_key,
        channel=channel,
    ).exists()


def _in_cooldown(
    tenant_id: int,
    patient_link_id: int,
    event_key: str,
    cooldown_days: int,
) -> bool:
    """Return True if there was a dispatch for this event within cooldown_days."""
    if cooldown_days <= 0:
        return False
    since = dj_timezone.now() - timedelta(days=cooldown_days)
    return EngagementDispatch.objects.filter(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        event_key=event_key,
        channel="sms",
        created_at__gte=since,
    ).exists()


def _today_tehran_bounds() -> tuple:
    """
    Return (start, end) aware datetimes spanning the current Tehran calendar day.

    Used by the daily-cap gate: an SMS dispatch is "today's" if its created_at
    falls within these bounds.  Bounds are computed in Tehran local time then
    kept as aware datetimes so the DB comparison is timezone-correct regardless
    of the stored TIMESTAMPTZ offset.
    """
    now_tehran = dj_timezone.now().astimezone(_TEHRAN)
    start_tehran = now_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
    end_tehran = start_tehran + timedelta(days=1)
    return start_tehran, end_tehran


def _sms_dispatched_today(tenant_id: int) -> int:
    """
    Count SMS-channel dispatch rows for this tenant within the current Tehran day.

    This is the daily-cap LEDGER denominator (step 52): the ledger records one
    'sms' dispatch row per actually-sent message (send_approved_sms →
    _record_dispatch), so this counts real sends for the calendar day, tenant-wide.
    """
    start, end = _today_tehran_bounds()
    return EngagementDispatch.objects.filter(
        tenant_id=tenant_id,
        channel="sms",
        created_at__gte=start,
        created_at__lt=end,
    ).count()


def _sms_enqueued_today_unsent(tenant_id: int) -> int:
    """
    Count SMS approvals ENQUEUED today that have not yet been sent.

    These are pending/approved sms-channel approval rows created within the
    current Tehran day.  They will (likely) become real sends, so they count
    against the daily cap NOW — otherwise a single run_all could enqueue far
    more than the cap before any of them lands in the dispatch ledger.
    Rejected/sent rows are excluded (sent ones are already counted via the ledger).
    """
    start, end = _today_tehran_bounds()
    return EngagementApproval.objects.filter(
        tenant_id=tenant_id,
        channel="sms",
        status__in=(
            EngagementApproval.STATUS_PENDING,
            EngagementApproval.STATUS_APPROVED,
        ),
        created_at__gte=start,
        created_at__lt=end,
    ).count()


def _sms_used_today_count(tenant_id: int) -> int:
    """
    Daily-cap "used" count = real sends today (ledger) + enqueued-today-unsent.

    Combined denominator for the step-52 daily-cap gate.  See the two helpers
    above for the rationale of each half.
    """
    return _sms_dispatched_today(tenant_id) + _sms_enqueued_today_unsent(tenant_id)


def _record_dispatch(
    tenant_id: int,
    patient_link_id: int,
    event_key: str,
    period_key: str,
    channel: str,
    ref_id: Optional[int] = None,
    status: str = "done",
) -> Optional[EngagementDispatch]:
    """
    Insert a dispatch row.  Returns the row, or None on duplicate (already done).

    Uses INSERT with IntegrityError catch rather than get_or_create to avoid a
    race condition: if two workers call this simultaneously, the second gets the
    IntegrityError and treats it as 'already done' — correct behavior.

    status: 'done' (default — normal dispatch) or 'holdout' (patient is in the
    causal-effect control group — the event is recorded for denominator tracking
    but no sms/worklist action is taken; see dispatch_patient holdout gate).
    """
    try:
        return EngagementDispatch.objects.create(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            event_key=event_key,
            period_key=period_key,
            channel=channel,
            ref_id=ref_id,
            status=status,
        )
    except IntegrityError:
        # UNIQUE violation — already dispatched; treat as idempotent success
        logger.debug(
            "_record_dispatch: duplicate bucket (tenant=%s, patient=%s, "
            "event_key=%r, period_key=%r, channel=%r, status=%r) — already done",
            tenant_id, patient_link_id, event_key, period_key, channel, status,
        )
        return None


def _open_followup_exists(
    tenant_id: int,
    patient_link_id: int,
    reason: str,
) -> bool:
    """Return True if an open followup_task for this (patient, reason) already exists."""
    return FollowupTask.objects.filter(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        reason=reason,
        status="open",
    ).exists()


# ---------------------------------------------------------------------------
# Collect due events for one patient
# ---------------------------------------------------------------------------

def _collect_due_events(
    tenant_id: int,
    patient_link_id: int,
) -> tuple[list[dict], dict[str, EngagementEvent]]:
    """
    Return (events, cfg) for a patient.

    events: list of due-event dicts, each with {event_key, period_key, detail}.
    cfg:    map event_key → EngagementEvent ORM row (only active events).

    Faithful port of specialist_clinic EngagementService.collect_due_events():
      1. Clinical (rule-driven) — grouped by event category (one msg per category,
         period_key is monthly for recurrence).
      2. Worklist-source events (monitoring_due, screening_due, vaccine_due, lapsed,
         uncontrolled, red_flag) sourced from followup_engine.due_clinical_events
         mapped via source_action.
      3. Appointment reminders.
      4. Refill due.
      5. Lapsed (no vital in 120 days).
      6. Uncontrolled (latest hba1c / bp above danger threshold).

    Steps 3-6 query the clinical DB directly (ORM).
    """
    from django.utils import timezone as dj_tz

    # Active engagement events config for this tenant
    active_events = list(
        EngagementEvent.objects.filter(tenant_id=tenant_id, is_active=True)
    )
    cfg: dict[str, EngagementEvent] = {e.event_key: e for e in active_events}
    action_to_event: dict[str, str] = {
        e.source_action: e.event_key
        for e in active_events
        if e.source_action
    }
    events: list[dict] = []
    month = dj_tz.now().strftime("%Y-%m")

    # 1) Clinical, rule-driven — group by event category
    clinical: dict[str, list[str]] = {}
    for ev in due_clinical_events(patient_link_id, tenant_id):
        ek = action_to_event.get(ev["action"])
        if ek and ek in cfg:
            clinical.setdefault(ek, []).append(ev["title"])
    for ek, titles in clinical.items():
        detail = "، ".join(titles[:6]) + ("…" if len(titles) > 6 else "")
        events.append({
            "event_key": ek,
            "period_key": f"{ek}:{month}",
            "detail": detail,
        })

    # 2) Appointment reminders
    if "appointment_reminder" in cfg:
        from clinical.models import Appointment
        lead = int(cfg["appointment_reminder"].lead_days or 0)
        now_tehran = dj_tz.now().astimezone(_TEHRAN).date()
        cutoff = now_tehran + timedelta(days=lead)
        appts = Appointment.objects.filter(
            patient_link_id=patient_link_id,
            tenant_id=tenant_id,
            status="scheduled",
            scheduled_at__date__range=(now_tehran, cutoff),
        )
        for appt in appts:
            events.append({
                "event_key": "appointment_reminder",
                "period_key": f"appt:{appt.id}",
                "detail": "یادآوری نوبت",
            })

    # 3) Refill due
    if "refill_due" in cfg:
        from clinical.models import PatientMedication
        lead = int(cfg["refill_due"].lead_days or 0)
        now_tehran = dj_tz.now().astimezone(_TEHRAN).date()
        cutoff = now_tehran + timedelta(days=lead)
        meds = PatientMedication.objects.filter(
            patient_link_id=patient_link_id,
            tenant_id=tenant_id,
            is_active=True,
            refill_due_date__lte=cutoff,
        ).exclude(refill_due_date__isnull=True)
        for med in meds:
            events.append({
                "event_key": "refill_due",
                "period_key": f"refill:{med.id}:{med.refill_due_date}",
                "detail": f"داروی {med.drug_name}",
            })

    # 4) Lapsed (no vital reading in 120 days) — once per month
    # slice13 safety gate: only verified readings count as "recent contact".
    # An unverified self-report cannot mask a truly lapsed patient.
    if "lapsed" in cfg:
        from clinical.models import VitalReading
        cutoff_dt = dj_tz.now() - timedelta(days=120)
        has_recent = VitalReading.objects.filter(
            patient_link_id=patient_link_id,
            tenant_id=tenant_id,
            measured_at__gte=cutoff_dt,
            verified=True,
        ).exists()
        if not has_recent:
            events.append({
                "event_key": "lapsed",
                "period_key": f"lapsed:{month}",
                "detail": "بیش از ۴ ماه بدون ثبت شاخص",
            })

    # 5) Uncontrolled (latest hba1c / bp_systolic at danger threshold)
    if "uncontrolled" in cfg:
        from clinical.models import ClinicalIndicator, VitalReading
        hba1c_d = 8.0
        sys_d = 140.0
        try:
            ind = ClinicalIndicator.objects.filter(
                tenant_id=tenant_id, key="hba1c", is_active=True
            ).first()
            if ind and ind.danger:
                hba1c_d = float(ind.danger)
            ind2 = ClinicalIndicator.objects.filter(
                tenant_id=tenant_id, key="bp_systolic", is_active=True
            ).first()
            if ind2 and ind2.danger:
                sys_d = float(ind2.danger)
        except Exception:
            pass

        # slice13 safety gate: only verified readings determine "uncontrolled" status.
        # An unverified self-report (verified=FALSE) must NOT trigger clinical alerts.
        latest_hba1c = (
            VitalReading.objects.filter(
                patient_link_id=patient_link_id,
                tenant_id=tenant_id,
                type="hba1c",
                verified=True,
            )
            .order_by("-measured_at")
            .values_list("value", flat=True)
            .first()
        )
        latest_sys = (
            VitalReading.objects.filter(
                patient_link_id=patient_link_id,
                tenant_id=tenant_id,
                type="bp_systolic",
                verified=True,
            )
            .order_by("-measured_at")
            .values_list("value", flat=True)
            .first()
        )
        if (latest_hba1c is not None and latest_hba1c >= hba1c_d) or (
            latest_sys is not None and latest_sys >= sys_d
        ):
            events.append({
                "event_key": "uncontrolled",
                "period_key": f"unctrl:{month}",
                "detail": "آخرین شاخص‌ها خارج از محدودهٔ کنترل",
            })

    return events, cfg


# ---------------------------------------------------------------------------
# Personalize SMS template (faithful port of campaign_service.personalize)
# ---------------------------------------------------------------------------

def _personalize(template: str, name: str) -> str:
    """Replace {name} placeholder in an SMS template."""
    return (template or "").replace("{name}", name or "")


# ---------------------------------------------------------------------------
# dispatch_patient — core dispatch logic for one patient
# ---------------------------------------------------------------------------

def dispatch_patient(
    tenant_id: int,
    patient_link_id: int,
    *,
    dry_run: bool = False,
    worklist_only: bool = False,
) -> dict:
    """
    Dispatch engagement events for one patient.

    Returns a summary dict: {sms, worklist, skipped, queued, errors}.

    worklist channel:
      - If no open followup_task exists for this reason + no dispatch recorded
        for this period → create a followup_task + record dispatch.

    sms channel (enqueue, NOT send):
      - phone comes from AccountingPort (PatientLink has no phone — ADR-0007).
      - opt-out from patient_links.sms_opt_out.
      - idempotency: skip if already dispatched for this period.
      - cooldown: skip if dispatched within cooldown_days.
      - ELSE: enqueue_approval (physician gate). SMS sent ONLY after approve.

    dry_run=True: compute and return counts without any DB writes.
    worklist_only=True: skip sms channel entirely (run worklist path only).
    """
    # observability counters (step 51): skipped is the legacy aggregate (kept for
    # backward compat); opt_out_skipped + cooldown_skipped break it down so the
    # run summary can tell *why* sends were suppressed without losing the total.
    res: dict = {
        "sms": 0, "worklist": 0, "skipped": 0, "queued": 0, "errors": 0,
        "holdout": 0, "opt_out_skipped": 0, "cooldown_skipped": 0,
        # step 52 — SMS suppressed because the tenant hit its daily cap.
        "daily_cap_skipped": 0,
    }

    try:
        link = PatientLink.objects.get(id=patient_link_id, tenant_id=tenant_id)
    except PatientLink.DoesNotExist:
        return res

    # ── Daily-cap gate (step 52) ─────────────────────────────────────────────
    # Read the per-tenant cap from settings (default 50; 0 = unlimited → inert).
    # The "used" count combines real sends for today (engagement_dispatch ledger,
    # channel='sms') PLUS approvals enqueued today that have not yet been sent
    # (pending/approved) — so the cap holds within a single run_all pass too, not
    # only after sends land in the ledger.  A live local counter is incremented as
    # this dispatch_patient call enqueues more, keeping the gate exact per call.
    # Local import avoids a circular import at module load time.
    from clinical.engagement_settings import get_engagement_settings
    _daily_cap = int(get_engagement_settings(tenant_id).get("daily_cap", 0) or 0)
    _sms_used_today = _sms_used_today_count(tenant_id) if _daily_cap > 0 else 0
    # ── End daily-cap gate setup ─────────────────────────────────────────────

    # ── Engagement holdout gate (slice11) ───────────────────────────────────
    # Determine whether this patient is in the causal-effect control group.
    # in_holdout=True → skip ALL automated dispatch (sms + worklist nudge from
    # the engagement engine) and record an auditable 'holdout' row per due event
    # so that the denominator is tracked for lift measurement.
    #
    # CRITICAL — mraaqbat hargez darigh nashavad:
    #   followup_engine.generate_for_patient and rule_engine.evaluate are called
    #   independently by the scheduler and are NOT gated here.  Clinical care
    #   (followup tasks from the clinical engine, red-flags, visits, prescriptions)
    #   continues exactly as for treated patients.
    #
    # ⚠️ ROADMAP: consent/patient-notification policy must be agreed with
    # legal/responsible physician before live use in production.
    _today = dj_timezone.now().date()
    _until = link.engagement_holdout_until
    in_holdout = bool(link.engagement_holdout) and (
        _until is None or _until >= _today
    )
    # ── End holdout gate ─────────────────────────────────────────────────────

    opted_out = bool(link.sms_opt_out)
    # Phone is in accounting — read via Port
    phone = _get_patient_phone(patient_link_id, tenant_id) if not opted_out else None

    # Lookup full_name for SMS personalization (via Port)
    full_name = ""
    try:
        from accounting_port.port import get_patients_by_ids
        dtos = get_patients_by_ids([link.patient_id])
        if dtos:
            full_name = dtos[0].full_name or ""
            if not phone and not opted_out:
                phone = dtos[0].phone_number
    except Exception as exc:
        logger.warning(
            "dispatch_patient: failed to fetch demographics patient_link_id=%s: %s",
            patient_link_id, exc,
        )

    try:
        events, cfg = _collect_due_events(tenant_id, patient_link_id)
    except Exception as exc:
        logger.error(
            "dispatch_patient: _collect_due_events failed for patient_link_id=%s "
            "tenant=%s: %s",
            patient_link_id, tenant_id, exc,
        )
        res["errors"] += 1
        return res

    for ev in events:
        event_key = ev["event_key"]
        period_key = ev["period_key"]
        conf = cfg.get(event_key)
        if not conf:
            continue
        channel = conf.channel
        if channel == "off":
            continue

        # ── Holdout branch — auditable skip for causal denominator ──────────
        # If the patient is in the control group (in_holdout=True), record a
        # 'holdout' row in the dispatch ledger (auditable denominator for lift
        # measurement) and skip both sms and worklist channels.
        # Clinical care paths (followup_engine, rule_engine) are NOT affected.
        if in_holdout:
            if not dry_run:
                _record_dispatch(
                    tenant_id, patient_link_id, event_key, period_key,
                    channel if channel in ("sms", "worklist") else "worklist",
                    status="holdout",
                )
            res["holdout"] += 1
            logger.debug(
                "dispatch_patient: holdout suppressed event_key=%r "
                "patient_link_id=%s tenant=%s",
                event_key, patient_link_id, tenant_id,
            )
            continue
        # ── End holdout branch ───────────────────────────────────────────────

        # ── worklist channel ────────────────────────────────────────────────
        if channel in ("worklist", "both"):
            already = _already_dispatched(
                tenant_id, patient_link_id, event_key, period_key, "worklist"
            )
            if not already:
                if not dry_run:
                    reason = REASON_BY_EVENT.get(event_key, "manual")
                    task_id: Optional[int] = None
                    if not _open_followup_exists(tenant_id, patient_link_id, reason):
                        try:
                            task = FollowupTask.objects.create(
                                tenant_id=tenant_id,
                                patient_link_id=patient_link_id,
                                due_date=dj_timezone.now().date(),
                                reason=reason,
                                detail=ev.get("detail", ""),
                                status="open",
                                source_event=event_key,
                                created_at=dj_timezone.now(),
                            )
                            task_id = task.id
                        except Exception as exc:
                            logger.warning(
                                "dispatch_patient: failed to create followup_task "
                                "patient_link_id=%s event_key=%r: %s",
                                patient_link_id, event_key, exc,
                            )
                    _record_dispatch(
                        tenant_id, patient_link_id, event_key, period_key, "worklist",
                        ref_id=task_id,
                    )
                res["worklist"] += 1

        # ── sms channel (enqueue approval — do NOT send) ────────────────────
        if not worklist_only and channel in ("sms", "both"):
            if opted_out or not phone:
                res["skipped"] += 1
                # opt-out is the actionable subset of skips (no-phone is data gap).
                if opted_out:
                    res["opt_out_skipped"] += 1
            elif _already_dispatched(
                tenant_id, patient_link_id, event_key, period_key, "sms"
            ):
                pass  # already queued/sent for this period
            elif _in_cooldown(
                tenant_id, patient_link_id, event_key, conf.cooldown_days or 0
            ):
                res["skipped"] += 1
                res["cooldown_skipped"] += 1
            elif _daily_cap > 0 and _sms_used_today >= _daily_cap:
                # Daily-cap gate (step 52): the tenant already hit its SMS budget
                # for today (Tehran). Suppress the enqueue (like opt_out/cooldown)
                # and record an auditable skip. cap=0 → unlimited → gate inert.
                res["skipped"] += 1
                res["daily_cap_skipped"] += 1
                logger.debug(
                    "dispatch_patient: daily_cap reached (cap=%s used=%s) — "
                    "sms suppressed event_key=%r patient_link_id=%s tenant=%s",
                    _daily_cap, _sms_used_today, event_key, patient_link_id, tenant_id,
                )
            else:
                template = conf.sms_template or ""
                body = sanitize(_personalize(template, full_name))
                if body.strip():
                    if not dry_run:
                        try:
                            enqueue_approval(
                                tenant_id,
                                patient_link_id,
                                event_key=event_key,
                                period_key=period_key,
                                channel="sms",
                                message=body,
                            )
                        except Exception as exc:
                            logger.warning(
                                "dispatch_patient: enqueue_approval failed "
                                "patient_link_id=%s event_key=%r: %s",
                                patient_link_id, event_key, exc,
                            )
                            res["errors"] += 1
                            continue
                    # Count this enqueue against the cap immediately so subsequent
                    # events in this call (and later patients in the run, which
                    # re-read the count) respect the budget. Increment even on
                    # dry_run so dry-run counts reflect the true gate behaviour.
                    _sms_used_today += 1
                    res["queued"] += 1

    return res


# ---------------------------------------------------------------------------
# run_all — batch dispatcher for a full tenant
# ---------------------------------------------------------------------------

def run_all(
    tenant_id: int,
    *,
    dry_run: bool = False,
    worklist_only: bool = False,
) -> dict:
    """
    Run dispatch_patient for all active PatientLinks in a tenant.

    Single-threaded — the scheduler must not call this concurrently for the
    same tenant (ROADMAP risk #9).

    Returns aggregate counts: {patients, sms, worklist, skipped, queued, errors}.
    """
    links = list(
        PatientLink.objects.filter(
            tenant_id=tenant_id,
            is_active=True,
        ).values_list("id", flat=True)
    )

    agg: dict = {
        "patients": 0,
        "sms": 0,
        "worklist": 0,
        "skipped": 0,
        "queued": 0,
        "errors": 0,
        "holdout": 0,  # slice11: events suppressed for holdout patients (auditable denominator)
        # observability breakdown (step 51) — subsets of `skipped`:
        "opt_out_skipped": 0,
        "cooldown_skipped": 0,
        # step 52 — subset of `skipped`: SMS suppressed by the daily cap.
        "daily_cap_skipped": 0,
    }

    _agg_keys = (
        "sms", "worklist", "skipped", "queued", "errors", "holdout",
        "opt_out_skipped", "cooldown_skipped", "daily_cap_skipped",
    )
    for pid in links:
        try:
            res = dispatch_patient(
                tenant_id, pid,
                dry_run=dry_run,
                worklist_only=worklist_only,
            )
            for k in _agg_keys:
                agg[k] += res.get(k, 0)
            agg["patients"] += 1
        except Exception as exc:
            logger.error(
                "run_all: unhandled error for patient_link_id=%s tenant=%s: %s",
                pid, tenant_id, exc,
            )
            agg["errors"] += 1

    # Structured, single-line, machine-parseable summary (aligned with the step-28
    # key=value production formatter).  PII-free: only counts and tenant_id.
    logger.info(
        "engagement_run_summary tenant_id=%s patients=%s queued=%s worklist=%s "
        "skipped=%s opt_out_skipped=%s cooldown_skipped=%s daily_cap_skipped=%s "
        "holdout=%s errors=%s dry_run=%s worklist_only=%s",
        tenant_id,
        agg["patients"],
        agg["queued"],
        agg["worklist"],
        agg["skipped"],
        agg["opt_out_skipped"],
        agg["cooldown_skipped"],
        agg["daily_cap_skipped"],
        agg["holdout"],
        agg["errors"],
        dry_run,
        worklist_only,
    )
    return agg


# ---------------------------------------------------------------------------
# send_approved_sms — the ONLY place a real SMS is sent
# ---------------------------------------------------------------------------

def send_approved_sms(
    approval_id: int,
    tenant_id: int,
    *,
    decided_by: str,
    override_quiet: bool = False,
    provider=None,  # injectable for tests — pass NullProvider() to force simulation
) -> dict:
    """
    Send the SMS for an approved EngagementApproval row.

    Called by the approve endpoint AFTER the manager clicks approve.
    This is the ONLY path where a real SMS can be sent.

    Guardrails (all re-checked at send time):
      1. Approval must exist for this tenant and be in status='approved'.
      2. Patient must not be opted out (auto-marks status='rejected' if opted out).
      3. Patient must have a phone number (auto-marks status='rejected' if missing).
      4. Quiet hours: if current Tehran time is outside allowed window
         (default 08:00–21:00) AND override_quiet=False → return {'ok': False,
         'reason': 'quiet'} and leave the approval in 'approved' status (it can
         be re-sent later or force-sent with override_quiet=True).
      5. provider.send() — uses get_provider() by default; NullProvider in tests.
      6. Records dispatch (idempotency ledger).
      7. Marks approval: sent_at=now(), status='sent'.

    Returns {'ok': bool, 'reason': str|None, 'provider_msgid': str|None,
             'pending': bool}.

    pending=True means the provider timed out — the message was most likely sent
    but we didn't receive confirmation.  The approval is still marked 'sent'
    (optimistic) to prevent duplicate sends.

    TESTS: inject provider=NullProvider() to force simulation — no real network call.
    """
    # Fetch approval — tenant-scoped
    try:
        approval = EngagementApproval.objects.get(
            id=approval_id,
            tenant_id=tenant_id,
        )
    except EngagementApproval.DoesNotExist:
        return {"ok": False, "reason": "not_found", "provider_msgid": None, "pending": False}

    if approval.status != EngagementApproval.STATUS_APPROVED:
        return {
            "ok": False,
            "reason": f"wrong_status:{approval.status}",
            "provider_msgid": None,
            "pending": False,
        }

    # Re-check opt-out and phone at send time
    try:
        link = PatientLink.objects.get(
            id=approval.patient_link_id,
            tenant_id=tenant_id,
        )
    except PatientLink.DoesNotExist:
        approval.status = EngagementApproval.STATUS_REJECTED
        approval.decided_by = decided_by
        approval.decided_at = dj_timezone.now()
        approval.save(update_fields=["status", "decided_by", "decided_at"])
        return {"ok": False, "reason": "patient_not_found", "provider_msgid": None, "pending": False}

    if link.sms_opt_out:
        approval.status = EngagementApproval.STATUS_REJECTED
        approval.decided_by = decided_by
        approval.decided_at = dj_timezone.now()
        approval.save(update_fields=["status", "decided_by", "decided_at"])
        return {"ok": False, "reason": "opt_out", "provider_msgid": None, "pending": False}

    # R1 consent gate (step 75 / S3): no real SMS without explicit, recorded
    # sms_consent — default-deny (the column defaults FALSE in slice0). This gates
    # ONLY the real-send boundary; the worklist/in-app path is never consent-gated
    # ("care/red-flags are never withheld"). dispatch_patient (the enqueue path) is
    # deliberately NOT gated — an unconsented patient still surfaces to the physician
    # queue (a useful "needs consent" signal); the send simply stops here. This is
    # the lawful, sufficient enforcement point (the only place provider.send() runs).
    # NOTE: sms_consent (communication consent) is DISTINCT from data_consent
    # (data-processing consent, slice17) — this gate uses sms_consent only.
    if not link.sms_consent:
        approval.status = EngagementApproval.STATUS_REJECTED
        approval.decided_by = decided_by
        approval.decided_at = dj_timezone.now()
        approval.save(update_fields=["status", "decided_by", "decided_at"])
        return {"ok": False, "reason": "no_consent", "provider_msgid": None, "pending": False}

    # Phone via AccountingPort
    phone: Optional[str] = _get_patient_phone(approval.patient_link_id, tenant_id)
    if not phone:
        approval.status = EngagementApproval.STATUS_REJECTED
        approval.decided_by = decided_by
        approval.decided_at = dj_timezone.now()
        approval.save(update_fields=["status", "decided_by", "decided_at"])
        return {"ok": False, "reason": "no_phone", "provider_msgid": None, "pending": False}

    # Quiet-hours guard — read the window from per-tenant settings (step 52).
    # Falls back to QUIET_START_DEFAULT/QUIET_END_DEFAULT when no key is set,
    # so behaviour is identical to before until a manager edits the window.
    # Local import avoids a circular import (engagement_settings imports the
    # QUIET_*_DEFAULT constants from this module at load time).
    from clinical.engagement_settings import get_quiet_window
    q_start, q_end = get_quiet_window(tenant_id)
    if _quiet_now(q_start, q_end) and not override_quiet:
        # Leave approval as 'approved' — it stays in the queue for later
        return {"ok": False, "reason": "quiet", "provider_msgid": None, "pending": False}

    # Get provider (injectable for tests)
    if provider is None:
        provider = get_provider()

    body = sanitize(approval.message or "")
    if not body.strip():
        return {"ok": False, "reason": "empty_body", "provider_msgid": None, "pending": False}

    # R3 clinical-content gate (step 76): a patient SMS must never carry this
    # patient's clinical SPECIFICS (lab/vital values, drug doses, BP readings).
    # Detection runs on the FINAL body (post-sanitize). BLOCK — never strip (there
    # is no safe rewrite for PHI). Auto-reject so a bad template surfaces to staff
    # (mirrors opt_out/consent); leaving it 'approved' would loop-block forever
    # since the condition is permanent until the template is edited.
    phi_signals = find_phi(body)
    if phi_signals:
        approval.status = EngagementApproval.STATUS_REJECTED
        approval.decided_by = decided_by
        approval.decided_at = dj_timezone.now()
        approval.save(update_fields=["status", "decided_by", "decided_at"])
        logger.warning(
            "[engagement] send BLOCKED — clinical content in body "
            "(approval=%s tenant=%s signals=%s) — NOT sent",
            approval.id, tenant_id, phi_signals,
        )
        return {"ok": False, "reason": "clinical_content_blocked", "provider_msgid": None, "pending": False}

    # SEND — this is the ONLY place a real SMS may go out
    result: SendResult = provider.send(phone, body, message_type="Informational")

    # Record dispatch (idempotency ledger — even if pending, record to avoid duplicate)
    period_key = approval.period_key or f"approval:{approval.id}"
    _record_dispatch(
        tenant_id,
        approval.patient_link_id,
        approval.event_key,
        period_key,
        "sms",
        ref_id=approval.id,
    )

    # Mark approval sent
    now = dj_timezone.now()
    approval.status = EngagementApproval.STATUS_SENT
    approval.sent_at = now
    approval.decided_by = decided_by
    approval.decided_at = now
    approval.save(update_fields=["status", "sent_at", "decided_by", "decided_at"])

    # Audit
    log_activity(
        tenant_id=tenant_id,
        user_id=None,
        username=decided_by,
        action_type="engagement_sms_sent",
        action_category="engagement",
        target_table="clinical.engagement_approvals",
        target_id=approval.id,
        patient_link_id=approval.patient_link_id,
        description=(
            f"event_key={approval.event_key!r} "
            f"provider_msgid={result.provider_msgid!r} "
            f"pending={result.pending}"
        ),
    )

    logger.debug(
        "send_approved_sms: approval_id=%s sent by %r tenant=%s "
        "provider_msgid=%s pending=%s",
        approval_id, decided_by, tenant_id, result.provider_msgid, result.pending,
    )

    return {
        "ok": result.ok or result.pending,  # pending → optimistic ok
        "reason": None if (result.ok or result.pending) else result.error,
        "provider_msgid": result.provider_msgid,
        "pending": result.pending,
    }
