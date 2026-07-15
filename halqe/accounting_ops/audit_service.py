from __future__ import annotations

from typing import Any

from accounting_ops.report_service import normalize_report_range
from accounting_ops.service import AccountingValidationError
from accounting_port.audit import AccountingAuditRepository


def _positive_int(value: Any, *, label: str, code: str, required: bool = False):
    if value in (None, "") and not required:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AccountingValidationError(f"{label} نامعتبر است.", code) from exc
    if result <= 0:
        raise AccountingValidationError(f"{label} نامعتبر است.", code)
    return result


def _short(value: Any, *, label: str, code: str, maximum: int):
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > maximum:
        raise AccountingValidationError(
            f"{label} نمی‌تواند بیش از {maximum} نویسه باشد.", code
        )
    return text


def get_accounting_audit_logs(
    *,
    tenant_id: int,
    date_from: Any = None,
    date_to: Any = None,
    page: Any = 1,
    page_size: Any = 50,
    user_id: Any = None,
    action_type: Any = None,
    action_category: Any = None,
    invoice_id: Any = None,
    patient_id: Any = None,
    search_text: Any = None,
) -> dict[str, Any]:
    start, end = normalize_report_range(
        date_from=date_from,
        date_to=date_to,
        default_days=30,
    )
    normalized_page = _positive_int(
        page, label="شماره صفحه", code="invalid_audit_page", required=True
    )
    normalized_size = _positive_int(
        page_size, label="تعداد ردیف صفحه", code="invalid_audit_page_size", required=True
    )
    if normalized_size > 100:
        raise AccountingValidationError(
            "تعداد ردیف هر صفحه نمی‌تواند بیش از ۱۰۰ باشد.",
            "invalid_audit_page_size",
        )
    return AccountingAuditRepository.search(
        tenant_id=tenant_id,
        date_from=start,
        date_to=end,
        page=normalized_page,
        page_size=normalized_size,
        filters={
            "user_id": _positive_int(
                user_id, label="شناسه کاربر", code="invalid_audit_user"
            ),
            "action_type": _short(
                action_type,
                label="نوع عملیات",
                code="invalid_audit_action_type",
                maximum=80,
            ),
            "action_category": _short(
                action_category,
                label="دسته عملیات",
                code="invalid_audit_category",
                maximum=80,
            ),
            "invoice_id": _positive_int(
                invoice_id, label="شناسه فاکتور", code="invalid_audit_invoice"
            ),
            "patient_id": _positive_int(
                patient_id, label="شناسه بیمار", code="invalid_audit_patient"
            ),
            "search_text": _short(
                search_text,
                label="متن جست‌وجو",
                code="invalid_audit_search",
                maximum=200,
            ),
        },
    )
