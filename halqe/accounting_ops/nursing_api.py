"""Accounting API for shift staff, nursing services and consumables."""
from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Optional

from django.core.exceptions import ImproperlyConfigured
from ninja import Query, Router, Schema
from psycopg import Error as PsycopgError

from accounting_ops.api import AccountingInvoiceDTO
from accounting_ops.nursing_payment_service import (
    close_nursing_invoice,
    settle_nursing_invoice,
    set_nursing_item_payment,
)
from accounting_ops.nursing_service import (
    add_nursing_items,
    get_shift_staff_for_invoice,
    list_active_staff,
    list_consumable_tariffs,
    list_nursing_services,
    set_shift_staff_for_invoice,
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
        "accounting nursing write-side unavailable tenant_id=%s error_type=%s",
        tenant_id,
        type(exc).__name__,
        exc_info=True,
    )
    return 503, error_response(
        "بخش حسابداری هنوز فعال نشده یا پایگاه دادهٔ آن در دسترس نیست.",
        "accounting_unavailable",
    )


class NursingServiceDTO(Schema):
    id: int
    service_name: str
    unit_price: int


class ConsumableTariffDTO(Schema):
    id: int
    name: str
    default_price: int
    category: str


class StaffDTO(Schema):
    id: int
    full_name: str
    staff_type: str


class ShiftStaffDTO(Schema):
    id: int
    work_date: date
    shift: str
    doctor_id: Optional[int] = None
    nurse_id: Optional[int] = None
    doctor_name: Optional[str] = None
    nurse_name: Optional[str] = None
    updated_at: datetime


class ShiftStaffInput(Schema):
    doctor_id: Optional[int] = None
    nurse_id: Optional[int] = None


class NursingServiceInput(Schema):
    service_id: int
    quantity: int = 1


class ConsumableInput(Schema):
    name: str
    category: str = "supply"
    quantity: float
    unit_price: int
    patient_provided: bool = False
    is_exception: bool = False


class NursingItemsInput(Schema):
    services: list[NursingServiceInput] = []
    consumables: list[ConsumableInput] = []
    notes: Optional[str] = None


class PaymentSummaryDTO(Schema):
    invoice_id: int
    total_amount: int
    paid_amount: int
    remaining_amount: int
    all_items_paid: bool
    payment_type: Optional[str] = None


class NursingMutationDTO(Schema):
    invoice_id: int
    pricing_version: str
    injection_ids: list[int]
    consumable_ids: list[int]
    financials: PaymentSummaryDTO


class SettleInput(Schema):
    payment_type: str


class ItemPaymentInput(Schema):
    payment_type: Optional[str] = None
    is_paid: bool = True


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


@router.get(
    "/accounting/nursing/services",
    response={200: list[NursingServiceDTO], 403: ErrorSchema, 503: ErrorSchema},
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_nursing_services(request):
    return _call(
        request,
        lambda: list_nursing_services(tenant_id=request.tenant_id),
    )


@router.get(
    "/accounting/consumables/tariffs",
    response={
        200: list[ConsumableTariffDTO],
        403: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_consumable_tariffs(
    request,
    category: Optional[str] = Query(default=None),
):
    return _call(
        request,
        lambda: list_consumable_tariffs(
            tenant_id=request.tenant_id,
            category=category,
        ),
    )


@router.get(
    "/accounting/staff",
    response={
        200: list[StaffDTO],
        403: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_staff(
    request,
    staff_type: Optional[str] = Query(default=None),
):
    return _call(
        request,
        lambda: list_active_staff(
            tenant_id=request.tenant_id,
            staff_type=staff_type,
        ),
    )


@router.get(
    "/accounting/invoices/{invoice_id}/shift-staff",
    response={
        200: Optional[ShiftStaffDTO],
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_get_shift_staff(request, invoice_id: int):
    return _call(
        request,
        lambda: get_shift_staff_for_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
        ),
    )


@router.put(
    "/accounting/invoices/{invoice_id}/shift-staff",
    response={
        200: ShiftStaffDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_set_shift_staff(
    request,
    invoice_id: int,
    payload: ShiftStaffInput,
):
    ip_address, user_agent = _meta(request)
    return _call(
        request,
        lambda: set_shift_staff_for_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            doctor_id=payload.doctor_id,
            nurse_id=payload.nurse_id,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        ),
    )


@router.post(
    "/accounting/invoices/{invoice_id}/nursing-items",
    response={
        201: NursingMutationDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_add_nursing_items(
    request,
    invoice_id: int,
    payload: NursingItemsInput,
):
    guard = _guard(request)
    if guard:
        return guard
    ip_address, user_agent = _meta(request)
    try:
        result = add_nursing_items(
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
    "/accounting/invoices/{invoice_id}/nursing/settle-all",
    response={
        200: PaymentSummaryDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_settle_nursing_invoice(
    request,
    invoice_id: int,
    payload: SettleInput,
):
    ip_address, user_agent = _meta(request)
    return _call(
        request,
        lambda: settle_nursing_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            payment_type=payload.payment_type,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        ),
    )


@router.post(
    "/accounting/invoices/{invoice_id}/nursing/items/{item_type}/{item_id}/payment",
    response={
        200: PaymentSummaryDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_set_nursing_item_payment(
    request,
    invoice_id: int,
    item_type: str,
    item_id: int,
    payload: ItemPaymentInput,
):
    ip_address, user_agent = _meta(request)
    return _call(
        request,
        lambda: set_nursing_item_payment(
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
    "/accounting/invoices/{invoice_id}/nursing/close",
    response={
        200: AccountingInvoiceDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting-nursing"],
)
def accounting_close_nursing_invoice(request, invoice_id: int):
    ip_address, user_agent = _meta(request)
    return _call(
        request,
        lambda: close_nursing_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        ),
    )
