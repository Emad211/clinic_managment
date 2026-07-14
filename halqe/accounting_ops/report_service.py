"""Validated read service for accounting management reports."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from django.utils import timezone

from accounting_ops.service import AccountingValidationError
from accounting_port.reports import AccountingReportsRepository


_ALLOWED_INVOICE_STATUS = frozenset({"open", "closed"})
_ALLOWED_SERVICE_TYPES = frozenset({"visit", "nursing", "procedure", "consumable"})
_MAX_RANGE_DAYS = 366


def _date(value: Any, *, label: str) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise AccountingValidationError(
            f"{label} باید به شکل YYYY-MM-DD باشد.", "invalid_report_date"
        ) from exc


def normalize_report_range(
    *, date_from: Any = None, date_to: Any = None, default_days: int = 7
) -> tuple[date, date]:
    end = _date(date_to, label="تاریخ پایان") or timezone.localdate()
    start = _date(date_from, label="تاریخ شروع") or (
        end - timedelta(days=max(default_days, 1) - 1)
    )
    if start > end:
        start, end = end, start
    if (end - start).days + 1 > _MAX_RANGE_DAYS:
        raise AccountingValidationError(
            "بازه گزارش نمی‌تواند بیش از ۳۶۶ روز باشد.", "report_range_too_large"
        )
    return start, end


def _limit(value: Any, *, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AccountingValidationError("تعداد ردیف نامعتبر است.", "invalid_limit") from exc
    if result <= 0 or result > maximum:
        raise AccountingValidationError(
            f"تعداد ردیف باید بین ۱ و {maximum} باشد.", "invalid_limit"
        )
    return result


def get_report_overview(
    *, tenant_id: int, date_from: Any = None, date_to: Any = None
) -> dict[str, Any]:
    start, end = normalize_report_range(date_from=date_from, date_to=date_to)
    return AccountingReportsRepository.overview_only(
        tenant_id=tenant_id, date_from=start, date_to=end
    )


def get_invoice_report(
    *,
    tenant_id: int,
    date_from: Any = None,
    date_to: Any = None,
    status: Optional[str] = None,
    insurance_type: Optional[str] = None,
    reception_user: Optional[str] = None,
    limit: Any = 200,
) -> dict[str, Any]:
    start, end = normalize_report_range(date_from=date_from, date_to=date_to)
    normalized_status = (status or "").strip().lower() or None
    if normalized_status and normalized_status not in _ALLOWED_INVOICE_STATUS:
        raise AccountingValidationError(
            "وضعیت فاکتور باید open یا closed باشد.", "invalid_invoice_status"
        )
    return AccountingReportsRepository.invoices_only(
        tenant_id=tenant_id,
        date_from=start,
        date_to=end,
        filters={
            "status": normalized_status,
            "insurance_type": (insurance_type or "").strip() or None,
            "reception_user": (reception_user or "").strip() or None,
        },
        limit=_limit(limit, maximum=1000),
    )


def get_service_report(
    *,
    tenant_id: int,
    date_from: Any = None,
    date_to: Any = None,
    service_type: Optional[str] = None,
    shift: Optional[str] = None,
    staff_id: Any = None,
    limit: Any = 300,
) -> dict[str, Any]:
    start, end = normalize_report_range(date_from=date_from, date_to=date_to)
    normalized_type = (service_type or "").strip().lower() or None
    if normalized_type and normalized_type not in _ALLOWED_SERVICE_TYPES:
        raise AccountingValidationError(
            "نوع خدمت نامعتبر است.", "invalid_service_type"
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
    return AccountingReportsRepository.services_only(
        tenant_id=tenant_id,
        date_from=start,
        date_to=end,
        filters={
            "service_type": normalized_type,
            "shift": (shift or "").strip() or None,
            "staff_id": normalized_staff,
        },
        limit=_limit(limit, maximum=1500),
    )
