"""Authenticated accounting invoice workbench API."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from django.core.exceptions import ImproperlyConfigured
from ninja import Router, Schema
from psycopg import Error as PsycopgError

from accounting_ops.api import AccountingInvoiceDTO
from accounting_ops.invoice_workbench_service import (
    add_visit_to_invoice,
    delete_invoice_item,
    get_invoice_detail,
)
from accounting_ops.payment_api import PaymentSummaryDTO
from accounting_ops.service import AccountingCommandError
from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response


logger = logging.getLogger(__name__)
router = Router()
_ACCOUNTING_ROLES = frozenset({"admin", "manager", "reception"})


def _guard(request):
    if getattr(request.auth, "role", "staff") not in _ACCOUNTING_ROLES:
        return 403, error_response(
            "دسترسی به حسابداری فقط برای پذیرش یا مدیر مجاز است.",
            "forbidden",
        )
    return None


def _meta(request) -> tuple[Optional[str], Optional[str]]:
    return request.META.get("REMOTE_ADDR"), request.META.get("HTTP_USER_AGENT")


def _command_error(exc: AccountingCommandError):
    return exc.status, error_response(str(exc), exc.code)


def _unavailable(exc: Exception, *, tenant_id: int):
    logger.error(
        "accounting invoice workbench unavailable tenant_id=%s error_type=%s",
        tenant_id,
        type(exc).__name__,
        exc_info=True,
    )
    return 503, error_response(
        "بخش حسابداری هنوز فعال نشده یا پایگاه دادهٔ آن در دسترس نیست.",
        "accounting_unavailable",
    )


def _call(request, callback):
    guard = _guard(request)
    if guard:
        return guard
    try:
        return callback()
    except AccountingCommandError as exc:
        return _command_error(exc)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _unavailable(exc, tenant_id=request.tenant_id)


class InvoiceWorkbenchItemDTO(Schema):
    item_type: str
    item_id: int
    description: str
    quantity: float
    recorded_amount: int
    patient_amount: int
    insurance_amount: int
    covered_by_insurance: bool
    performer_type: Optional[str] = None
    performer_id: Optional[int] = None
    performer_name: Optional[str] = None
    occurred_at: datetime
    notes: Optional[str] = None
    payment_type: Optional[str] = None
    is_paid: bool
    payment_updated_at: Optional[datetime] = None


class InvoiceWorkbenchDetailDTO(Schema):
    invoice: AccountingInvoiceDTO
    items: list[InvoiceWorkbenchItemDTO]
    financials: PaymentSummaryDTO


class AddVisitInput(Schema):
    notes: Optional[str] = None


class DeleteItemOut(Schema):
    deleted: bool
    item_type: str
    item_id: int
    detail: InvoiceWorkbenchDetailDTO


@router.get(
    "/accounting/invoices/{invoice_id}/detail",
    response={
        200: InvoiceWorkbenchDetailDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-invoices"],
)
def accounting_invoice_detail(request, invoice_id: int):
    return _call(
        request,
        lambda: get_invoice_detail(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
        ),
    )


@router.post(
    "/accounting/invoices/{invoice_id}/visits",
    response={
        201: InvoiceWorkbenchDetailDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-invoices"],
)
def accounting_add_visit_to_invoice(
    request,
    invoice_id: int,
    payload: AddVisitInput,
):
    guard = _guard(request)
    if guard:
        return guard
    ip_address, user_agent = _meta(request)
    try:
        result = add_visit_to_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            notes=payload.notes,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return 201, result
    except AccountingCommandError as exc:
        return _command_error(exc)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _unavailable(exc, tenant_id=request.tenant_id)


@router.delete(
    "/accounting/invoices/{invoice_id}/items/{item_type}/{item_id}",
    response={
        200: DeleteItemOut,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-invoices"],
)
def accounting_delete_invoice_item(
    request,
    invoice_id: int,
    item_type: str,
    item_id: int,
):
    ip_address, user_agent = _meta(request)
    return _call(
        request,
        lambda: delete_invoice_item(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            item_type=item_type,
            item_id=item_id,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        ),
    )
