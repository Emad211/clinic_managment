"""
Patient-card domain router (cleanup step 6 — god-file split).

Migrated verbatim out of the ``config/api.py`` god-file (خوشهٔ J، قدم ۴۴). Holds
the three patient-card endpoints — one PUBLIC (no JWT) read surface and two
staff-only (JWT) token-management endpoints:

  GET  /card/{token}                       → PUBLIC, zero-write, rate-limited card
  POST /patients/{uuid}/card-token         → staff JWT, issue a token
  POST /patients/{uuid}/card-token/revoke  → staff JWT, revoke a token

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", patient_card_router)`` and the routes carry their full
short paths ("/card/{token}", "/patients/{patient_uuid}/card-token", …), so
``/api/v1`` (urls.py) + the path == the same full paths as before.

SACRED SECURITY INVARIANTS (preserved verbatim — این حساس‌ترین قدم است):
  - ``GET /card/{token}`` keeps ``auth=None`` (PUBLIC). It MUST NOT acquire JWT.
  - The in-process sliding-window rate-limiter (``_card_allow`` + ``_rl_hits``)
    moves here with the domain; its state/behaviour is unchanged (per-process,
    same window/limit, initialised once at module load — never re-initialised).
  - resolve-before-GUC: ``card_resolve_token`` (SECURITY DEFINER) resolves the
    opaque token WITHOUT GUC, then ``set_tenant_guc`` scopes the projection.
  - No PHI in the URL (opaque token only); generic 404 leaks no reason;
    zero-write on the public path; minimum-necessary / leak-proof projection.

This module imports FROM ``config.api_base`` (shared ``api``/``_jwt_auth``);
nothing in ``api_base`` imports a router, so the package stays free of cycles.
"""
from typing import Optional
from datetime import datetime
import threading as _threading
import time as _time

import uuid as uuid_module
from ninja import Router, Schema

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response

from accounting_port.port import get_patient_by_uuid
from clinical.audit import log_activity
from clinical.card_token_service import (
    issue as _card_issue,
    revoke as _card_revoke,
    resolve_token as _card_resolve_token,
    active_for_patient as _card_active_for_patient,  # noqa: F401  (kept for parity)
)
from clinical.card_projection_service import card_for_patient as _card_for_patient
from platform_core.tenant_context import set_tenant_guc as _set_tenant_guc

router = Router()


# ===========================================================================
# Patient Card Token — خوشهٔ J، قدم ۴۴
#
# سطحِ PHIِ رو-به-بیمار، امنیتی‌بحرانی.
#
# معماریِ امنیتی (قفل‌شده با security-privacy-advisor):
#   - endpoint عمومی GET /card/{token}: بدونِ JWT، zero-write، rate-limit in-process.
#     card_resolve_token() SECURITY DEFINER → GUC → projection → response.
#   - staff endpointها (issue/revoke): JWT + GUC → RLS.
#
# گِیتِ LAN-vs-internet (ثبت‌شده، internet غیرفعال):
#   مواجهه با اینترنت نیازِ TLS + rate-limitِ توزیع‌شده + TTLِ کوتاه‌تر + آنتروپیِ
#   بیشتر دارد. مسیرِ SMS-link نساخته‌ایم (KYC بلاک). فعلاً LAN-only.
# ===========================================================================

# ---------------------------------------------------------------------------
# Rate-limit in-process — SECU-13 (per-process، مثلِ specialist_clinic).
# برای deployment چند-instance، Redis/DB-backed لازم است.
# ---------------------------------------------------------------------------
_rl_lock = _threading.Lock()
_rl_hits: dict[str, list[float]] = {}

_CARD_RATE_LIMIT = 30   # درخواست
_CARD_RATE_WINDOW = 60  # ثانیه


def _card_allow(key: str) -> bool:
    """Sliding window rate-limiter (in-process). Returns True if request is allowed."""
    t = _time.monotonic()
    cutoff = t - _CARD_RATE_WINDOW
    with _rl_lock:
        q = _rl_hits.setdefault(key, [])
        while q and q[0] < cutoff:
            q.pop(0)
        if len(q) >= _CARD_RATE_LIMIT:
            return False
        q.append(t)
        return True


# ---------------------------------------------------------------------------
# Schemas — card endpoints
# ---------------------------------------------------------------------------

class VitalCardDTO(Schema):
    """یک ویتال روی کارتِ عمومی (minimum-necessary)."""
    key: str
    label: str
    value: float
    unit: str
    status: str  # 'ok' | 'warn' | 'danger'


class PublicCardResponse(Schema):
    """
    قرارداد payload کارتِ عمومیِ بیمار (قفل‌شده — frontend موازی همین را مصرف می‌کند).

    هرگز: national_id، تماسِ بیمار، نامِ دارو/دوز، تشخیص/بیماری،
    HbA1cِ خام، یادداشتِ بالینی، درآمد/کیف‌پول.
    """
    first_name: str
    clinic_name: Optional[str]
    vitals: list[VitalCardDTO]
    next_appointment: Optional[str]   # ISO date (YYYY-MM-DD) یا None
    framing: str                       # جملهٔ انگیزشیِ ساده
    # یادآورِ خنثیِ غربالگری (قدم ۴۸): رشتهٔ نرم یا None.
    # هرگز per-item/count/label/تاریخ — فقط پیامِ count-capped و بدونِ تشخیص.
    reminder_message: Optional[str] = None


class CardTokenOut(Schema):
    """پاسخِ issue token برای staff."""
    token: str
    expires_at: datetime
    card_url: str   # URL مطلق نیست — فقط path (LAN-only)


# ---------------------------------------------------------------------------
# ۱) GET /card/{token} — endpoint عمومی (بدونِ JWT، zero-write)
#
#    جریانِ resolve→GUC→projection:
#      ۱) card_resolve_token(token) → {patient_link_id, tenant_id} یا None.
#         (SECURITY DEFINER: RLS را برای این lookup عبور می‌دهد.)
#      ۲) اگر None → 404 (generic: دلیل فاش نمی‌شود).
#      ۳) set_tenant_guc(tenant_id) → GUC ست می‌شود.
#      ۴) card_for_patient(patient_link_id, tenant_id) → projection (GUC-scoped).
#      ۵) Return PublicCardResponse.
#
#    zero-write: هیچ INSERT/UPDATE/DELETE در این مسیر وجود ندارد.
#    rate-limit: ≤ 30 درخواست/۶۰ ثانیه per IP (in-process).
# ---------------------------------------------------------------------------

@router.get(
    "/card/{token}",
    response={200: PublicCardResponse, 404: ErrorSchema, 429: ErrorSchema},
    auth=None,
    tags=["patient-card"],
    summary="کارتِ عمومیِ بیمار (بدونِ JWT)",
)
def get_public_card(request, token: str):
    """
    سطحِ عمومیِ رو-به-بیمار: آخرین ویتال‌ها + نوبتِ بعدی.
    بدونِ JWT. rate-limit: ۳۰ req/min per IP (in-process).

    zero-write: این endpoint هیچ چیزی نمی‌نویسد.

    LAN-vs-internet note:
      این endpoint فعلاً LAN-only (QR/tablet در مطب) است.
      internet exposure نیازِ TLS + rate-limitِ توزیع‌شده دارد (هنوز فعال نیست).
    """
    client_ip = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR", "?")
    )
    if not _card_allow(f"card:{client_ip}"):
        return 429, error_response("تعدادِ درخواست بیش از حد مجاز است", "rate_limited")

    resolved = _card_resolve_token(token)
    if resolved is None:
        # generic 404: دلیل فاش نمی‌شود (ناشناخته/منقضی/revoked)
        return 404, error_response("کارت یافت نشد", "not_found")

    patient_link_id = resolved["patient_link_id"]
    tenant_id = resolved["tenant_id"]

    # GUC را ست کن تا دادهٔ بالینی تحتِ RLS (tenant-scoped) خوانده شود
    _set_tenant_guc(tenant_id)

    card_data = _card_for_patient(patient_link_id, tenant_id)
    if card_data is None:
        return 404, error_response("کارت یافت نشد", "not_found")

    return 200, PublicCardResponse(
        first_name=card_data["first_name"],
        clinic_name=card_data["clinic_name"],
        vitals=[VitalCardDTO(**v) for v in card_data["vitals"]],
        next_appointment=card_data["next_appointment"],
        framing=card_data["framing"],
        reminder_message=card_data.get("reminder_message"),
    )


# ---------------------------------------------------------------------------
# ۲) POST /patients/{uuid}/card-token — issue token (staff، JWT)
# ---------------------------------------------------------------------------

@router.post(
    "/patients/{patient_uuid}/card-token",
    response={201: CardTokenOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-card"],
    summary="صدورِ توکنِ کارتِ بیمار (staff)",
)
def issue_card_token(request, patient_uuid: uuid_module.UUID):
    """
    صدورِ توکنِ جدیدِ کارتِ عمومی برای بیمار (staff-only).
    one-active-at-a-time: توکنِ قبلی revoke می‌شود.
    TTL پیش‌فرض: ۸ ساعت (LAN-only).

    Returns: {token, expires_at, card_url}
    """
    tenant_id = request.tenant_id
    user = request.auth

    # پیدا کردنِ patient_link از UUID بیمار
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        return 404, error_response("بیمار یافت نشد", "not_found")

    from clinical.models import PatientLink
    try:
        link = PatientLink.objects.get(
            tenant_id=tenant_id,
            patient_id=demo.id,
        )
    except PatientLink.DoesNotExist:
        return 404, error_response("بیمار در کلینیک ثبت‌نام نشده", "not_found")

    token_str, expires_at = _card_issue(
        patient_link_id=link.id,
        tenant_id=tenant_id,
        issued_by=user.username,
    )

    log_activity(
        tenant_id=tenant_id,
        user_id=user.id,
        username=user.username,
        action_type="card_token_issued",
        action_category="patient_card",
        description=f"card token issued for patient_link_id={link.id}",
        patient_link_id=link.id,
    )

    return 201, CardTokenOut(
        token=token_str,
        expires_at=expires_at,
        card_url=f"/card/{token_str}",
    )


# ---------------------------------------------------------------------------
# ۳) POST /patients/{uuid}/card-token/revoke — revoke token (staff، JWT)
# ---------------------------------------------------------------------------

class CardRevokeRequest(Schema):
    token_id: int


@router.post(
    "/patients/{patient_uuid}/card-token/revoke",
    response={200: dict, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-card"],
    summary="رevokeِ توکنِ کارتِ بیمار (staff)",
)
def revoke_card_token(request, patient_uuid: uuid_module.UUID, body: CardRevokeRequest):
    """
    Revoke یک توکنِ فعال (staff-only).
    GUC-scoped: RLS به tenant محدود می‌کند — cross-tenant revoke ممکن نیست.
    """
    tenant_id = request.tenant_id
    user = request.auth

    ok = _card_revoke(token_id=body.token_id, tenant_id=tenant_id)
    if not ok:
        return 404, error_response("توکن یافت نشد یا قبلاً revoke شده", "not_found")

    log_activity(
        tenant_id=tenant_id,
        user_id=user.id,
        username=user.username,
        action_type="card_token_revoked",
        action_category="patient_card",
        description=f"card token {body.token_id} revoked",
    )

    return 200, {"status": "revoked"}
