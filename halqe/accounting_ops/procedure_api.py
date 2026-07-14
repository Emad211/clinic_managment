"""Accounting API for procedure pricing, payments and close."""
from __future__ import annotations

import logging
from typing import Optional

from django.core.exceptions import ImproperlyConfigured
from ninja import Router, Schema
from pydantic import Field
from psycopg import Error as PsycopgError

from accounting_ops.api import AccountingInvoiceDTO
from accounting_ops.procedure_payment_service import (
    close_procedure_invoice,
    set_procedure_item_payment,
    settle_procedure_invoice,
)
from accounting_ops.procedure_service import (
    add_procedure_items,
    list_procedure_tariffs,
)
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
        "accounting procedure write-side unavailable tenant_id=%s error_type=%s",
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


class ProcedureTariffDTO(Schema):
    id: int
    name: str
    unit_price: int


class ProcedureInput(Schema):
    tariff_id: Optional[int] = None
    name: Optional[str] = None
    unit_price: Optional[int] = None
    quantity: int = 1
    performer_type: Optional[str] = None


class ProcedureItemsInput(Schema):
    procedures: list[ProcedureInput] = Field(default_factory=list)
    notes: Optional[str] = None


class PaymentSummaryDTO(Schema):
    invoice_id: int
    total_amount: int
    paid_amount: int
    remaining_amount: int
    all_items_paid: bool
    payment_type: Optional[str] = None


class ProcedureMutationDTO(Schema):
    invoice_id: int
    pricing_version: str
    procedure_ids: list[int]
    financials: PaymentSummaryDTO


class SettleInput(Schema):
    payment_type: str


class ItemPaymentInput(Schema):
    payment_type: Optional[str] = None
    is_paid: bool = True


@router.get(
    "/accounting/procedures/tariffs",
    response={200: list[ProcedureTariffDTO], 403: ErrorSchema, 503: ErrorSchema},
    auth=_jwt_auth,
    tags=["accounting-procedures"],
)
def accounting_procedure_tariffs(request):
    return _call(
        request,
        lambda: list_procedure_tariffs(tenant_id=request.tenant_id),
    )


@router.post(
    "/accounting/invoices/{invoice_id}/procedure-items",
    response={
        201: ProcedureMutationDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-procedures"],
)
def accounting_add_procedure_items(
    request,
    invoice_id: int,
    payload: ProcedureItemsInput,
):
    guard = _guard(request)
    if guard:
        return guard
    ip_address, user_agent = _meta(request)
    try:
        result = add_procedure_items(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            payload=payload.model_dump(),
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return 201, result
    except AccountingCommandError as exc:
        return _command_error(exc)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _unavailable(exc, tenant_id=request.tenant_id)


@router.post(
    "/accounting/invoices/{invoice_id}/procedure/settle-all",
    response={
        200: PaymentSummaryDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-procedures"],
)
def accounting_settle_procedure_invoice(
    request,
    invoice_id: int,
    payload: SettleInput,
):
    ip_address, user_agent = _meta(request)
    return _call(
        request,
        lambda: settle_procedure_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            payment_type=payload.payment_type,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        ),
    )


@router.post(
    "/accounting/invoices/{invoice_id}/procedure/items/{item_type}/{item_id}/payment",
    response={
        200: PaymentSummaryDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-procedures"],
)
def accounting_set_procedure_item_payment(
    request,
    invoice_id: int,
    item_type: str,
    item_id: int,
    payload: ItemPaymentInput,
):
    ip_address, user_agent = _meta(request)
    return _call(
        request,
        lambda: set_procedure_item_payment(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            item_type=item_type,
            item_id=item_id,
            payment_type=payload.payment_type,
            is_paid=payload.is_paid,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        ),
    )


@router.post(
    "/accounting/invoices/{invoice_id}/procedure/close",
    response={
        200: AccountingInvoiceDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-procedures"],
)
def accounting_close_procedure_invoice(request, invoice_id: int):
    ip_address, user_agent = _meta(request)
    return _call(
        request,
        lambda: close_procedure_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        ),
    )
