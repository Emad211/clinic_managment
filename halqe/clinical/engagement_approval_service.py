"""
clinical/engagement_approval_service.py — Step 17: Physician Approval Queue.

State machine
─────────────
  pending → approved   (approve)
  pending → rejected   (reject)
  approved, rejected → terminal (any other transition raises InvalidApprovalTransition)

Step 18 will add: approved → sent  (marking sent_at + status='sent' after actual SMS send).

Design
──────
  - Hard gate: NO SMS is sent here. This service only manages the queue.
  - Idempotent enqueue: UNIQUE(tenant_id, patient_link_id, event_key, period_key)
    enforced at DB level. get_or_create semantics: if a row already exists (any
    status), return it unchanged — never reset a decided row.
  - Tenant-scoped: every query filters on tenant_id. Wrong tenant → ApprovalNotFound.
  - Audit: approve/reject log to clinical.activity_logs via audit.log_activity
    (best-effort; audit failure never aborts the main operation).
  - timezone.now() (Django USE_TZ=True) → aware TIMESTAMPTZ.

Public API
──────────
  enqueue_approval(tenant_id, patient_link_id, *, event_key, channel, due_date,
                   message, period_key, offer, appointment_id) -> EngagementApproval
      Idempotent: returns the existing row if (tenant, patient, event_key, period_key)
      already exists. Creates a new 'pending' row otherwise.

  list_pending(tenant_id) -> list[EngagementApproval]
      All status='pending' rows for this tenant, ordered by due_date ASC nulls last,
      then created_at DESC (newest-pending first within same due-date).

  approve(approval_id, tenant_id, *, decided_by) -> EngagementApproval
      Transition pending → approved. Raises InvalidApprovalTransition if not pending.

  reject(approval_id, tenant_id, *, decided_by, reason=None) -> EngagementApproval
      Transition pending → rejected. Raises InvalidApprovalTransition if not pending.

Domain exceptions
─────────────────
  ApprovalNotFound          — row not found for this tenant (404)
  InvalidApprovalTransition — wrong source state for transition (409)
"""
from __future__ import annotations

import logging
from typing import Optional
from datetime import date as _date

from django.utils import timezone

from clinical.models import EngagementApproval
from clinical.audit import log_activity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------

class ApprovalNotFound(Exception):
    """Row does not exist for this (id, tenant_id) pair."""


class InvalidApprovalTransition(Exception):
    """
    State transition not allowed.

    Carry the approval_id and current status so the endpoint can produce a
    meaningful 409 body without re-fetching.
    """
    def __init__(self, message: str, approval_id: int, current_status: str):
        super().__init__(message)
        self.approval_id = approval_id
        self.current_status = current_status


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def enqueue_approval(
    tenant_id: int,
    patient_link_id: int,
    *,
    event_key: str,
    period_key: str,
    channel: Optional[str] = None,
    due_date: Optional[_date] = None,
    message: Optional[str] = None,
    offer: Optional[str] = None,
    appointment_id: Optional[int] = None,
) -> EngagementApproval:
    """
    Create a new 'pending' approval row — or return the existing one.

    Idempotency guarantee: UNIQUE(tenant_id, patient_link_id, event_key, period_key)
    at DB level. If a row already exists for this (tenant, patient, event_key, period_key)
    — regardless of its current status — return it unchanged. Never reset a decided row.

    Step 18's dispatcher will call this for SMS-channel due events instead of
    sending directly, so the physician can approve before any SMS is sent.
    """
    # Attempt get first — avoids an IntegrityError on the happy path when the
    # row already exists (any status). Only fall through to create on DoesNotExist.
    try:
        existing = EngagementApproval.objects.get(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            event_key=event_key,
            period_key=period_key,
        )
        logger.debug(
            "enqueue_approval: existing row id=%s status=%s (tenant=%s, patient=%s, "
            "event_key=%r, period_key=%r) — returning unchanged",
            existing.id,
            existing.status,
            tenant_id,
            patient_link_id,
            event_key,
            period_key,
        )
        return existing
    except EngagementApproval.DoesNotExist:
        pass

    # Create a fresh pending row
    now = timezone.now()
    approval = EngagementApproval.objects.create(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        event_key=event_key,
        period_key=period_key,
        channel=channel,
        due_date=due_date,
        message=message,
        offer=offer,
        appointment_id=appointment_id,
        status=EngagementApproval.STATUS_PENDING,
        created_at=now,
    )
    logger.debug(
        "enqueue_approval: created id=%s (tenant=%s, patient=%s, event_key=%r, period_key=%r)",
        approval.id,
        tenant_id,
        patient_link_id,
        event_key,
        period_key,
    )
    return approval


def list_pending(tenant_id: int) -> list[EngagementApproval]:
    """
    Return all pending approval rows for this tenant.

    Ordering: due_date ASC nulls last, then created_at DESC (newest pending first
    within the same due date bucket).
    """
    from django.db.models import F
    from django.db.models.functions import Coalesce
    from django.db.models import Value
    import datetime

    # Postgres: NULLS LAST on due_date ASC, then newest created_at first
    return list(
        EngagementApproval.objects.filter(
            tenant_id=tenant_id,
            status=EngagementApproval.STATUS_PENDING,
        ).order_by(
            F("due_date").asc(nulls_last=True),
            "-created_at",
        )
    )


def approve(
    approval_id: int,
    tenant_id: int,
    *,
    decided_by: str,
) -> EngagementApproval:
    """
    Transition pending → approved.

    Sets decided_by and decided_at. Does NOT send any SMS.
    Raises ApprovalNotFound if the row does not exist for this tenant.
    Raises InvalidApprovalTransition if the row is not in 'pending' status.
    """
    approval = _get_or_raise(approval_id, tenant_id)

    if approval.status != EngagementApproval.STATUS_PENDING:
        raise InvalidApprovalTransition(
            f"Approval id={approval_id} is '{approval.status}'; "
            f"only 'pending' rows can be approved.",
            approval_id=approval_id,
            current_status=approval.status,
        )

    approval.status = EngagementApproval.STATUS_APPROVED
    approval.decided_by = decided_by
    approval.decided_at = timezone.now()
    approval.save(update_fields=["status", "decided_by", "decided_at"])

    log_activity(
        tenant_id=tenant_id,
        user_id=None,        # no user object in the service layer — caller passes username
        username=decided_by,
        action_type="engagement_approval_approved",
        action_category="engagement",
        target_table="clinical.engagement_approvals",
        target_id=approval.id,
        patient_link_id=approval.patient_link_id,
        description=f"event_key={approval.event_key!r} period_key={approval.period_key!r}",
    )

    logger.debug(
        "approve: id=%s approved by %r (tenant=%s)", approval_id, decided_by, tenant_id
    )
    return approval


def reject(
    approval_id: int,
    tenant_id: int,
    *,
    decided_by: str,
    reason: Optional[str] = None,
) -> EngagementApproval:
    """
    Transition pending → rejected.

    Sets decided_by and decided_at. If reason is provided, it is appended to
    the message field (no dedicated rejection_reason column in schema).
    Raises ApprovalNotFound if the row does not exist for this tenant.
    Raises InvalidApprovalTransition if the row is not in 'pending' status.
    """
    approval = _get_or_raise(approval_id, tenant_id)

    if approval.status != EngagementApproval.STATUS_PENDING:
        raise InvalidApprovalTransition(
            f"Approval id={approval_id} is '{approval.status}'; "
            f"only 'pending' rows can be rejected.",
            approval_id=approval_id,
            current_status=approval.status,
        )

    approval.status = EngagementApproval.STATUS_REJECTED
    approval.decided_by = decided_by
    approval.decided_at = timezone.now()

    update_fields = ["status", "decided_by", "decided_at"]

    # Append reason to message (no dedicated column) — used for audit trail only
    if reason:
        existing_message = approval.message or ""
        sep = " | " if existing_message else ""
        approval.message = f"{existing_message}{sep}rejected: {reason}"
        update_fields.append("message")

    approval.save(update_fields=update_fields)

    log_activity(
        tenant_id=tenant_id,
        user_id=None,
        username=decided_by,
        action_type="engagement_approval_rejected",
        action_category="engagement",
        target_table="clinical.engagement_approvals",
        target_id=approval.id,
        patient_link_id=approval.patient_link_id,
        description=(
            f"event_key={approval.event_key!r} period_key={approval.period_key!r}"
            + (f" reason={reason!r}" if reason else "")
        ),
    )

    logger.debug(
        "reject: id=%s rejected by %r (tenant=%s)", approval_id, decided_by, tenant_id
    )
    return approval


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_or_raise(approval_id: int, tenant_id: int) -> EngagementApproval:
    """
    Fetch an EngagementApproval by (id, tenant_id).

    Raises ApprovalNotFound if not found — tenant isolation: a wrong tenant id
    is indistinguishable from 'not found' (no information leakage).
    """
    try:
        return EngagementApproval.objects.get(id=approval_id, tenant_id=tenant_id)
    except EngagementApproval.DoesNotExist:
        raise ApprovalNotFound(
            f"EngagementApproval id={approval_id} not found for tenant={tenant_id}."
        )
