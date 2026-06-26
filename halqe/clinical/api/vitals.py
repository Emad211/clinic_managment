"""
Vitals domain router (cleanup step 7 — god-file split).

Migrated verbatim out of the ``config/api.py`` god-file. Holds the vital read
endpoint plus the physician vital-review write-path (slice14 / step 47):

  GET  /patients/{uuid}/vitals/latest               → latest reading per type
  POST /patients/{uuid}/vitals/{vital_id}/verify    → pending → approved
  POST /patients/{uuid}/vitals/{vital_id}/reject    → pending → rejected (soft-keep)

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", vitals_router)`` and the routes carry their full short
paths, so ``/api/v1`` (urls.py) + the path == the same full paths as before.

SACRED SAFETY INVARIANT (locked with gp-family-medicine-advisor, step 45/47):
  The 6 ``verified=True`` filters in the engine are UNTOUCHED — this module only
  moves the endpoints, not the gate logic.
    - verify  : sets verified=TRUE  → the reading enters build_facts/card/suggestions.
    - reject  : leaves verified=FALSE, sets rejected_at → stays out of the engine
                automatically (Assert C); soft-keep means the row is NOT deleted —
                it remains in the DB for audit.
  State machine:
    pending  : verified=FALSE, rejected_at IS NULL
    approved : verified=TRUE
    rejected : verified=FALSE, rejected_at NOT NULL  (soft-kept for audit)
  RLS: set_tenant_guc(app.current_tenant) → staff sees only its own tenant.
  Idempotency: verify of an already-verified row → 409 conflict.

This module imports FROM ``config.api_base`` (shared ``_jwt_auth``) and
``clinical.api._shared`` (``VitalReadingDTO`` + ``_resolve_patient_link_for_tenant``);
nothing in either imports a router, so the package stays free of cycles.
"""
from __future__ import annotations

import uuid as uuid_module
from typing import Optional
from datetime import datetime

from ninja import Router, Schema
from django.utils import timezone

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response
from clinical.api._shared import (
    VitalReadingDTO,
    _resolve_patient_link_for_tenant,
)

from accounting_port.port import get_patient_by_uuid
from clinical.models import VitalReading, PatientLink
from clinical.audit import log_activity

router = Router()


# ---------------------------------------------------------------------------
# Vitals (latest) endpoint — requires JWT
# ---------------------------------------------------------------------------

@router.get(
    "/patients/{patient_uuid}/vitals/latest",
    response=list[VitalReadingDTO],
    auth=_jwt_auth,
    tags=["vitals"],
)
def get_latest_vitals(request, patient_uuid: uuid_module.UUID):
    """
    Return the most recent VitalReading for each type for this patient. Requires JWT.

    Lookup chain: accounting.patients(uuid) → clinical.patient_links → vital_readings.
    Raises 404 if the patient or the clinical enrollment doesn't exist.
    """
    from django.http import Http404

    # 1. Resolve uuid → accounting patient id (read-only)
    patient_dto = get_patient_by_uuid(patient_uuid)
    if patient_dto is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    # 2. Find the clinical patient_link
    try:
        link = PatientLink.objects.get(patient_id=patient_dto.id, is_active=True)
    except PatientLink.DoesNotExist:
        raise Http404(f"Patient uuid={patient_uuid} has no active clinical enrollment.")

    # 3. Latest reading per type
    latest_per_type = (
        VitalReading.objects.filter(patient_link_id=link.id)
        .order_by("type", "-measured_at")
        .distinct("type")
    )

    return list(latest_per_type)


# ===========================================================================
# Vital Review — خوشهٔ J، قدم ۴۷
#
# POST /patients/{uuid}/vitals/{vital_id}/verify   → staff JWT، GUC-scoped/RLS
# POST /patients/{uuid}/vitals/{vital_id}/reject   → staff JWT، GUC-scoped/RLS
#
# اصلِ ایمنی (قفل‌شده با gp-family-medicine-advisor):
#   ۶ فیلترِ verified=True در موتور دست‌نخورده باقی می‌مانند.
#   rejected هم verified=FALSE است → خودکار از موتور خارج می‌ماند (Assert C).
#   soft-keep: reject حذفِ فیزیکی نیست — ردیف در DB می‌ماند برای audit.
#
# State machine (slice14):
#   pending  : verified=FALSE, rejected_at IS NULL  — انتظار
#   approved : verified=TRUE                         — بعد از verify
#   rejected : verified=FALSE, rejected_at NOT NULL  — soft-kept for audit
#
# RLS: GUC app.current_tenant ست می‌شود → staff فقط tenantِ خود را می‌بیند.
# Idempotency: verifyِ ردیفِ از-قبل-verified → 409 conflict.
# Audit: هر دو اکشن لاگ می‌شوند.
# ===========================================================================

class VitalReviewOut(Schema):
    """Vital reading بعد از review — حالتِ کامل برای UI."""
    id: int
    patient_link_id: int
    type: str
    value: float
    unit: Optional[str] = None
    measured_at: datetime
    source: Optional[str] = None
    verified: bool
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None


def _vital_to_review_out(v: "VitalReading") -> VitalReviewOut:
    return VitalReviewOut(
        id=v.id,
        patient_link_id=v.patient_link_id,
        type=v.type,
        value=v.value,
        unit=v.unit,
        measured_at=v.measured_at,
        source=v.source,
        verified=v.verified,
        verified_by=v.verified_by,
        verified_at=v.verified_at,
        rejected_by=v.rejected_by,
        rejected_at=v.rejected_at,
    )


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/vitals/{vital_id}/verify
# ---------------------------------------------------------------------------

@router.post(
    "/patients/{patient_uuid}/vitals/{vital_id}/verify",
    response={
        200: VitalReviewOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["vitals"],
)
def verify_vital(request, patient_uuid: uuid_module.UUID, vital_id: int):
    """
    تأییدِ یک vital readingِ self-reported توسطِ پزشک/staff.

    State transition: pending (verified=FALSE, rejected_at=NULL) → approved (verified=TRUE).

    پس از verify، ردیف verified=TRUE می‌شود و در build_facts / کارت / پیشنهادها ظاهر می‌شود.
    ۶ فیلترِ موتور (verified=True) دست‌نخورده هستند — هیچ تغییری در منطقِ فیلتر داده نشده.

    RLS-scoped: GUC app.current_tenant ست می‌شود → staff فقط tenantِ خودش را می‌بیند.
    Idempotency: اگر ردیف از قبل verified=TRUE باشد → ۴۰۹ conflict.
    Audit: log_activity با action_type='vital_verified'.

    Returns 404 اگر vital وجود نداشته باشد یا متعلق به این بیمار/tenant نباشد.
    Returns 409 اگر ردیف از قبل verified=TRUE بود (idempotency guard).
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    actor_id = getattr(request.auth, "pk", None)

    # 1. Resolve uuid → patient link (tenant-scoped, 404 if not found)
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    # 2. Fetch the vital — must belong to this patient + tenant (RLS gate)
    #    set_tenant_guc ensures the ORM query runs with the correct GUC
    from platform_core.tenant_context import set_tenant_guc as _set_guc
    _set_guc(tenant_id)

    try:
        vital = VitalReading.objects.get(
            id=vital_id,
            patient_link_id=link.id,
            tenant_id=tenant_id,
        )
    except VitalReading.DoesNotExist:
        return 404, error_response(
            f"VitalReading id={vital_id} not found for this patient/tenant.",
            "not_found",
        )

    # 3. Idempotency guard — already verified → 409
    if vital.verified:
        return 409, error_response(
            f"VitalReading id={vital_id} is already verified (verified=TRUE). "
            "No action taken.",
            "conflict",
        )

    # 4. Apply verify: verified=TRUE, verified_by, verified_at
    now_ts = timezone.now()
    vital.verified = True
    vital.verified_by = actor
    vital.verified_at = now_ts
    vital.save(update_fields=["verified", "verified_by", "verified_at"])

    # 5. Audit — state-changing write, best-effort append-only
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_id,
        username=actor,
        action_type="vital_verified",
        action_category="clinical",
        target_table="vital_readings",
        target_id=vital_id,
        patient_link_id=link.id,
        description=f"type={vital.type}, value={vital.value}, source={vital.source}",
    )

    return 200, _vital_to_review_out(vital)


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/vitals/{vital_id}/reject
# ---------------------------------------------------------------------------

@router.post(
    "/patients/{patient_uuid}/vitals/{vital_id}/reject",
    response={
        200: VitalReviewOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["vitals"],
)
def reject_vital(request, patient_uuid: uuid_module.UUID, vital_id: int):
    """
    ردِ یک vital readingِ self-reported توسطِ پزشک/staff.

    State transition: pending (verified=FALSE, rejected_at=NULL) → rejected (rejected_by, rejected_at ست).

    پس از reject، ردیف verified=FALSE باقی می‌ماند → خودکار از موتور/کارت/پیشنهادها خارج است.
    soft-keep: ردیف از DB حذف نمی‌شود — برای audit trail نگه‌داری می‌شود (توصیهٔ حقوقیِ GP).

    RLS-scoped: GUC app.current_tenant ست می‌شود → staff فقط tenantِ خودش را می‌بیند.
    Guard: اگر ردیف قبلاً rejected باشد (rejected_at IS NOT NULL) → ۴۰۹.
    اگر ردیف verified=TRUE باشد (approved) → ۴۰۹ (نمی‌توان approved را reject کرد).
    Audit: log_activity با action_type='vital_rejected'.

    Returns 404 اگر vital وجود نداشته باشد یا متعلق به این بیمار/tenant نباشد.
    Returns 409 اگر ردیف قبلاً rejected یا verified (approved) باشد.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    actor_id = getattr(request.auth, "pk", None)

    # 1. Resolve uuid → patient link (tenant-scoped, 404 if not found)
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    # 2. Set GUC + fetch the vital — must belong to this patient + tenant
    from platform_core.tenant_context import set_tenant_guc as _set_guc
    _set_guc(tenant_id)

    try:
        vital = VitalReading.objects.get(
            id=vital_id,
            patient_link_id=link.id,
            tenant_id=tenant_id,
        )
    except VitalReading.DoesNotExist:
        return 404, error_response(
            f"VitalReading id={vital_id} not found for this patient/tenant.",
            "not_found",
        )

    # 3. Guard: cannot reject an already-rejected or already-verified (approved) vital
    if vital.rejected_at is not None:
        return 409, error_response(
            f"VitalReading id={vital_id} is already rejected (rejected_at is set). "
            "No action taken.",
            "conflict",
        )
    if vital.verified:
        return 409, error_response(
            f"VitalReading id={vital_id} is verified (approved). "
            "Cannot reject a verified reading — re-enter data via an encounter if needed.",
            "conflict",
        )

    # 4. Apply reject: rejected_by + rejected_at; verified stays FALSE (gate intact)
    now_ts = timezone.now()
    vital.rejected_by = actor
    vital.rejected_at = now_ts
    # vital.verified stays FALSE — the 6 engine filters (verified=True) remain untouched
    vital.save(update_fields=["rejected_by", "rejected_at"])

    # 5. Audit — state-changing write, best-effort append-only
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_id,
        username=actor,
        action_type="vital_rejected",
        action_category="clinical",
        target_table="vital_readings",
        target_id=vital_id,
        patient_link_id=link.id,
        description=f"type={vital.type}, value={vital.value}, source={vital.source}",
    )

    return 200, _vital_to_review_out(vital)
