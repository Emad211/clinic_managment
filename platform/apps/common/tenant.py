"""Tenant context helpers for PostgreSQL Row-Level Security.

The whole multi-tenancy model (docs/DATA_MODEL.md §3) rests on a single
session GUC: ``app.current_clinic``. RLS policies on every domain table read it:

    USING (clinic_id = current_setting('app.current_clinic', true)::uuid)

deny-by-default: if the GUC is unset, ``current_setting(..., true)`` returns
NULL and no row matches -> zero rows. The DB role must NOT have BYPASSRLS.

Two entry points set it:
- Web requests: ``TenantMiddleware`` (apps/common/middleware.py).
- Background workers / management commands: ``with tenant_context(clinic_id):``.
"""

from contextlib import contextmanager

from django.db import connection, transaction

# Use SET LOCAL so the value is scoped to the surrounding transaction and is
# automatically discarded on commit/rollback -- no leakage across pooled
# connections. SET LOCAL therefore REQUIRES an open transaction.
_SET_SQL = "SELECT set_config('app.current_clinic', %s, true)"  # true => local
_RESET_SQL = "SELECT set_config('app.current_clinic', '', true)"


def set_current_clinic(clinic_id) -> None:
    """Set the tenant GUC on the current connection (transaction-local)."""
    with connection.cursor() as cur:
        cur.execute(_SET_SQL, [str(clinic_id) if clinic_id else ""])


def get_current_clinic():
    with connection.cursor() as cur:
        cur.execute("SELECT current_setting('app.current_clinic', true)")
        row = cur.fetchone()
    return row[0] if row and row[0] else None


@contextmanager
def tenant_context(clinic_id):
    """Run a block scoped to a single tenant (for workers, commands, tests).

    Opens a transaction so SET LOCAL is valid for the whole block.
    """
    with transaction.atomic():
        set_current_clinic(clinic_id)
        yield
