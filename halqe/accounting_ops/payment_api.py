"""Payment endpoints for the accounting bounded context.

The legacy accounting application records settlement per invoice item and refuses
closing an invoice while any item is unpaid.  These endpoints preserve that
contract for the first migrated item family (visits).
"""
from __future__ import annotations

import logging
from typing import Optional

from django.core.exceptions import ImproperlyConfigured
from ninja import Router, Schema
from psycopg import Error as PsycopgError

from accounting_ops.service import (
    AccountingCommandError,
    get_invoice_financials,
    set_item_payment,
    settle_all_invoice,
)
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


def _request_meta(request) -> tuple[Optional[str], Optional[str]]:
    return (
        request.META.get("REMOTE_ADDR"),
        request.META.get("HTTP_USER_AGENT"),
    )


def _command_error(exc: AccountingCommandError):
    return exc.status, error_response(str(exc), exc.code)


def _unavailable(exc: Exception, *, tenant_id: int):
    logger.error(
        "accounting payment write-side unavailable tenant_id=%s error_type=%s",
        tenant_id,
        type(exc).__name__,
        exc_info=True,
    )
    return 503, error_response(
        "بخش حسابداری هنوز فعال نشده یا پایگاه دادهٔ آن در دسترس نیست.",
        "accounting_unavailable",
    )


class PaymentSummaryDTO(Schema):
    invoice_id: int
    total_amount: int
    paid_amount: int
    remaining_amount: int
    all_items_paid: bool
    payment_type: Optional[str] = None


class ItemPaymentInput(Schema):
    payment_type: Optional[str] = None
    is_paid: bool = True


class SettleAllInput(Schema):
    payment_type: str


@router.get(
    "/accounting/invoices/{invoice_id}/financials",
    response={
        200: PaymentSummaryDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-payments"],
)
def accounting_invoice_financials(request, invoice_id: int):
    guard = _guard(request)
    if guard:
        return guard
    try:
        return get_invoice_financials(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
        )
    except AccountingCommandError as exc:
        return _command_error(exc)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _unavailable(exc, tenant_id=request.tenant_id)


@router.post(
    "/accounting/invoices/{invoice_id}/items/{item_type}/{item_id}/payment",
    response={
        200: PaymentSummaryDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-payments"],
)
def accounting_set_item_payment(
    request,
    invoice_id: int,
    item_type: str,
    item_id: int,
    payload: ItemPaymentInput,
):
    guard = _guard(request)
    if guard:
        return guard
    ip_address, user_agent = _request_meta(request)
    try:
        return set_item_payment(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            item_type=item_type,
            item_id=item_id,
            payment_type=payload.payment_type,
            is_paid=payload.is_paid,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except AccountingCommandError as exc:
        return _command_error(exc)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _unavailable(exc, tenant_id=request.tenant_id)


@router.post(
    "/accounting/invoices/{invoice_id}/settle-all",
    response={
        200: PaymentSummaryDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-payments"],
)
def accounting_settle_all(request, invoice_id: int, payload: SettleAllInput):
    guard = _guard(request)
    if guard:
        return guard
    ip_address, user_agent = _request_meta(request)
    try:
        return settle_all_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            payment_type=payload.payment_type,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except AccountingCommandError as exc:
        return _command_error(exc)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _unavailable(exc, tenant_id=request.tenant_id)
