"""Manager-only API for accounting staff, catalogs, insurance and payroll."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Optional

from django.core.exceptions import ImproperlyConfigured
from ninja import Router, Schema
from psycopg import Error as PsycopgError

from accounting_ops.admin_service import (
    delete_exclusion,
    get_accounting_admin_configuration,
    upsert_catalog_item,
    upsert_exclusion,
    upsert_insurance_scheme,
    upsert_payroll_settings,
    upsert_staff,
    upsert_visit_tariff,
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
            "تنظیمات حسابداری فقط برای مدیر یا ادمین مجاز است.", "forbidden"
        )
    return None


def _meta(request) -> tuple[Optional[str], Optional[str]]:
    return request.META.get("REMOTE_ADDR"), request.META.get("HTTP_USER_AGENT")


def _call(request, callback, *, created: bool = False):
    guard = _guard(request)
    if guard:
        return guard
    try:
        result = callback()
        return (201, result) if created else result
    except AccountingCommandError as exc:
        return exc.status, error_response(str(exc), exc.code)
    except (ImproperlyConfigured, PsycopgError) as exc:
        logger.error(
            "accounting admin unavailable tenant_id=%s error_type=%s",
            request.tenant_id,
            type(exc).__name__,
            exc_info=True,
        )
        return 503, error_response(
            "پایگاه دادهٔ تنظیمات حسابداری در دسترس نیست.",
            "accounting_unavailable",
        )


class StaffDTO(Schema):
    id: int
    full_name: str
    staff_type: str
    is_active: bool
    created_at: datetime


class InsuranceSchemeDTO(Schema):
    id: int
    code: str
    name: str
    is_supplementary: bool
    is_base: bool
    is_active: bool
    created_at: datetime


class VisitTariffDTO(Schema):
    id: int
    insurance_type: str
    insurance_scheme_id: Optional[int] = None
    tariff_price: int
    nursing_tariff: int
    nursing_covers: bool
    is_active: bool
    is_supplementary: bool
    is_base_tariff: bool
    created_at: datetime
    updated_at: datetime


class CatalogItemDTO(Schema):
    id: int
    name: str
    price: int
    is_active: bool
    created_at: datetime
    category: Optional[str] = None


class ExclusionDTO(Schema):
    id: int
    insurance_type: str
    nursing_service_id: int
    service_name: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime


class PayrollDTO(Schema):
    id: int
    staff_id: int
    staff_name: Optional[str] = None
    staff_type: Optional[str] = None
    base_morning: int
    base_evening: int
    base_night: int
    visit_fee: int
    injection_percent: float
    procedure_percent: float
    tax_percent: float
    nursing_percent: float
    nurse_procedure_percent: float
    updated_at: datetime


class CatalogGroupsDTO(Schema):
    nursing: list[CatalogItemDTO]
    procedure: list[CatalogItemDTO]
    consumable: list[CatalogItemDTO]


class AdminConfigurationDTO(Schema):
    staff: list[StaffDTO]
    insurance_schemes: list[InsuranceSchemeDTO]
    visit_tariffs: list[VisitTariffDTO]
    catalogs: CatalogGroupsDTO
    exclusions: list[ExclusionDTO]
    payroll_settings: list[PayrollDTO]


class StaffInput(Schema):
    id: Optional[int] = None
    full_name: str
    staff_type: str
    is_active: bool = True


class InsuranceSchemeInput(Schema):
    id: Optional[int] = None
    code: str
    name: str
    is_supplementary: bool = False
    is_base: bool = False
    is_active: bool = True


class VisitTariffInput(Schema):
    id: Optional[int] = None
    insurance_type: str
    insurance_scheme_id: Optional[int] = None
    tariff_price: int = 0
    nursing_tariff: int = 0
    nursing_covers: bool = False
    is_active: bool = True
    is_supplementary: bool = False
    is_base_tariff: bool = False


class CatalogItemInput(Schema):
    id: Optional[int] = None
    name: str
    price: int = 0
    category: Optional[str] = None
    is_active: bool = True


class ExclusionInput(Schema):
    id: Optional[int] = None
    insurance_type: str
    nursing_service_id: int
    note: Optional[str] = None


class PayrollInput(Schema):
    staff_id: int
    base_morning: int = 0
    base_evening: int = 0
    base_night: int = 0
    visit_fee: int = 0
    injection_percent: float = 0
    procedure_percent: float = 0
    tax_percent: float = 0
    nursing_percent: float = 0
    nurse_procedure_percent: float = 0


class DeleteDTO(Schema):
    deleted: bool
    id: int


_ERROR_RESPONSES = {
    403: ErrorSchema,
    404: ErrorSchema,
    409: ErrorSchema,
    422: ErrorSchema,
    503: ErrorSchema,
}


@router.get(
    "/accounting/admin/config",
    response={200: AdminConfigurationDTO, 403: ErrorSchema, 503: ErrorSchema},
    auth=_jwt_auth,
    tags=["accounting-admin"],
)
def accounting_admin_config(request):
    return _call(
        request,
        lambda: get_accounting_admin_configuration(tenant_id=request.tenant_id),
    )


@router.post(
    "/accounting/admin/staff",
    response={201: StaffDTO} | _ERROR_RESPONSES,
    auth=_jwt_auth,
    tags=["accounting-admin"],
)
def accounting_admin_staff(request, payload: StaffInput):
    ip, agent = _meta(request)
    return _call(
        request,
        lambda: upsert_staff(
            tenant_id=request.tenant_id,
            payload=payload.model_dump(), actor=request.auth,
            ip_address=ip, user_agent=agent,
        ),
        created=True,
    )


@router.post(
    "/accounting/admin/insurance-schemes",
    response={201: InsuranceSchemeDTO} | _ERROR_RESPONSES,
    auth=_jwt_auth,
    tags=["accounting-admin"],
)
def accounting_admin_insurance_scheme(request, payload: InsuranceSchemeInput):
    ip, agent = _meta(request)
    return _call(
        request,
        lambda: upsert_insurance_scheme(
            tenant_id=request.tenant_id,
            payload=payload.model_dump(), actor=request.auth,
            ip_address=ip, user_agent=agent,
        ),
        created=True,
    )


@router.post(
    "/accounting/admin/visit-tariffs",
    response={201: VisitTariffDTO} | _ERROR_RESPONSES,
    auth=_jwt_auth,
    tags=["accounting-admin"],
)
def accounting_admin_visit_tariff(request, payload: VisitTariffInput):
    ip, agent = _meta(request)
    return _call(
        request,
        lambda: upsert_visit_tariff(
            tenant_id=request.tenant_id,
            payload=payload.model_dump(), actor=request.auth,
            ip_address=ip, user_agent=agent,
        ),
        created=True,
    )


@router.post(
    "/accounting/admin/catalogs/{catalog_type}",
    response={201: CatalogItemDTO} | _ERROR_RESPONSES,
    auth=_jwt_auth,
    tags=["accounting-admin"],
)
def accounting_admin_catalog(
    request, catalog_type: str, payload: CatalogItemInput
):
    ip, agent = _meta(request)
    return _call(
        request,
        lambda: upsert_catalog_item(
            tenant_id=request.tenant_id, catalog_type=catalog_type,
            payload=payload.model_dump(), actor=request.auth,
            ip_address=ip, user_agent=agent,
        ),
        created=True,
    )


@router.post(
    "/accounting/admin/exclusions",
    response={201: ExclusionDTO} | _ERROR_RESPONSES,
    auth=_jwt_auth,
    tags=["accounting-admin"],
)
def accounting_admin_exclusion(request, payload: ExclusionInput):
    ip, agent = _meta(request)
    return _call(
        request,
        lambda: upsert_exclusion(
            tenant_id=request.tenant_id,
            payload=payload.model_dump(), actor=request.auth,
            ip_address=ip, user_agent=agent,
        ),
        created=True,
    )


@router.delete(
    "/accounting/admin/exclusions/{exclusion_id}",
    response={200: DeleteDTO} | _ERROR_RESPONSES,
    auth=_jwt_auth,
    tags=["accounting-admin"],
)
def accounting_admin_delete_exclusion(request, exclusion_id: int):
    ip, agent = _meta(request)
    return _call(
        request,
        lambda: delete_exclusion(
            tenant_id=request.tenant_id, exclusion_id=exclusion_id,
            actor=request.auth, ip_address=ip, user_agent=agent,
        ),
    )


@router.post(
    "/accounting/admin/payroll-settings",
    response={201: PayrollDTO} | _ERROR_RESPONSES,
    auth=_jwt_auth,
    tags=["accounting-admin"],
)
def accounting_admin_payroll(request, payload: PayrollInput):
    ip, agent = _meta(request)
    return _call(
        request,
        lambda: upsert_payroll_settings(
            tenant_id=request.tenant_id,
            payload=payload.model_dump(), actor=request.auth,
            ip_address=ip, user_agent=agent,
        ),
        created=True,
    )
