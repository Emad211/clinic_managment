"""Public structured-record service facade.

The complete aggregate implementation lives in
:mod:`clinical._patient_record_service_core`.  This facade keeps the established
import surface while enforcing one additional safety boundary for standalone
laboratory entries: whenever ``test_key`` identifies a catalog test, the stored
name, unit and reference range are copied exclusively from the tenant's active
server catalog.  Client-supplied display metadata is ignored.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from clinical import _patient_record_service_core as _core
from clinical._patient_record_service_core import *  # noqa: F401,F403


def add_lab_result(
    *,
    tenant_id: int,
    patient_link_id: int,
    test_key: Optional[str] = None,
    test_name: Optional[str] = None,
    value: Optional[float] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    taken_at: Optional[datetime] = None,
    notes: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
):
    """Create a standalone result with authoritative catalog snapshots.

    Free-text tests may supply their own name/unit/reference range.  Catalog
    tests may not override any of those fields: this prevents a modified client
    from making an HbA1c result look as though it used another unit or reference
    interval while preserving the historical snapshot semantics of lab rows.
    """
    normalized_key = _core._clean(test_key)
    if normalized_key:
        _core._set_scope(tenant_id)
        try:
            catalog = _core.LabTestCatalog.objects.get(
                tenant_id=tenant_id,
                test_key=normalized_key,
                is_active=True,
            )
        except _core.LabTestCatalog.DoesNotExist as exc:
            raise _core.PatientRecordValidationError(
                "آزمایش انتخاب‌شده در کاتالوگ فعال نیست."
            ) from exc

        return _core.add_lab_result(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            test_key=normalized_key,
            test_name=catalog.name_fa,
            value=value,
            unit=catalog.unit,
            ref_low=catalog.ref_low,
            ref_high=catalog.ref_high,
            taken_at=taken_at,
            notes=notes,
            actor_username=actor_username,
            actor_id=actor_id,
        )

    return _core.add_lab_result(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        test_key=None,
        test_name=test_name,
        value=value,
        unit=unit,
        ref_low=ref_low,
        ref_high=ref_high,
        taken_at=taken_at,
        notes=notes,
        actor_username=actor_username,
        actor_id=actor_id,
    )
