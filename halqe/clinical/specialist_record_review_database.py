"""Database-backed binding checks for clinician migration review packets.

Artifact hashes prove that files did not change after review.  This module proves
that each pseudonymous sample row also names the exact patient imported from the
source ledger and still resolves to the accounting UUID shown in the cockpit
path.  No demographic field is returned or logged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID

from django.db import connection

from accounting_port.review import get_accounting_patient_uuid_for_review
from clinical.models import PatientLink
from platform_core.tenant_context import set_tenant_guc


@dataclass
class ReviewPatientBindingResult:
    passed: bool
    checked_patients: int
    failures: list[str] = field(default_factory=list)

    @property
    def detail(self) -> str:
        if self.passed:
            return (
                f"All {self.checked_patients} selected patients match the import "
                "ledger, clinical enrollment and accounting UUID."
            )
        preview = ", ".join(self.failures[:12])
        suffix = "" if len(self.failures) <= 12 else f" (+{len(self.failures) - 12} more)"
        return f"Patient binding failures: {preview}{suffix}"



def verify_review_patient_bindings(
    *,
    packet: Mapping[str, Any],
    source_id: str,
    tenant_id: int,
) -> ReviewPatientBindingResult:
    """Verify source-row → ledger target → clinical link → accounting UUID."""
    patients = packet.get("patients")
    if not isinstance(patients, list) or not patients:
        return ReviewPatientBindingResult(
            passed=False,
            checked_patients=0,
            failures=["patient-sample-empty"],
        )

    set_tenant_guc(int(tenant_id))
    failures: list[str] = []
    checked = 0
    for index, item in enumerate(patients):
        if not isinstance(item, Mapping):
            failures.append(f"row-{index}:malformed")
            continue
        source_row_id = _positive_int(item.get("source_patient_link_id"))
        target_row_id = _positive_int(item.get("target_patient_link_id"))
        patient_uuid = _canonical_uuid(item.get("patient_uuid"))
        if source_row_id is None or target_row_id is None or patient_uuid is None:
            failures.append(f"row-{index}:invalid-identifiers")
            continue

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT target_table, target_row_id
                FROM clinical.record_import_ledger
                WHERE tenant_id=%s
                  AND source_id=%s
                  AND source_table='patient_links'
                  AND source_row_id=%s
                """,
                [int(tenant_id), source_id, source_row_id],
            )
            ledger = cursor.fetchone()
        if not ledger:
            failures.append(f"source-{source_row_id}:ledger-missing")
            continue
        ledger_table, ledger_target = ledger
        if ledger_table != "clinical.patient_links":
            failures.append(f"source-{source_row_id}:ledger-target-table")
            continue
        if int(ledger_target) != target_row_id:
            failures.append(f"source-{source_row_id}:ledger-target-id")
            continue

        link = PatientLink.objects.filter(
            tenant_id=int(tenant_id),
            id=target_row_id,
            is_active=True,
        ).only("id", "patient_id").first()
        if link is None:
            failures.append(f"source-{source_row_id}:clinical-link-missing")
            continue

        accounting_uuid = get_accounting_patient_uuid_for_review(
            accounting_patient_id=int(link.patient_id),
            tenant_id=int(tenant_id),
        )
        if accounting_uuid != patient_uuid:
            failures.append(f"source-{source_row_id}:accounting-uuid-mismatch")
            continue
        checked += 1

    return ReviewPatientBindingResult(
        passed=not failures and checked == len(patients),
        checked_patients=checked,
        failures=failures,
    )



def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None



def _canonical_uuid(value: Any) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None
