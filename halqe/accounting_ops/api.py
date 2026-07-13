"""Accounting/reception API — first migration slice from ``webapp``.

All endpoints are authenticated and tenant-scoped. Only accounting-capable
roles may use them. Writes go through a separate PostgreSQL accounting role;
the normal clinical connection remains physically read-only on ``accounting.*``.
"""
from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Optional
from uuid import UUID

from ninja import Query, Router, Schema
from django.core.exceptions import ImproperlyConfigured
from psycopg import Error as PsycopgError

from accounting_ops.service import (
    AccountingCommandError,
    close_invoice,
    list_open_invoices,
    list_visit_tariffs,
    open_visit_invoice,
    search_patients,
)
from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response


logger = logging.getLogger(__name__)

router = Router()
_ACCOUNTING_ROLES = frozenset({"admin", "manager", "reception"})


def _assert_accounting_access(request):
    role = getattr(request.auth, "role", "staff")
    if role not in _ACCOUNTING_ROLES:
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


def _accounting_unavailable(exc: Exception, *, tenant_id: int):
    # Do not put request bodies, patient identifiers or DB credentials in logs.
    logger.error(
        "accounting write-side unavailable tenant_id=%s error_type=%s",
        tenant_id,
        type(exc).__name__,
        exc_info=True,
    )
    return 503, error_response(
        "بخش حسابداری هنوز فعال نشده یا پایگاه دادهٔ آن در دسترس نیست.",
        "accounting_unavailable",
    )


class AccountingPatientInput(Schema):
    name: str
    family_name: str
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    birthdate: Optional[date] = None
    gender: Optional[str] = None
    insurance_expiry: Optional[date] = None
    address: Optional[str] = None
    is_foreign: bool = False


class AccountingPatientDTO(Schema):
    id: int
    uuid: UUID
    name: str
    family_name: str
    full_name: str
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    birthdate: Optional[date] = None
    gender: Optional[str] = None
    insurance_type: Optional[str] = None
    insurance_expiry: Optional[date] = None
    address: Optional[str] = None
    is_foreign: bool


class OpenVisitInvoiceInput(Schema):
    patient: AccountingPatientInput
    insurance_type: str
    supplementary_insurance: Optional[str] = None
    doctor_id: Optional[int] = None
    work_date: Optional[date] = None
    shift: Optional[str] = None
    notes: Optional[str] = None


class AccountingInvoiceDTO(Schema):
    id: int
    tenant_id: int
    patient_id: int
    patient_uuid: UUID
    patient_full_name: str
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    status: str
    pricing_version: str
    insurance_type: Optional[str] = None
    supplementary_insurance: Optional[str] = None
    total_amount: int
    work_date: Optional[date] = None
    shift: Optional[str] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    opened_by: Optional[str] = None
    opened_by_name: Optional[str] = None
    closed_by: Optional[str] = None
    closed_by_name: Optional[str] = None
    visit_id: Optional[int] = None
    visit_price: Optional[int] = None


class OpenInvoicesResponse(Schema):
    items: list[AccountingInvoiceDTO]
    total: int
    limit: int
    offset: int


class VisitTariffDTO(Schema):
    id: int
    insurance_type: str
    tariff_price: int
    is_supplementary: bool
    is_base_tariff: bool
    nursing_covers: bool
    nursing_tariff: int


@router.get(
    "/accounting/patients/search",
    response={200: list[AccountingPatientDTO], 403: ErrorSchema, 503: ErrorSchema},
    auth=_jwt_auth,
    tags=["accounting"],
)
def accounting_patient_search(
    request,
    q: str = Query(default=""),
    limit: int = Query(default=30, ge=1, le=100),
):
    guard = _assert_accounting_access(request)
    if guard:
        return guard
    try:
        return search_patients(
            tenant_id=request.tenant_id,
            query=q,
            limit=limit,
        )
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _accounting_unavailable(exc, tenant_id=request.tenant_id)


@router.get(
    "/accounting/tariffs/visits",
    response={200: list[VisitTariffDTO], 403: ErrorSchema, 503: ErrorSchema},
    auth=_jwt_auth,
    tags=["accounting"],
)
def accounting_visit_tariffs(request):
    guard = _assert_accounting_access(request)
    if guard:
        return guard
    try:
        return list_visit_tariffs(tenant_id=request.tenant_id)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _accounting_unavailable(exc, tenant_id=request.tenant_id)


@router.get(
    "/accounting/invoices/open",
    response={200: OpenInvoicesResponse, 403: ErrorSchema, 503: ErrorSchema},
    auth=_jwt_auth,
    tags=["accounting"],
)
def accounting_open_invoices(
    request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    guard = _assert_accounting_access(request)
    if guard:
        return guard
    try:
        return list_open_invoices(
            tenant_id=request.tenant_id,
            limit=limit,
            offset=offset,
        )
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _accounting_unavailable(exc, tenant_id=request.tenant_id)


@router.post(
    "/accounting/invoices/visit",
    response={
        201: AccountingInvoiceDTO,
        403: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting"],
)
def accounting_create_visit_invoice(request, payload: OpenVisitInvoiceInput):
    """Atomically register/update the patient and open a visit invoice."""
    guard = _assert_accounting_access(request)
    if guard:
        return guard

    ip_address, user_agent = _request_meta(request)
    try:
        result = open_visit_invoice(
            tenant_id=request.tenant_id,
            payload=payload.model_dump(),
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except AccountingCommandError as exc:
        return _command_error(exc)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _accounting_unavailable(exc, tenant_id=request.tenant_id)
    return 201, result


@router.post(
    "/accounting/invoices/{invoice_id}/close",
    response={
        200: AccountingInvoiceDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        503: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["accounting"],
)
def accounting_close_invoice(request, invoice_id: int):
    guard = _assert_accounting_access(request)
    if guard:
        return guard

    ip_address, user_agent = _request_meta(request)
    try:
        return close_invoice(
            tenant_id=request.tenant_id,
            invoice_id=invoice_id,
            actor=request.auth,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except AccountingCommandError as exc:
        return _command_error(exc)
    except (ImproperlyConfigured, PsycopgError) as exc:
        return _accounting_unavailable(exc, tenant_id=request.tenant_id)
