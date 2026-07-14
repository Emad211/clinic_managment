"""Read-only accounting identity lookups for record migration and review.

All accounting access stays inside this SELECT-only port. Review functions return
only UUID; import resolution returns only internal patient IDs and conflict
flags. No name, phone, national ID or other demographic value leaves the port.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

from django.db import connections, transaction


@dataclass(frozen=True)
class AccountingPatientResolution:
    by_accounting_id: Optional[int]
    by_national_id: Optional[int]
    duplicate_national_id: bool = False

    @property
    def conflict(self) -> bool:
        return (
            self.by_accounting_id is not None
            and self.by_national_id is not None
            and self.by_accounting_id != self.by_national_id
        )

    @property
    def patient_id(self) -> Optional[int]:
        if self.conflict or self.duplicate_national_id:
            return None
        return self.by_national_id or self.by_accounting_id


def _normalized_tenant(tenant_id: int) -> int | None:
    try:
        value = int(tenant_id)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def resolve_accounting_patient_for_record_import(
    *,
    tenant_id: int,
    accounting_patient_id: object = None,
    national_id: object = None,
) -> AccountingPatientResolution:
    """Resolve exact identity keys without returning the demographic keys themselves."""
    tenant = _normalized_tenant(tenant_id)
    if tenant is None:
        return AccountingPatientResolution(None, None)

    try:
        numeric_id = int(accounting_patient_id) if accounting_patient_id is not None else 0
    except (TypeError, ValueError):
        numeric_id = 0
    national = str(national_id).strip() if national_id is not None else ""

    by_id: Optional[int] = None
    by_national: Optional[int] = None
    duplicate = False
    with transaction.atomic(using="accounting_read"):
        with connections["accounting_read"].cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                [str(tenant)],
            )
            if numeric_id > 0:
                cursor.execute(
                    """
                    SELECT id FROM accounting.patients
                    WHERE tenant_id=%s AND id=%s
                    """,
                    [tenant, numeric_id],
                )
                row = cursor.fetchone()
                by_id = int(row[0]) if row else None
            if national:
                cursor.execute(
                    """
                    SELECT id FROM accounting.patients
                    WHERE tenant_id=%s AND national_id=%s
                    ORDER BY id LIMIT 2
                    """,
                    [tenant, national],
                )
                rows = cursor.fetchall()
                duplicate = len(rows) > 1
                by_national = int(rows[0][0]) if len(rows) == 1 else None
    return AccountingPatientResolution(
        by_accounting_id=by_id,
        by_national_id=by_national,
        duplicate_national_id=duplicate,
    )


def get_accounting_patient_uuids_for_review(
    *,
    accounting_patient_ids: Iterable[int],
    tenant_id: int,
) -> dict[int, str]:
    """Return tenant-scoped ``patient_id -> UUID`` for positive requested IDs."""
    tenant = _normalized_tenant(tenant_id)
    if tenant is None:
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
                [str(tenant)],
            )
            cursor.execute(
                """
                SELECT id, uuid
                FROM accounting.patients
                WHERE tenant_id=%s AND id=ANY(%s::bigint[])
                ORDER BY id
                """,
                [tenant, sorted(normalized_ids)],
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
