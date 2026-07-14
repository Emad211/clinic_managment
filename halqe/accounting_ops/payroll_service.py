"""Validation layer for the legacy-faithful payroll preview."""
from __future__ import annotations

from typing import Any, Optional

from accounting_ops.report_service import normalize_report_range
from accounting_ops.service import AccountingValidationError
from accounting_port.payroll import AccountingPayrollRepository


_STAFF_TYPES = frozenset({"doctor", "nurse"})
_SHIFTS = frozenset({"morning", "evening", "night"})


def calculate_payroll_report(
    *,
    tenant_id: int,
    date_from: Any = None,
    date_to: Any = None,
    staff_id: Any = None,
    staff_type: Optional[str] = None,
    shift: Optional[str] = None,
) -> dict[str, Any]:
    start, end = normalize_report_range(
        date_from=date_from, date_to=date_to, default_days=30
    )
    normalized_type = (staff_type or "").strip().lower() or None
    if normalized_type and normalized_type not in _STAFF_TYPES:
        raise AccountingValidationError(
            "نوع کادر باید doctor یا nurse باشد.", "invalid_staff_type"
        )
    normalized_shift = (shift or "").strip().lower() or None
    if normalized_shift and normalized_shift not in _SHIFTS:
        raise AccountingValidationError(
            "شیفت باید morning، evening یا night باشد.", "invalid_shift"
        )
    normalized_staff = None
    if staff_id not in (None, ""):
        try:
            normalized_staff = int(staff_id)
        except (TypeError, ValueError) as exc:
            raise AccountingValidationError(
                "شناسه کادر درمان نامعتبر است.", "invalid_staff_id"
            ) from exc
        if normalized_staff <= 0:
            raise AccountingValidationError(
                "شناسه کادر درمان نامعتبر است.", "invalid_staff_id"
            )

    return AccountingPayrollRepository.calculate_read_only(
        tenant_id=tenant_id,
        date_from=start,
        date_to=end,
        staff_id=normalized_staff,
        staff_type=normalized_type,
        shift=normalized_shift,
    )
