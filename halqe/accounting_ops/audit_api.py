from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Optional

from django.db import DatabaseError
from ninja import Router, Schema

from accounting_ops.audit_service import get_accounting_audit_logs
from accounting_ops.service import AccountingCommandError
from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response


logger = logging.getLogger(__name__)
router = Router()
_MANAGER_ROLES = frozenset({"admin", "manager"})


def _call(request, callback):
    if getattr(request.auth, "role", "staff") not in _MANAGER_ROLES:
        return 403, error_response(
            "بازبینی رویدادهای حسابداری فقط برای مدیر یا ادمین مجاز است.",
            "forbidden",
        )
    try:
        return callback()
    except AccountingCommandError as exc:
        return exc.status, error_response(str(exc), exc.code)
    except DatabaseError as exc:
        logger.error(
            "accounting audit unavailable tenant_id=%s error_type=%s",
            request.tenant_id,
            type(exc).__name__,
            exc_info=True,
        )
        return 503, error_response(
            "پایگاه دادهٔ رویدادهای حسابداری در دسترس نیست.",
            "accounting_audit_unavailable",
        )


class AuditUserDTO(Schema):
    user_id: Optional[int] = None
    username: str
    full_name: str


class AuditFilterOptionsDTO(Schema):
    action_types: list[str]
    action_categories: list[str]
    users: list[AuditUserDTO]


class AuditCategorySummaryDTO(Schema):
    action_category: str
    count: int


class AuditRowDTO(Schema):
    id: int
    created_at: datetime
    user_id: Optional[int] = None
    username: str
    user_full_name: str
    action_type: str
    action_category: str
    description: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    target_name: Optional[str] = None
    invoice_id: Optional[int] = None
    patient_id: Optional[int] = None
    patient_name: Optional[str] = None
    amount: int
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditSearchDTO(Schema):
    date_from: date
    date_to: date
    page: int
    page_size: int
    total: int
    total_pages: int
    rows: list[AuditRowDTO]
    category_summary: list[AuditCategorySummaryDTO]
    filter_options: AuditFilterOptionsDTO


_AUDIT_ERRORS = {
    403: ErrorSchema,
    422: ErrorSchema,
    503: ErrorSchema,
}


@router.get(
    "/accounting/audit/logs",
    response={200: AuditSearchDTO} | _AUDIT_ERRORS,
    auth=_jwt_auth,
    tags=["accounting-audit"],
)
def accounting_audit_logs(
    request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = 1,
    page_size: int = 50,
    user_id: Optional[int] = None,
    action_type: Optional[str] = None,
    action_category: Optional[str] = None,
    invoice_id: Optional[int] = None,
    patient_id: Optional[int] = None,
    search_text: Optional[str] = None,
):
    return _call(
        request,
        lambda: get_accounting_audit_logs(
            tenant_id=request.tenant_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
            user_id=user_id,
            action_type=action_type,
            action_category=action_category,
            invoice_id=invoice_id,
            patient_id=patient_id,
            search_text=search_text,
        ),
    )
