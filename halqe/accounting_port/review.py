"""Read-only accounting identity lookups for migration review gates.

Clinical verification may prove that imported clinical links still resolve to
the pseudonymous UUID used by the patient cockpit. All accounting access stays
inside this SELECT-only port; no demographic value other than UUID is returned.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from django.db import connections, transaction


def get_accounting_patient_uuids_for_review(
    *,
    accounting_patient_ids: Iterable[int],
    tenant_id: int,
) -> dict[int, str]:
    """Return tenant-scoped ``patient_id -> UUID`` for positive requested IDs."""
    try:
        normalized_tenant = int(tenant_id)
    except (TypeError, ValueError):
        return {}
    if normalized_tenant <= 0:
        return {}

    normalized_ids: set[int] = set()
    for value in accounting_patient_ids:
        try:
            patient_id = int(value)
        except (TypeError, ValueError):
            continue
        if patient_id > 0:
            normalized_ids.add(patient_id)
    if not normalized_ids:
        return {}

    with transaction.atomic(using="accounting_read"):
        with connections["accounting_read"].cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                [str(normalized_tenant)],
            )
            cursor.execute(
                """
                SELECT id, uuid
                FROM accounting.patients
                WHERE tenant_id=%s AND id=ANY(%s)
                ORDER BY id
                """,
                [normalized_tenant, sorted(normalized_ids)],
            )
            return {int(row[0]): str(row[1]) for row in cursor.fetchall()}


def get_accounting_patient_uuid_for_review(
    *, accounting_patient_id: int, tenant_id: int
) -> Optional[str]:
    """Return one accounting UUID through the same batch-safe port."""
    rows = get_accounting_patient_uuids_for_review(
        accounting_patient_ids=[accounting_patient_id],
        tenant_id=tenant_id,
    )
    try:
        key = int(accounting_patient_id)
    except (TypeError, ValueError):
        return None
    return rows.get(key)
