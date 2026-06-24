"""
GUC tenant-context helpers — Step 2 of halqe platform hardening.

Purpose: install the hook that future RLS policies (Step 19) will consume.
         This step sets the mechanism; RLS policy is NOT enabled here.

Design (RATIONALE encoded for Step 19 reviewers):
  - PostgreSQL GUC `app.current_tenant` is set per-connection via set_config().
  - is_local=False (third arg = false) means the setting persists on the
    pooled/persistent connection beyond the current transaction. This is
    intentional: the request thread reuses one connection for all its queries,
    and we want every query on that connection to see the correct tenant.
  - TenantGucMiddleware clears the GUC to '' at the START of every request
    (defense: pooled connections could carry a previous request's tenant into
    an endpoint that does not set it — e.g. unauthenticated routes).
  - JWTBearer.authenticate() SETS the GUC after resolving the user's tenant_id
    from the JWT claims. Because auth runs inside the view dispatch (after
    middleware), the order is: CLEAR (middleware) → SET (auth) → view queries.
  - RLS policies in Step 19 will read:
        current_setting('app.current_tenant', true)
    The second arg (missing_ok=true) returns '' when not set, so an
    unauthenticated request returns '' (fail-safe, no tenant leak).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def set_tenant_guc(tenant_id: int) -> None:
    """
    Set `app.current_tenant` GUC on the Django `default` connection.

    Called by JWTBearer.authenticate() immediately after the user's tenant_id
    is resolved from the JWT token. This ensures every query on the current
    request thread's connection is associated with the correct tenant — and
    future RLS policies on clinical.* will enforce it automatically.

    Uses is_local=false so the value persists on the connection for the
    duration of the request (not just the current transaction block).
    """
    from django.db import connection  # local import — avoids circular import at module load

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_tenant', %s, false)",
                [str(tenant_id)],
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "set_tenant_guc: failed to set GUC for tenant_id=%s", tenant_id
        )


def clear_tenant_guc() -> None:
    """
    Clear `app.current_tenant` GUC on the Django `default` connection.

    Called by TenantGucMiddleware at the START of every request (before the
    view runs). This is a defense-in-depth measure: if the connection was
    previously used by a different request that set the GUC, clearing it here
    prevents the stale value from leaking into an unauthenticated endpoint.

    The authed flow then re-sets it in JWTBearer.authenticate().
    """
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_tenant', '', false)",
                [],
            )
    except Exception:  # noqa: BLE001
        logger.warning("clear_tenant_guc: failed to clear GUC")
