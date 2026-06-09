"""Append-only audit logging (REGULATORY §6 — accountability / ممیزی).

``log_activity`` records a state-changing action into ``activity_log``. It mirrors
the Flask apps' ``services/activity_logger.log_activity`` so the audit habit
carries over to the platform. Best-effort by design: a logging failure must never
break the primary action, so the insert is isolated in its own savepoint and any
error is swallowed (the audit trail is important, but losing one row must not roll
back a successful clinical/financial mutation).

Must be called inside the acting clinic's tenant context (the web request already
is, via TenantMiddleware) so the RLS WITH CHECK on ``activity_log`` passes.
"""

from django.db import transaction

from apps.common.models import ActivityLog


def log_activity(clinic, actor, action, summary="", *, entity_type="",
                 entity_id=None, metadata=None):
    """Write one append-only audit row. Returns the row, or None on failure."""
    try:
        with transaction.atomic():  # savepoint: isolate a logging failure
            return ActivityLog.objects.create(
                clinic=clinic,
                actor=actor,
                actor_username=getattr(actor, "username", "") or "",
                action=action,
                summary=summary or "",
                entity_type=entity_type or "",
                entity_id=entity_id,
                metadata=metadata or {},
            )
    except Exception:
        return None
