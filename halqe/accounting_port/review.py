"""Read-only accounting identity lookup for migration review gates.

Clinical release verification needs to prove that a selected clinical
``patient_link_id`` still resolves to the UUID written into the pseudonymous
review packet. It crosses the clinical → accounting boundary only through this
SELECT-only port and never mutates accounting demographics.
"""
from __future__ import annotations

from typing import Optional

from django.db import connections, transaction


def get_accounting_patient_uuid_for_review(
    *, accounting_patient_id: int, tenant_id: int
) -> Optional[str]:
    """Return the accounting UUID for one tenant-scoped patient id, if present."""
    if int(accounting_patient_id) <= 0 or int(tenant_id) <= 0:
        return None
    with transaction.atomic(using="accounting_read"):
        with connections["accounting_read"].cursor() as cursor:
            # Use the canonical application GUC. Accounting is currently protected
            # by SELECT-only grants rather than RLS, but this keeps the port correct
            # if accounting RLS is enabled later and matches every clinical policy.
            cursor.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                [str(int(tenant_id))],
            )
            cursor.execute(
                """
                SELECT uuid
                FROM accounting.patients
                WHERE tenant_id=%s AND id=%s
                """,
                [int(tenant_id), int(accounting_patient_id)],
            )
            row = cursor.fetchone()
    return str(row[0]) if row else None
