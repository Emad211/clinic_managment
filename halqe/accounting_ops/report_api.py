"""Manager-only, read-only accounting reporting API."""
from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Optional

from django.db import DatabaseError
from ninja import Router, Schema

from accounting_ops.report_service import (
    get_invoice_report,
    get_report_overview,
    get_service_report,
)
from accounting_ops.service import AccountingCommandError
from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response


logger = logging.getLogger(__name__)
router = Router()
_MANAGER_ROLES = frozenset({"admin", "manager"})


def _guard(request):
    if getattr(request.auth, "role", "staff") not in _MANAGER_ROLES:
        return 403, error_response(
            "گزارش‌های مالی فقط برای مدیر یا ادمین مجاز است.", "forbidden"
        )
    return None


def _call(request, callback):
    guard = _guard(request)
    if guard:
        return guard
    try:
        return callback()
    except AccountingCommandError as exc:
        return exc.status, error_response(str(exc), exc.code)
    except DatabaseError as exc:
        logger.error(
            "accounting report unavailable tenant_id=%s error_type=%s",
            request.tenant_id,
            type(exc).__name__,
            exc_info=True,
        )
        return 503, error_response(
            "پایگاه دادهٔ گزارش حسابداری در دسترس نیست.",
            "accounting_report_unavailable",
        )


class InvoiceSummaryDTO(Schema):
    total: int
    open: int
    closed: int
    unique_patients: int
    total_liability: int


class RevenueItemDTO(Schema):
    count: int
    amount: int


class RevenueDTO(Schema):
    visit: RevenueItemDTO
    nursing: RevenueItemDTO
    procedure: RevenueItemDTO
    operating_revenue: int


class ConsumableSummaryDTO(Schema):
    count: int
    amount: int


class PaymentSummaryDTO(Schema):
    items: int
    paid_items: int
    unpaid_items: int


class DailyFinancialDTO(Schema):
    day: date
    visits: int
    nursing: int
    procedures: int
    consumables: int
    operating_revenue: int
    consumables_cost: int


class ReceptionUserDTO(Schema):
    username: str
    full_name: str


class ReportFiltersDTO(Schema):
    insurances: list[str]
    reception_users: list[ReceptionUserDTO]


class InvoiceRowDTO(Schema):
    id: int
    work_date: Optional[date] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    status: str
    total_amount: int
    insurance_type: Optional[str] = None
    supplementary_insurance: Optional[str] = None
    opened_by: Optional[str] = None
    opened_by_name: Optional[str] = None
    closed_by: Optional[str] = None
    closed_by_name: Optional[str] = None
    patient_name: str


class OverviewInvoiceRowDTO(Schema):
    id: int
    work_date: Optional[date] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    status: str
    total_amount: int
    insurance_type: Optional[str] = None
    supplementary_insurance: Optional[str] = None
    opened_by_name: Optional[str] = None
    closed_by_name: Optional[str] = None
    patient_name: str


class AccountingOverviewDTO(Schema):
    date_from: date
    date_to: date
    invoices: InvoiceSummaryDTO
    revenue: RevenueDTO
    consumables: ConsumableSummaryDTO
    payments: PaymentSummaryDTO
    daily: list[DailyFinancialDTO]
    recent_invoices: list[OverviewInvoiceRowDTO]
    filters: ReportFiltersDTO


class InvoiceRowsSummaryDTO(Schema):
    total: int
    open: int
    closed: int
    total_amount: int


class InvoiceReportDTO(Schema):
    date_from: date
    date_to: date
    summary: InvoiceRowsSummaryDTO
    rows: list[InvoiceRowDTO]


class ServiceBucketDTO(Schema):
    count: int
    amount: int


class ServiceRowDTO(Schema):
    service_type: str
    id: int
    invoice_id: Optional[int] = None
    work_date: Optional[date] = None
    occurred_at: datetime
    patient_name: str
    service_name: str
    quantity: float
    amount: int
    patient_amount: int
    insurance_amount: int
    doctor_id: Optional[int] = None
    nurse_id: Optional[int] = None
    staff_name: Optional[str] = None
    performer_type: Optional[str] = None
    shift: Optional[str] = None
    reception_user: Optional[str] = None
    included_in_revenue: bool
    patient_provided: bool
    is_exception: bool


class ServiceReportDTO(Schema):
    date_from: date
    date_to: date
    summary: dict[str, ServiceBucketDTO]
    rows: list[ServiceRowDTO]


_REPORT_ERRORS = {
    403: ErrorSchema,
    422: ErrorSchema,
    503: ErrorSchema,
}


@router.get(
    "/accounting/reports/overview",
    response={200: AccountingOverviewDTO} | _REPORT_ERRORS,
    auth=_jwt_auth,
    tags=["accounting-reports"],
)
def accounting_report_overview(
    request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    return _call(
        request,
        lambda: get_report_overview(
            tenant_id=request.tenant_id,
            date_from=date_from,
            date_to=date_to,
        ),
    )


@router.get(
    "/accounting/reports/invoices",
    response={200: InvoiceReportDTO} | _REPORT_ERRORS,
    auth=_jwt_auth,
    tags=["accounting-reports"],
)
def accounting_report_invoices(
    request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    insurance_type: Optional[str] = None,
    reception_user: Optional[str] = None,
    limit: int = 200,
):
    return _call(
        request,
        lambda: get_invoice_report(
            tenant_id=request.tenant_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            insurance_type=insurance_type,
            reception_user=reception_user,
            limit=limit,
        ),
    )


@router.get(
    "/accounting/reports/services",
    response={200: ServiceReportDTO} | _REPORT_ERRORS,
    auth=_jwt_auth,
    tags=["accounting-reports"],
)
def accounting_report_services(
    request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    service_type: Optional[str] = None,
    shift: Optional[str] = None,
    staff_id: Optional[int] = None,
    limit: int = 300,
):
    return _call(
        request,
        lambda: get_service_report(
            tenant_id=request.tenant_id,
            date_from=date_from,
            date_to=date_to,
            service_type=service_type,
            shift=shift,
            staff_id=staff_id,
            limit=limit,
        ),
    )
