"""
Audit logging helper — append-only write to clinical.activity_logs.

Usage:
    from clinical.audit import log_activity
    log_activity(
        tenant_id=request.tenant_id,
        user_id=request.auth.pk,
        username=request.auth.username,
        action_type="login",
        action_category="auth",
    )

Design decisions:
  - Append-only: only INSERT (no UPDATE/DELETE). The DB enforces this via
    REVOKE UPDATE, DELETE ON clinical.activity_logs FROM clinical_app.
  - created_at: set explicitly via Django's auto_now_add on ActivityLog
    (TIMESTAMPTZ DEFAULT now() also covers direct-SQL paths).
  - Best-effort: if the audit INSERT fails, the exception is caught and
    logged to stderr — the main request is NOT 500'd because of an audit
    failure. In tests the insert must succeed (no mocking), so failures
    will surface as test errors.
  - All arguments are keyword-only to prevent positional-order mistakes.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def log_activity(
    *,
    tenant_id: int,
    user_id: Optional[int],
    username: Optional[str],
    action_type: str,
    action_category: Optional[str] = None,
    description: Optional[str] = None,
    target_table: Optional[str] = None,
    target_id: Optional[int] = None,
    patient_link_id: Optional[int] = None,
) -> None:
    """
    Insert one row into clinical.activity_logs.

    Swallows exceptions (best-effort) — logs to stderr on failure.
    Callers should NOT rely on the return value; it is always None.
    """
    # Import inside the function to avoid circular imports at module load time.
    from clinical.models import ActivityLog

    try:
        ActivityLog.objects.create(
            tenant_id=tenant_id,
            user_id=user_id,
            username=username,
            action_type=action_type,
            action_category=action_category,
            description=description,
            target_table=target_table,
            target_id=target_id,
            patient_link_id=patient_link_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "audit log_activity failed (best-effort, not propagating): "
            "action_type=%s tenant_id=%s user_id=%s error=%r",
            action_type,
            tenant_id,
            user_id,
            exc,
        )
