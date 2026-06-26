"""
Patient self-report domain router (cleanup step 6 — god-file split).

Migrated verbatim out of the ``config/api.py`` god-file (slice13 / step 45). Holds
the two self-report endpoints — one staff-only (JWT) token issuer and one PUBLIC
(no JWT, one-time token) patient submission endpoint:

  POST /patients/{uuid}/report-token  → staff JWT, issue a one-time report token
  POST /patient-report/{token}        → PUBLIC, one-time, verified=FALSE insert

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", self_report_router)`` and the routes carry their full short
paths, so ``/api/v1`` (urls.py) + the path == the same full paths as before.

SACRED SECURITY INVARIANTS (preserved verbatim — این حساس‌ترین قدم است):
  - ``POST /patient-report/{token}`` keeps ``auth=None`` (PUBLIC). It MUST NOT
    acquire JWT — an opaque one-time token authenticates the request.
  - The in-process per-token rate-limiter (``_check_rate_limit`` + ``_rate_store``)
    moves here with the domain; its state/behaviour is unchanged (per-process,
    one request/token/minute, initialised once at module load — never reset).
  - resolve-before-GUC: ``report_resolve_token`` (SECURITY DEFINER) resolves the
    one-time token WITHOUT GUC, then ``set_tenant_guc`` scopes the insert.
  - No PHI in URL / response body; one-time token (used → generic 404 thereafter);
    every reading is stored ``verified=FALSE, source='patient_self'`` so the
    sacred verified-gate keeps it out of the engine/card/suggestions until a
    physician verifies it (step 47). all-or-nothing insert + single mark-used
    inside one transaction.

``_resolve_patient_link_for_tenant`` is shared with NON-migrated domains
(encounters, vital-review), so per the cleanup rule it STAYS in ``config.api``
and is imported lazily here (function-level) to avoid an import cycle — the
helper is defined in ``config.api`` *after* this router is imported, so a
module-level import would fail.

This module imports FROM ``config.api_base`` (shared ``_jwt_auth``); nothing in
``api_base`` imports a router, so the package stays free of cycles.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime
import threading as _threading
import time as _time

import uuid as uuid_module
from ninja import Router, Schema

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response

from clinical.audit import log_activity
from clinical.report_token_service import (
    issue as _report_issue,
    resolve_token as _report_resolve,
    mark_used as _report_mark_used,
)
from platform_core.tenant_context import set_tenant_guc as _set_tenant_guc

router = Router()


# ===========================================================================
# Patient self-report — slice13 / step 45
#
# اصلِ مقدس (security-privacy-advisor):
#   دادهٔ self-reportِ تأییدنشده هرگز وارد موتور/کارت/پیشنهاد نمی‌شود
#   تا پزشک verify کند (قدم ۴۷ — موکول).
#
# Endpoints:
#   POST /patients/{uuid}/report-token  — staff issue (JWT required)
#   POST /patient-report/{token}        — public submit (no JWT, one-time token)
# ===========================================================================

# ── مقادیرِ مجاز و بازه‌های فیزیولوژیکِ self-report ─────────────────────────
# Whitelist محدود: فقط شاخص‌هایی که بیمار می‌تواند در خانه اندازه بگیرد.
_REPORT_ALLOWED_TYPES: dict[str, tuple[float, float]] = {
    "fbs":          (20.0,  800.0),   # mg/dL — قند ناشتا
    "bp_systolic":  (50.0,  300.0),   # mmHg  — فشارِ سیستولیک
    "bp_diastolic": (20.0,  200.0),   # mmHg  — فشارِ دیاستولیک
}
_REPORT_UNIT: dict[str, str] = {
    "fbs":          "mg/dL",
    "bp_systolic":  "mmHg",
    "bp_diastolic": "mmHg",
}

# Rate-limit ساده in-process (per-process — برای multi-instance باید Redis شود)
_rate_lock = _threading.Lock()
_rate_store: dict[str, float] = {}   # token_str → last_attempt timestamp
_RATE_WINDOW_SEC = 60                # یک درخواست per token per minute


def _check_rate_limit(token_str: str) -> bool:
    """Returns True if within rate limit (allow). False = too many requests."""
    now = _time.monotonic()
    with _rate_lock:
        last = _rate_store.get(token_str)
        if last is not None and (now - last) < _RATE_WINDOW_SEC:
            return False
        _rate_store[token_str] = now
    return True


# ---------------------------------------------------------------------------
# Schemas — self-report
# ---------------------------------------------------------------------------

class ReportTokenOut(Schema):
    """توکنِ self-report صادرشده برای بیمار."""
    token: str
    expires_at: datetime
    report_url: str


class SelfReportReadingIn(Schema):
    """یک اندازه‌گیری در batch."""
    type: str
    value: float

    class Config:
        extra = "forbid"   # کلیدِ اضافی reject می‌شود


class SelfReportIn(Schema):
    """
    بدنهٔ درخواستِ self-report بیمار.

    دو حالتِ پشتیبانی‌شده:
    ۱) تکی (سازگار با قبل): {type, value}
    ۲) batch: {readings: [{type, value}, ...]} — یک تا N خواندن.
    اگر readings موجود باشد، حالتِ batch اعمال می‌شود (type/value نادیده).
    """
    # حالتِ تکی (سازگار با قبل)
    type: Optional[str] = None
    value: Optional[float] = None
    # حالتِ batch
    readings: Optional[list[SelfReportReadingIn]] = None

    class Config:
        extra = "forbid"   # کلیدِ اضافی reject می‌شود


class SelfReportReadingOut(Schema):
    """یک اندازه‌گیری در پاسخِ batch."""
    type: str
    value: float


class SelfReportOut(Schema):
    """
    پاسخِ موفقِ self-report.

    در حالتِ تکی: type/value حاضرند و accepted=[{type, value}].
    در حالتِ batch: accepted لیستِ همهٔ اندازه‌گیری‌های ثبت‌شده، count=تعداد.
    سازگار با هر دو حالت.
    """
    status: str = "ok"
    # حالتِ تکی (backward-compat)
    type: Optional[str] = None
    value: Optional[float] = None
    # batch (همیشه حاضر — در حالتِ تکی یک آیتم دارد)
    accepted: list[SelfReportReadingOut] = []
    count: int = 1
    message: str = "داده دریافت شد — پزشک آن را بررسی خواهد کرد"


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/report-token — صدورِ توکنِ self-report (staff، JWT)
# ---------------------------------------------------------------------------

@router.post(
    "/patients/{patient_uuid}/report-token",
    response={201: ReportTokenOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["self-report"],
    summary="صدورِ توکنِ self-report برای بیمار (staff)",
)
def issue_report_token(request, patient_uuid: uuid_module.UUID):
    """
    صدورِ توکنِ یک‌بارمصرفِ self-report برای یک بیمارِ ثبت‌نام‌شده.

    staff (manager یا staff role) می‌تواند این توکن را صادر و لینکِ آن را
    به بیمار بدهد (SMS / QR).
    توکن یک‌بارمصرف است و بعد از TTL (۲۴ ساعت) منقضی می‌شود.
    بیمار از لینک POST /patient-report/{token} استفاده می‌کند تا داده ثبت کند.

    scope جداگانه از card-token: این توکن فقط برای write path (self-report)
    مجاز است؛ /card/{token} (read path) آن را نمی‌پذیرد.

    داده‌ای که از این مسیر می‌آید با verified=FALSE ذخیره می‌شود و هرگز
    وارد موتور/کارت/پیشنهاد نمی‌شود تا پزشک تأیید کند (قدم ۴۷).

    Requires JWT. Tenant-scoped: 404 if patient has no enrollment for this tenant.
    """
    # _resolve_patient_link_for_tenant is shared with non-migrated domains and
    # lives in config.api; import lazily (function-level) to avoid a cycle.
    from config.api import _resolve_patient_link_for_tenant

    tenant_id = request.tenant_id
    user = request.auth

    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    token_str, expires_at = _report_issue(
        patient_link_id=link.id,
        tenant_id=tenant_id,
        issued_by=user.username,
    )

    log_activity(
        tenant_id=tenant_id,
        user_id=user.id,
        username=user.username,
        action_type="report_token_issued",
        action_category="self_report",
        description=f"report token issued for patient_link_id={link.id}",
        patient_link_id=link.id,
    )

    return 201, ReportTokenOut(
        token=token_str,
        expires_at=expires_at,
        report_url=f"/patient-report/{token_str}",
    )


# ---------------------------------------------------------------------------
# POST /patient-report/{token} — ثبتِ self-report بیمار (بدونِ JWT)
# ---------------------------------------------------------------------------

@router.post(
    "/patient-report/{token}",
    response={
        200: SelfReportOut,
        404: ErrorSchema,   # token نامعتبر/ناشناخته
        409: ErrorSchema,   # token قبلاً استفاده‌شده
        410: ErrorSchema,   # token منقضی
        422: ErrorSchema,   # مقدار خارج از بازه یا type غیرمجاز
        429: ErrorSchema,   # rate limit
    },
    auth=None,
    tags=["self-report"],
    summary="ثبتِ self-report بیمار (بدونِ JWT، یک‌بارمصرف)",
)
def submit_patient_report(request, token: str, body: SelfReportIn):
    """
    endpoint عمومیِ ثبتِ self-report بیمار.

    امنیت (security-privacy-advisor قفل کرد):
      ۱) بدونِ JWT — توکنِ opaque (one-time) احراز هویت می‌کند.
      ۲) report_resolve_token() SECURITY DEFINER برای lookup بدونِ GUC.
      ۳) type در whitelist محدود (fbs | bp_systolic | bp_diastolic).
      ۴) value در بازهٔ فیزیولوژیک — خارج از بازه → ۴۲۲.
      ۵) هیچ PHI در URL / بدنهٔ پاسخ.
      ۶) یک‌بارمصرف: بعد از استفادهٔ موفق → ۴۰۴ برای درخواست‌های بعدی.
      ۷) داده با verified=FALSE, source='patient_self' ذخیره می‌شود.
      ۸) rate-limit: یک درخواست per token per minute.

    دو حالتِ بدنه:
      تکی (سازگار با قبل): {type, value}
      batch: {readings: [{type, value}, ...]} — یک تا N اندازه‌گیری.

    منطقِ batch:
      - all-or-nothing: اگر هر reading نامعتبر باشد → ۴۲۲، هیچ insert و هیچ mark-used.
      - batch خالی → ۴۲۲.
      - همه reading معتبر: همه insert شوند → توکن یک‌بار mark used شود.

    جریانِ کامل:
      ۱) resolve token (SECURITY DEFINER — no GUC)
      ۲) normalize به لیستِ readings
      ۳) validate همهٔ readings (all-or-nothing قبل از insert)
      ۴) rate-limit check
      ۵) set_tenant_guc(tenant_id)
      ۶) INSERT همه readings (verified=FALSE, source='patient_self')
      ۷) mark_used یک‌بار
      ۸) return 200

    Physician verify (step 47, deferred):
      verified=FALSE ردیف تا زمانِ تأییدِ پزشک نامرئی است.
    """
    # 1) Resolve token (SECURITY DEFINER — no GUC needed)
    # Rate-limit is applied AFTER resolve so that:
    #   (a) expired/used/unknown tokens return 404 without consuming rate-limit.
    #   (b) validation failures (422) return 422 without consuming rate-limit,
    #       so the user can retry with a corrected value (توکن مصرف نمی‌شود).
    resolved = _report_resolve(token)

    if resolved is None:
        return _report_distinguish_error(token)

    patient_link_id = resolved["patient_link_id"]
    tenant_id = resolved["tenant_id"]

    # 2) Normalize body به لیستِ (type, value) — سازگار با حالتِ تکی و batch
    if body.readings is not None:
        # حالتِ batch
        raw_readings = [(r.type, r.value) for r in body.readings]
    elif body.type is not None and body.value is not None:
        # حالتِ تکی (سازگار با قبل)
        raw_readings = [(body.type, body.value)]
    else:
        return 422, error_response(
            "باید 'readings' (batch) یا 'type'+'value' (تکی) ارسال شود",
            "validation_error",
        )

    # 3) batch خالی → ۴۲۲ (قبل از insert، توکن مصرف نمی‌شود)
    if len(raw_readings) == 0:
        return 422, error_response(
            "readings نمی‌تواند خالی باشد (حداقل یک اندازه‌گیری لازم است)",
            "validation_error",
        )

    # 4) Validate همهٔ readings — all-or-nothing: اگر هر کدام نامعتبر باشد →
    #    ۴۲۲ بدونِ هیچ insert و بدونِ mark-used (توکن هنوز قابلِ استفاده است).
    _MAX_READINGS = 10
    if len(raw_readings) > _MAX_READINGS:
        return 422, error_response(
            f"حداکثر {_MAX_READINGS} اندازه‌گیری در یک ارسال مجاز است",
            "validation_error",
        )

    validated: list[tuple[str, float]] = []
    for vtype, vvalue in raw_readings:
        if vtype not in _REPORT_ALLOWED_TYPES:
            allowed = ", ".join(_REPORT_ALLOWED_TYPES.keys())
            return 422, error_response(
                f"نوعِ '{vtype}' مجاز نیست. مقادیرِ مجاز: {allowed}",
                "validation_error",
            )
        lo, hi = _REPORT_ALLOWED_TYPES[vtype]
        if not (lo <= vvalue <= hi):
            return 422, error_response(
                f"مقدارِ {vvalue} برای '{vtype}' خارج از بازهٔ مجاز ({lo}–{hi}) است",
                "validation_error",
            )
        validated.append((vtype, vvalue))

    # 5) Rate-limit — applied after validation (422s don't consume rate-limit slot)
    if not _check_rate_limit(token):
        return 429, error_response("تعداد درخواست‌ها بیش از حد مجاز است", "rate_limit")

    # 6) Set GUC → RLS enforced for all subsequent queries in this connection
    _set_tenant_guc(tenant_id)

    # 7) INSERT همهٔ readings با verified=FALSE, source='patient_self'
    #    all-or-nothing: اگر هر insert خطا دهد، هیچ mark-used نمی‌شود.
    #    (validated کامل شد، پس error در insert غیرمنتظره است — DB constraint/network)
    from django.db import connection as _conn, transaction as _txn
    from django.utils import timezone as _tz
    now_ts = _tz.now()

    # 7+8) INSERT all readings AND mark the token used inside ONE transaction.
    # ATOMIC_REQUESTS is not set (autocommit on, ADR-0008 session-GUC model), so a
    # mid-batch DB error would otherwise partial-commit; wrapping in atomic() gives
    # true all-or-nothing — either every reading is stored and the token consumed,
    # or nothing is and the token stays usable. The session GUC set at step 6
    # (set_config is_local=false) persists inside this block, so RLS still applies;
    # a rollback does NOT reset it (only SET LOCAL would).
    try:
        with _txn.atomic():
            with _conn.cursor() as cursor:
                for vtype, vvalue in validated:
                    cursor.execute(
                        """
                        INSERT INTO clinical.vital_readings
                            (tenant_id, patient_link_id, type, value, unit,
                             measured_at, source, verified, recorded_by)
                        VALUES (%s, %s, %s, %s, %s, %s, 'patient_self', FALSE, 'patient_self_report')
                        """,
                        [
                            tenant_id,
                            patient_link_id,
                            vtype,
                            vvalue,
                            _REPORT_UNIT.get(vtype, ""),
                            now_ts,
                        ],
                    )
            # Mark token used inside the same transaction — rolls back with the
            # inserts if anything fails, so the token is never consumed on error.
            _report_mark_used(token, tenant_id)
    except Exception as exc:
        # بازگشتِ خطای عمومی — جزئیاتِ DB در پاسخ نیست، توکن مصرف نمی‌شود (rollback شد)
        import logging as _logging
        _logging.getLogger(__name__).error(
            "submit_patient_report: DB insert failed for patient_link_id=%s: %s",
            patient_link_id, exc,
        )
        return 422, error_response("خطا در ثبتِ داده — لطفاً دوباره امتحان کنید", "server_error")

    # 9) Build response — سازگار با حالتِ تکی و batch
    accepted_out = [SelfReportReadingOut(type=t, value=v) for t, v in validated]
    first_type, first_value = validated[0]

    return 200, SelfReportOut(
        # backward-compat: تکی → همان type/value قدیمی
        type=first_type if len(validated) == 1 else None,
        value=first_value if len(validated) == 1 else None,
        accepted=accepted_out,
        count=len(accepted_out),
    )


def _report_distinguish_error(token: str):
    """
    Helper: تفکیکِ ۴۰۴ (not found/never issued) از ۴۰۹ (used) از ۴۱۰ (expired).

    این lookup با SECURITY DEFINER‌های موجود کار می‌کند:
      - report_resolve_token فقط used_at IS NULL AND expires_at > now را برمی‌گرداند.
      - برای تفکیک state، یک raw lookup بدونِ RLS لازم داریم.
      - ما از یک helper function دیگر (report_state_token) استفاده نمی‌کنیم
        چون scope را بزرگ نمی‌کنیم.
    پس از مشورتِ security-privacy-advisor: generic 404 ایمن‌تر است.
    فقط برای UX بهتر: اگر token در فرمتِ درستی باشد، ۴۰۹ می‌دهیم وگرنه ۴۰۴.

    تصمیمِ نهایی: همیشه ۴۰۴ (generic) — کمترین information leakage.
    توضیحِ ۴۰۹ به staff (نه در response) داده می‌شود.
    """
    return 404, error_response(
        "توکن معتبر نیست، منقضی شده، یا قبلاً استفاده شده است",
        "token_invalid",
    )
