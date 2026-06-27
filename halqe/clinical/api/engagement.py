"""
Engagement approval-queue domain router (Steps 17-18) — physician hard gate
before any SMS.

Migrated out of the ``config/api.py`` god-file in cleanup step 4.

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", engagement_router)`` and the routes below carry their full
sub-paths, so ``/api/v1`` (urls.py) + ``""`` (prefix) + ``"/engagement/…"`` ==
the same paths as before:

  GET  /api/v1/engagement/approvals                  → pending queue (any authed user)
  POST /api/v1/engagement/approvals/{id}/approve     → pending → approved (manager only)
  POST /api/v1/engagement/approvals/{id}/reject      → pending → rejected (manager only)
  POST /api/v1/engagement/approvals/{id}/send        → approved → sent (manager only, Step 18)

GET is the only path that lists; approve/reject/send are manager-only — the
safety gate MUST be privileged. /send is the ONLY endpoint that actually sends
an SMS (NullProvider in tests → SIMULATED, no real network call).
"""
from typing import Optional
from datetime import datetime, date

from ninja import Router, Schema

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response
from clinical.api._shared import _assert_manager
from clinical.models import (
    EngagementApproval as _EngagementApproval,
    EngagementEvent,
    PatientLink,
    VitalReading,
    Appointment,
)
from clinical.engagement_approval_service import (
    list_pending as _list_pending_approvals,
    approve as _approve_approval,
    reject as _reject_approval,
    ApprovalNotFound as _ApprovalNotFound,
    InvalidApprovalTransition as _InvalidApprovalTransition,
)
from clinical.engagement_service import send_approved_sms as _send_approved_sms
from clinical.engagement_settings import (
    get_engagement_settings as _get_engagement_settings,
    save_engagement_settings as _save_engagement_settings,
)
from clinical.audit import log_activity
from accounting_port.port import get_patients_by_ids

router = Router()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EngagementApprovalDTO(Schema):
    """
    One engagement approval row — enriched for the manager review card (step 52).

    status values: 'pending' | 'approved' | 'rejected' | 'sent' (Step 18).

    The enrichment fields (event_label, patient_name, sms_opt_out, sms_consent,
    last_contact_at) are computed by list_engagement_approvals in ONE batched pass
    (no N+1) so the reviewer can judge each pending SMS without extra round-trips.
    They mirror the locked web contract EngagementApproval (web/src/lib/api.ts).
    """
    id: int
    tenant_id: int
    patient_link_id: int
    event_key: str
    # Human-readable Persian label resolved from engagement_events.label;
    # falls back to event_key when no matching event row exists.
    event_label: str
    # Minimum-necessary patient name (FIRST name only) from the accounting Port —
    # same privacy framing as the public card (card_projection_service).
    patient_name: str
    channel: Optional[str] = None
    due_date: Optional[date] = None
    message: Optional[str] = None
    offer: Optional[str] = None
    status: str
    period_key: Optional[str] = None
    appointment_id: Optional[int] = None
    # patient_links.sms_opt_out — red badge, blocks send.
    sms_opt_out: bool = False
    # patient_links.sms_consent — warning badge when False.
    sms_consent: bool = False
    # ISO datetime of the last outbound/verified contact, or null (never contacted).
    # max(latest done-appointment scheduled_at, latest VERIFIED vital measured_at).
    last_contact_at: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: datetime


class ApprovalListResponse(Schema):
    """Pending queue list."""
    items: list[EngagementApprovalDTO]
    total: int


class ApproveRejectIn(Schema):
    """Optional body for approve/reject endpoints."""
    reason: Optional[str] = None   # only used by reject; ignored on approve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_name_from_demo(demo) -> str:
    """
    Minimum-necessary patient name: FIRST name only, never the full name.

    Mirrors card_projection_service: prefer accounting.patients.name (the given
    name), fall back to the first whitespace-token of full_name. Empty string
    when no demographics are available (the reviewer still sees the message).
    """
    if demo is None:
        return ""
    name = (getattr(demo, "name", None) or "").strip()
    if name:
        return name
    full = (getattr(demo, "full_name", None) or "").strip()
    if full:
        return full.split(" ")[0]
    return ""


def _enrich_approvals(
    tenant_id: int,
    approvals: list["_EngagementApproval"],
) -> dict[int, dict]:
    """
    Batch-compute the enrichment fields for a list of approval rows.

    Returns {approval_id: {event_label, patient_name, sms_opt_out, sms_consent,
                           last_contact_at}}.

    All lookups are batched (no N+1):
      - event labels   : one query over engagement_events for the page's event_keys.
      - patient names  : one Port call (get_patients_by_ids) for the page's patients.
      - opt_out/consent: one query over patient_links for the page's link_ids.
      - last_contact   : one aggregate per source (done-appointments, verified vitals).
    """
    if not approvals:
        return {}

    link_ids = sorted({a.patient_link_id for a in approvals})
    event_keys = sorted({a.event_key for a in approvals if a.event_key})

    # 1) event_key → label (engagement_events, tenant-scoped). Fallback = event_key.
    label_by_event: dict[str, str] = {}
    if event_keys:
        for ev in EngagementEvent.objects.filter(
            tenant_id=tenant_id, event_key__in=event_keys
        ).values("event_key", "label"):
            label_by_event[ev["event_key"]] = ev["label"]

    # 2) patient_links → (patient_id, sms_opt_out, sms_consent) for the page.
    link_rows = {
        pl["id"]: pl
        for pl in PatientLink.objects.filter(
            tenant_id=tenant_id, id__in=link_ids
        ).values("id", "patient_id", "sms_opt_out", "sms_consent")
    }

    # 3) demographics (FIRST name only) — one Port call for the page's patients.
    patient_ids = sorted({r["patient_id"] for r in link_rows.values()})
    demos_by_pid = {d.id: d for d in get_patients_by_ids(patient_ids)}

    # 4) last_contact_at = max(latest done-appt scheduled_at, latest verified vital).
    #    Two batched aggregates keyed by patient_link_id; merged in Python.
    from django.db.models import Max
    appt_max: dict[int, datetime] = {
        r["patient_link_id"]: r["m"]
        for r in Appointment.objects.filter(
            tenant_id=tenant_id,
            patient_link_id__in=link_ids,
            status=Appointment.STATUS_DONE,
        )
        .values("patient_link_id")
        .annotate(m=Max("scheduled_at"))
    }
    vital_max: dict[int, datetime] = {
        r["patient_link_id"]: r["m"]
        for r in VitalReading.objects.filter(
            tenant_id=tenant_id,
            patient_link_id__in=link_ids,
            verified=True,
        )
        .values("patient_link_id")
        .annotate(m=Max("measured_at"))
    }

    enriched: dict[int, dict] = {}
    for a in approvals:
        link = link_rows.get(a.patient_link_id)
        pid = link["patient_id"] if link else None
        demo = demos_by_pid.get(pid) if pid is not None else None

        # last_contact: max of the two sources (either may be absent → None)
        candidates = [
            t for t in (
                appt_max.get(a.patient_link_id),
                vital_max.get(a.patient_link_id),
            ) if t is not None
        ]
        last_contact = max(candidates) if candidates else None

        enriched[a.id] = {
            "event_label": label_by_event.get(a.event_key) or a.event_key,
            "patient_name": _first_name_from_demo(demo),
            "sms_opt_out": bool(link["sms_opt_out"]) if link else False,
            "sms_consent": bool(link["sms_consent"]) if link else False,
            "last_contact_at": last_contact.isoformat() if last_contact else None,
        }
    return enriched


def _approval_to_dto(
    approval: "_EngagementApproval",
    enrichment: Optional[dict] = None,
) -> EngagementApprovalDTO:
    """
    Serialise one approval row.

    enrichment: the per-row dict from _enrich_approvals (the LIST endpoint passes
    it for the whole page in one batched no-N+1 pass).

    When omitted (single-row transition endpoints: approve/reject), we DELIBERATELY
    do NOT call the accounting Port here.  Those transition responses are not read
    for their enrichment fields by the frontend (the manager UI only calls
    removeItem after approve/reject) — and a per-transition Port round-trip would
    (a) be wasted work and (b) force every approve/reject test to declare the
    'accounting_read' alias + transaction=True.  Instead we fill the required
    contract fields with the same SAFE FALLBACKS _enrich_approvals uses when a
    source is absent: event_label = event_key, patient_name = "".  The required
    contract fields are still present and valid; only the LIST path is enriched.
    """
    if enrichment is None:
        enrichment = {
            "event_label": approval.event_key,
            "patient_name": "",
            "sms_opt_out": False,
            "sms_consent": False,
            "last_contact_at": None,
        }

    return EngagementApprovalDTO(
        id=approval.id,
        tenant_id=approval.tenant_id,
        patient_link_id=approval.patient_link_id,
        event_key=approval.event_key,
        event_label=enrichment.get("event_label") or approval.event_key,
        patient_name=enrichment.get("patient_name", ""),
        channel=approval.channel,
        due_date=approval.due_date,
        message=approval.message,
        offer=approval.offer,
        status=approval.status,
        period_key=approval.period_key,
        appointment_id=approval.appointment_id,
        sms_opt_out=enrichment.get("sms_opt_out", False),
        sms_consent=enrichment.get("sms_consent", False),
        last_contact_at=enrichment.get("last_contact_at"),
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        sent_at=approval.sent_at,
        created_at=approval.created_at,
    )


# The manager-role 403 gate is now the shared ``_assert_manager`` imported from
# ``clinical.api._shared`` (cleanup step 62). Its canonical body is the Persian
# message + code 'forbidden' (unified with the manager analytics domain).


# ---------------------------------------------------------------------------
# GET /engagement/approvals — pending queue (any authed user can VIEW)
# ---------------------------------------------------------------------------

@router.get(
    "/engagement/approvals",
    response=ApprovalListResponse,
    auth=_jwt_auth,
    tags=["engagement"],
)
def list_engagement_approvals(request):
    """
    Return the pending engagement approval queue for the authenticated tenant.

    Any authenticated user (staff or manager) can VIEW the queue.
    Only managers can approve or reject items (see the POST endpoints below).

    Ordered by due_date ASC (nulls last), then newest first within the same day.
    Returns only status='pending' items — use the admin panel or DB directly to
    review approved/rejected history.

    NO SMS is sent here.  Requires JWT (tenant-scoped).
    """
    tenant_id = request.tenant_id
    rows = _list_pending_approvals(tenant_id)
    # Single batched enrichment pass for the whole page (no N+1).
    enrichment = _enrich_approvals(tenant_id, rows)
    return ApprovalListResponse(
        items=[_approval_to_dto(r, enrichment.get(r.id)) for r in rows],
        total=len(rows),
    )


# ---------------------------------------------------------------------------
# POST /engagement/approvals/{id}/approve — pending → approved (manager only)
# ---------------------------------------------------------------------------

@router.post(
    "/engagement/approvals/{approval_id}/approve",
    response={
        200: EngagementApprovalDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["engagement"],
)
def approve_engagement_approval(request, approval_id: int, body: ApproveRejectIn = None):
    """
    Approve a pending engagement approval (manager-only).

    Transitions status: pending → approved.
    Sets decided_by (JWT username) and decided_at (now()).
    Does NOT send any SMS — Step 18 will process approved rows.

    Returns 403 if the authenticated user is not a manager.
    Returns 404 if the approval does not exist for this tenant.
    Returns 409 if the approval is not in 'pending' status (already decided).
    Requires JWT (tenant-scoped, manager role).
    """
    # Manager gate — the approval is the privileged safety gate
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    try:
        approval = _approve_approval(approval_id, tenant_id, decided_by=actor)
    except _ApprovalNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _InvalidApprovalTransition as exc:
        return 409, error_response(str(exc), "invalid_transition")

    return 200, _approval_to_dto(approval)


# ---------------------------------------------------------------------------
# POST /engagement/approvals/{id}/reject — pending → rejected (manager only)
# ---------------------------------------------------------------------------

@router.post(
    "/engagement/approvals/{approval_id}/reject",
    response={
        200: EngagementApprovalDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["engagement"],
)
def reject_engagement_approval(request, approval_id: int, body: ApproveRejectIn = None):
    """
    Reject a pending engagement approval (manager-only).

    Transitions status: pending → rejected.
    Sets decided_by (JWT username) and decided_at (now()).
    The optional body.reason is appended to the message field for audit trail.

    Returns 403 if the authenticated user is not a manager.
    Returns 404 if the approval does not exist for this tenant.
    Returns 409 if the approval is not in 'pending' status (already decided).
    Requires JWT (tenant-scoped, manager role).
    """
    # Manager gate — the approval is the privileged safety gate
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    reason = body.reason if body else None

    try:
        approval = _reject_approval(approval_id, tenant_id, decided_by=actor, reason=reason)
    except _ApprovalNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _InvalidApprovalTransition as exc:
        return 409, error_response(str(exc), "invalid_transition")

    return 200, _approval_to_dto(approval)


# ---------------------------------------------------------------------------
# POST /engagement/approvals/{id}/send — approved → sent (Step 18, manager only)
#
# This is the ONLY endpoint that actually sends an SMS.
# The manager must first approve (pending → approved), then trigger send here.
# Quiet-hours guard is enforced (08:00-21:00 Tehran) unless override_quiet=True.
# Uses get_provider() which returns NullProvider when no API key is configured.
# In tests, provider is always NullProvider → SIMULATED, NO real network call.
# ---------------------------------------------------------------------------

class SendApprovalIn(Schema):
    """Optional body for the send endpoint."""
    override_quiet: bool = False  # bypass quiet-hours gate (e.g. urgent clinical)


class SendApprovalOut(Schema):
    """Result of an SMS send attempt."""
    ok: bool
    reason: Optional[str] = None
    provider_msgid: Optional[str] = None
    pending: bool = False
    approval_id: int
    status: str                   # final approval status after send attempt


@router.post(
    "/engagement/approvals/{approval_id}/send",
    response={
        200: SendApprovalOut,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["engagement"],
)
def send_engagement_approval(
    request,
    approval_id: int,
    body: SendApprovalIn = None,
):
    """
    Send the SMS for an approved engagement approval (manager-only, Step 18).

    The approval must already be in status='approved' (call approve first).
    This endpoint is the ONLY path where a real SMS can leave the system.

    Guardrails:
      - Patient opt-out re-checked → auto-rejects and returns ok=False reason='opt_out'.
      - Phone via AccountingPort (PatientLink has no phone — ADR-0007).
        No phone → auto-rejects, ok=False, reason='no_phone'.
      - Quiet hours (08:00-21:00 Tehran): blocks outside window unless
        body.override_quiet=True.  Approval stays 'approved' (send later).
      - get_provider(): returns NullProvider when no KAVENEGAR_API_KEY is set.
        In tests NullProvider is always used → SIMULATED, no network call.
      - On send: records dispatch (idempotency ledger) + marks approval
        status='sent' + sent_at=now().

    Returns 403 if not a manager.
    Returns 404 if approval not found for this tenant.
    Returns 409 if approval is not in status='approved' (wrong state).

    KAVENEGAR KYC NOTE: the live key returns code 430 (KYC not complete).
    No real SMS is sent until the owner finishes KYC.  Use NullProvider in tests.
    """
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    override_quiet = (body.override_quiet if body else False)

    # Verify the approval exists and is in the correct state before calling send
    try:
        approval_obj = _EngagementApproval.objects.get(
            id=approval_id, tenant_id=tenant_id
        )
    except _EngagementApproval.DoesNotExist:
        return 404, error_response(
            f"EngagementApproval id={approval_id} not found for this tenant.",
            "not_found",
        )

    if approval_obj.status != _EngagementApproval.STATUS_APPROVED:
        return 409, error_response(
            f"Approval id={approval_id} is '{approval_obj.status}'; "
            "only 'approved' rows can be sent. Call /approve first.",
            "invalid_transition",
        )

    result = _send_approved_sms(
        approval_id,
        tenant_id,
        decided_by=actor,
        override_quiet=override_quiet,
    )

    # Re-fetch the approval to get the final status after send_approved_sms
    try:
        approval_obj.refresh_from_db()
    except Exception:
        pass

    if result.get("reason") == "not_found":
        return 404, error_response(
            f"EngagementApproval id={approval_id} not found for this tenant.",
            "not_found",
        )

    return 200, SendApprovalOut(
        ok=result["ok"],
        reason=result.get("reason"),
        provider_msgid=result.get("provider_msgid"),
        pending=result.get("pending", False),
        approval_id=approval_id,
        status=approval_obj.status,
    )


# ===========================================================================
# Engagement event→channel config + guardrail settings (Step 52, cluster L).
#
# GET /engagement/events            → list event→channel routing (manager-only)
# PUT /engagement/events/{key}      → update channel + cooldown (manager-only)
# GET /engagement/settings          → quiet hours + daily cap (manager-only)
# PUT /engagement/settings          → update quiet hours + daily cap (manager-only)
#
# All four are manager-only (staff → 403) via the shared ``_assert_manager`` gate
# — engagement routing/guardrails are a privileged configuration surface, like
# the approval gate above.  No SMS is ever sent from these endpoints.  Settings
# are persisted via the dedicated engagement_settings service (platform.settings,
# tenant-scoped).
#
# ROUTER PLACEMENT NOTE: these config endpoints live on the ENGAGEMENT router
# (prefix "") rather than the manager analytics router (prefix "/manager") so the
# full URLs stay /api/v1/engagement/events and /api/v1/engagement/settings — the
# exact paths the step-52 frontend (web/src/lib/api.ts) consumes. Manager-only
# is enforced by ``_assert_manager``, not by router location.
# ===========================================================================


# ── Schemas ────────────────────────────────────────────────────────────────

class EngagementEventDTO(Schema):
    """
    One event→channel routing row — matches the locked web contract
    EngagementEvent (web/src/lib/api.ts).
    """
    event_key: str
    label: str
    category: str
    channel: str          # sms | worklist | both | off
    cooldown_days: int


class UpdateEngagementEventIn(Schema):
    """Body for PUT /engagement/events/{event_key}."""
    channel: str          # sms | worklist | both | off
    cooldown_days: int


class EngagementSettingsDTO(Schema):
    """Global engagement guardrails — matches the web EngagementSettings."""
    quiet_start: str      # "HH:MM" Tehran-local
    quiet_end: str        # "HH:MM" Tehran-local
    daily_cap: int        # max SMS per tenant per day (0 = unlimited / gate inert)


class UpdateEngagementSettingsIn(Schema):
    """Body for PUT /engagement/settings."""
    quiet_start: str
    quiet_end: str
    daily_cap: int


_VALID_CHANNELS = {"sms", "worklist", "both", "off"}


def _event_to_dto(ev: EngagementEvent) -> EngagementEventDTO:
    return EngagementEventDTO(
        event_key=ev.event_key,
        label=ev.label,
        category=ev.category,
        channel=ev.channel,
        cooldown_days=ev.cooldown_days,
    )


# ---------------------------------------------------------------------------
# GET /engagement/events — list event→channel routing (manager-only)
# ---------------------------------------------------------------------------

@router.get(
    "/engagement/events",
    response={200: list[EngagementEventDTO], 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["engagement"],
)
def list_engagement_events(request):
    """
    Return all active event→channel routing rows for this tenant (manager-only).

    Ordered by the model default (priority, id).  Staff → 403.
    """
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    events = list(
        EngagementEvent.objects.filter(tenant_id=tenant_id, is_active=True)
    )
    return 200, [_event_to_dto(e) for e in events]


# ---------------------------------------------------------------------------
# PUT /engagement/events/{event_key} — update channel + cooldown (manager-only)
# ---------------------------------------------------------------------------

@router.put(
    "/engagement/events/{event_key}",
    response={
        200: EngagementEventDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        422: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["engagement"],
)
def update_engagement_event(request, event_key: str, body: UpdateEngagementEventIn):
    """
    Update the channel + cooldown_days of one engagement event (manager-only).

    channel ∈ {sms, worklist, both, off} (invalid → 422).
    cooldown_days must be >= 0 (negative → 422).
    Returns 404 if no active event row for this (tenant, event_key).
    Audited (state-changing config write).
    """
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    # Validate inputs before touching the row
    if body.channel not in _VALID_CHANNELS:
        return 422, error_response(
            f"Invalid channel {body.channel!r}. Must be one of "
            f"{sorted(_VALID_CHANNELS)}.",
            "validation_error",
        )
    if body.cooldown_days < 0:
        return 422, error_response(
            f"cooldown_days must be >= 0 (got {body.cooldown_days}).",
            "validation_error",
        )

    try:
        ev = EngagementEvent.objects.get(
            tenant_id=tenant_id, event_key=event_key, is_active=True
        )
    except EngagementEvent.DoesNotExist:
        return 404, error_response(
            f"EngagementEvent event_key={event_key!r} not found for this tenant.",
            "not_found",
        )

    ev.channel = body.channel
    ev.cooldown_days = body.cooldown_days
    ev.save(update_fields=["channel", "cooldown_days"])

    log_activity(
        tenant_id=tenant_id,
        user_id=getattr(request.auth, "pk", None),
        username=actor,
        action_type="engagement_event_updated",
        action_category="engagement",
        target_table="engagement_events",
        target_id=ev.id,
        description=f"event_key={event_key!r} channel={body.channel!r} "
                    f"cooldown_days={body.cooldown_days}",
    )

    return 200, _event_to_dto(ev)


# ---------------------------------------------------------------------------
# GET /engagement/settings — quiet hours + daily cap (manager-only)
# ---------------------------------------------------------------------------

@router.get(
    "/engagement/settings",
    response={200: EngagementSettingsDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["engagement"],
)
def get_engagement_settings_endpoint(request):
    """
    Return the engagement guardrail settings for this tenant (manager-only).

    Falls back to module defaults for any unset key (08:00–21:00, cap 50).
    Staff → 403.
    """
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    return 200, EngagementSettingsDTO(**_get_engagement_settings(tenant_id))


# ---------------------------------------------------------------------------
# PUT /engagement/settings — update quiet hours + daily cap (manager-only)
# ---------------------------------------------------------------------------

@router.put(
    "/engagement/settings",
    response={
        200: EngagementSettingsDTO,
        403: ErrorSchema,
        422: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["engagement"],
)
def update_engagement_settings_endpoint(request, body: UpdateEngagementSettingsIn):
    """
    Update the engagement guardrail settings for this tenant (manager-only).

    Validation lives in the service (save_engagement_settings); a ValueError is
    mapped to 422.  Returns the re-read persisted settings (round-trip confirm).
    Staff → 403.  Audited.
    """
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    try:
        settings_dict = _save_engagement_settings(
            tenant_id,
            quiet_start=body.quiet_start,
            quiet_end=body.quiet_end,
            daily_cap=body.daily_cap,
            updated_by=actor,
        )
    except ValueError as exc:
        return 422, error_response(str(exc), "validation_error")

    log_activity(
        tenant_id=tenant_id,
        user_id=getattr(request.auth, "pk", None),
        username=actor,
        action_type="engagement_settings_updated",
        action_category="engagement",
        target_table="platform.settings",
        description=f"quiet_start={body.quiet_start} quiet_end={body.quiet_end} "
                    f"daily_cap={body.daily_cap}",
    )

    return 200, EngagementSettingsDTO(**settings_dict)
