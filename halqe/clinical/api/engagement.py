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
from clinical.models import EngagementApproval as _EngagementApproval
from clinical.engagement_approval_service import (
    list_pending as _list_pending_approvals,
    approve as _approve_approval,
    reject as _reject_approval,
    ApprovalNotFound as _ApprovalNotFound,
    InvalidApprovalTransition as _InvalidApprovalTransition,
)
from clinical.engagement_service import send_approved_sms as _send_approved_sms

router = Router()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EngagementApprovalDTO(Schema):
    """
    One engagement approval row.

    status values: 'pending' | 'approved' | 'rejected' | 'sent' (Step 18).
    """
    id: int
    tenant_id: int
    patient_link_id: int
    event_key: str
    channel: Optional[str] = None
    due_date: Optional[date] = None
    message: Optional[str] = None
    offer: Optional[str] = None
    status: str
    period_key: Optional[str] = None
    appointment_id: Optional[int] = None
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

def _approval_to_dto(approval: "_EngagementApproval") -> EngagementApprovalDTO:
    return EngagementApprovalDTO(
        id=approval.id,
        tenant_id=approval.tenant_id,
        patient_link_id=approval.patient_link_id,
        event_key=approval.event_key,
        channel=approval.channel,
        due_date=approval.due_date,
        message=approval.message,
        offer=approval.offer,
        status=approval.status,
        period_key=approval.period_key,
        appointment_id=approval.appointment_id,
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
    return ApprovalListResponse(
        items=[_approval_to_dto(r) for r in rows],
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
