"""
Allergies domain router (فاز ۱ کاکپیتِ پروندهٔ بیمار).

CRUDِ حساسیت‌های بیمار روی جدولِ کانونیِ ``clinical.allergies`` (slice2 + slice18).
همه JWT، همه tenant-scoped:

  GET    /patients/{uuid}/allergies            → list[AllergyDTO]
  POST   /patients/{uuid}/allergies            → 201 AllergyDTO
  DELETE /patients/{uuid}/allergies/{id}       → 200 {"deleted": true, "id": id}

قراردادِ JSON (برای مصرفِ فرانتِ کاکپیت):
  AllergyDTO = { id, substance, severity, note, reaction, created_at }
  حداقلِ توافق‌شده {id, substance, severity, note} است؛ reaction (ستونِ slice2)
  و created_at superset‌های بی‌ضرر و هم‌راستا با بقیهٔ DTOهای پروژه‌اند — فرانت
  می‌تواند نادیده بگیرد. severity یکی از mild|moderate|severe|anaphylaxis یا null.

لایه‌بندی: route → service (clinical.allergy_service) → ORM. هیچ SQLِ خامی این‌جا.
resolveِ بیمار با helperِ مشترکِ ``_resolve_patient_link_for_tenant`` (همان Http404ها).
GUC/RLS و لاگِ activity در لایهٔ سرویس انجام می‌شوند.

این ماژول FROM ``config.api_base`` و ``clinical.api._shared`` import می‌کند؛ هیچ‌کدام
router import نمی‌کنند → پکیج بدونِ چرخهٔ import می‌ماند (هم‌الگوی بقیهٔ routerها).
"""
from __future__ import annotations

import uuid as uuid_module
from typing import Optional
from datetime import datetime

from ninja import Router, Schema

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response
from clinical.api._shared import _resolve_patient_link_for_tenant

from clinical.allergy_service import (
    list_allergies as _list_allergies,
    add_allergy as _add_allergy,
    delete_allergy as _delete_allergy,
    AllergyValidationError as _AllergyValidationError,
    InvalidAllergySeverity as _InvalidAllergySeverity,
    AllergyNotFound as _AllergyNotFound,
)

router = Router()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AllergyDTO(Schema):
    """یک حساسیت در پاسخِ فهرست/ساخت."""
    id: int
    substance: str
    severity: Optional[str] = None
    note: Optional[str] = None
    # superset بی‌ضرر (ستونِ slice2 + مهرِ زمانِ DB):
    reaction: Optional[str] = None
    created_at: datetime


class AllergyIn(Schema):
    """بدنهٔ POST — ساختِ حساسیت."""
    substance: str
    severity: Optional[str] = None
    note: Optional[str] = None


class AllergyDeleteOut(Schema):
    """پاسخِ DELETE."""
    deleted: bool
    id: int


def _to_dto(a) -> AllergyDTO:
    return AllergyDTO(
        id=a.id,
        substance=a.substance,
        severity=a.severity,
        note=a.note,
        reaction=a.reaction,
        created_at=a.created_at,
    )


# ---------------------------------------------------------------------------
# GET /patients/{uuid}/allergies
# ---------------------------------------------------------------------------

@router.get(
    "/patients/{patient_uuid}/allergies",
    response=list[AllergyDTO],
    auth=_jwt_auth,
    tags=["allergies"],
)
def list_patient_allergies(request, patient_uuid: uuid_module.UUID):
    """
    فهرستِ حساسیت‌های بیمار (جدیدترین اول). JWT، tenant-scoped.

    Lookup: accounting.patients(uuid) → clinical.patient_links(tenant) → allergies.
    404 اگر بیمار یا ثبت‌نامِ بالینیِ این مستأجر وجود نداشته باشد.
    """
    tenant_id = request.tenant_id
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)
    rows = _list_allergies(tenant_id=tenant_id, patient_link_id=link.id)
    return [_to_dto(a) for a in rows]


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/allergies
# ---------------------------------------------------------------------------

@router.post(
    "/patients/{patient_uuid}/allergies",
    response={201: AllergyDTO, 404: ErrorSchema, 422: ErrorSchema},
    auth=_jwt_auth,
    tags=["allergies"],
)
def create_patient_allergy(request, patient_uuid: uuid_module.UUID, payload: AllergyIn):
    """
    افزودنِ یک حساسیت برای بیمار → 201 با ردیفِ ساخته‌شده. JWT، tenant-scoped.

    - substance اجباری (خالی → 422 validation_error).
    - severity یکی از mild|moderate|severe|anaphylaxis یا خالی (نامعتبر → 422).
    - Audit: allergy_added (لایهٔ سرویس).
    404 اگر بیمار/ثبت‌نامِ این مستأجر وجود نداشته باشد.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    actor_id = getattr(request.auth, "pk", None)

    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    try:
        allergy = _add_allergy(
            tenant_id=tenant_id,
            patient_link_id=link.id,
            substance=payload.substance,
            severity=payload.severity,
            note=payload.note,
            actor_username=actor,
            actor_id=actor_id,
        )
    except (_AllergyValidationError, _InvalidAllergySeverity) as exc:
        return 422, error_response(str(exc), "validation_error")

    return 201, _to_dto(allergy)


# ---------------------------------------------------------------------------
# DELETE /patients/{uuid}/allergies/{id}
# ---------------------------------------------------------------------------

@router.delete(
    "/patients/{patient_uuid}/allergies/{allergy_id}",
    response={200: AllergyDeleteOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["allergies"],
)
def delete_patient_allergy(
    request, patient_uuid: uuid_module.UUID, allergy_id: int
):
    """
    حذفِ یک حساسیتِ بیمار. JWT، tenant-scoped.

    با (id, tenant_id, patient_link_id) فیلتر می‌شود → حذفِ cross-tenant ممکن نیست.
    404 اگر ردیف برای این بیمار/مستأجر پیدا نشد. Audit: allergy_deleted.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    actor_id = getattr(request.auth, "pk", None)

    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    try:
        _delete_allergy(
            tenant_id=tenant_id,
            patient_link_id=link.id,
            allergy_id=allergy_id,
            actor_username=actor,
            actor_id=actor_id,
        )
    except _AllergyNotFound as exc:
        return 404, error_response(str(exc), "not_found")

    return 200, AllergyDeleteOut(deleted=True, id=allergy_id)
