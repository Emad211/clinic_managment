"""
clinical/report_token_service.py — Patient self-report token service (slice13, step 45).

مسئولیت‌ها:
  - issue(patient_link_id, tenant_id, issued_by, ttl_hours):
      صدورِ توکنِ یک‌بارمصرفِ جدید برای self-report بیمار.
      برمی‌گرداند: (token_str, expires_at).

  - resolve_token(token_str):
      lookup عمومی از طریقِ report_resolve_token() SECURITY DEFINER (بدونِ GUC).
      برمی‌گرداند: dict{patient_link_id, tenant_id} یا None.

  - mark_used(token_str, tenant_id):
      توکن را یک‌بارمصرف می‌کند (UPDATE used_at). باید بعد از INSERT موفق فراخوانده شود.

معماریِ امنیتی:
  - issue از مسیرِ JWT + GUC → RLS اعمال می‌شود.
  - resolve_token از report_resolve_token() SECURITY DEFINER استفاده می‌کند که
    RLS را فقط برای lookup عبور می‌دهد (همانِ الگوی slice7/slice12).
  - mark_used با GUC ست‌شده (از resolve_token + set_tenant_guc) صدا می‌شود.
  - این ماژول هرگز national_id را نمی‌خواند یا برنمی‌گرداند.

جدا از card_token_service:
  - card_token: read-path/LAN/one-active-at-a-time/revokeable.
  - report_token: write-path/one-time-use/no-revoke (used_at ست می‌شود).

scope جداگانه (security-privacy-advisor):
  - توکنِ کارت نمی‌تواند برای self-report استفاده شود و بالعکس.
  - endpoint /patient-report/{token} فقط report_resolve_token را می‌پذیرد.
  - endpoint /card/{token} فقط card_resolve_token را می‌پذیرد.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import connection
from django.utils import timezone as dj_timezone

from clinical.models import PatientReportToken

# TTL پیش‌فرض برای self-report (۲۴ ساعت)
DEFAULT_TTL_HOURS: int = 24


def issue(
    patient_link_id: int,
    tenant_id: int,
    issued_by: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> tuple[str, object]:
    """
    صدورِ توکنِ یک‌بارمصرفِ self-report برای بیمار.

    برخلافِ card_token که one-active-at-a-time است، report_token چندگانه
    می‌تواند وجود داشته باشد (هر بار که staff issue می‌کند یک توکنِ جدید می‌سازد).
    اما چون هر توکن one-time است، فقط اولین استفاده موفق می‌شود.

    Args:
      patient_link_id: ID ردیف در clinical.patient_links
      tenant_id: مستأجرِ کاربرِ staff (از JWT)
      issued_by: نامِ کاربرِ staff (برای audit trail)
      ttl_hours: طولِ عمرِ توکن به ساعت (پیش‌فرض ۲۴ ساعت)

    Returns:
      (token_string, expires_at): توکنِ opaque و زمانِ انقضا (TIMESTAMPTZ)
    """
    now = dj_timezone.now()
    expires_at = now + timedelta(hours=ttl_hours)
    token_str = secrets.token_urlsafe(32)

    PatientReportToken.objects.create(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        token=token_str,
        expires_at=expires_at,
        issued_by=issued_by,
    )

    return token_str, expires_at


def resolve_token(token_str: str) -> dict | None:
    """
    رزولوِ عمومیِ توکنِ self-report از طریقِ SECURITY DEFINER function.

    این تابع بدونِ GUC (مسیرِ عمومی) کار می‌کند و report_resolve_token() را که
    RLS را برای همین lookup bypass می‌کند صدا می‌زند.

    شرطِ اعتبار (در تابعِ DB اعمال می‌شود):
      - used_at IS NULL (هنوز استفاده‌نشده)
      - expires_at > now() (منقضی‌نشده)

    اگر هر یک نقض شود → None.

    Returns: {'patient_link_id': int, 'tenant_id': int} یا None.

    ایمنی:
      - این تابع هرگز اطلاعاتِ بیشتری (national_id، نامِ دارو، تشخیص) برنمی‌گرداند.
      - endpoint پس از دریافتِ tenant_id، GUC را ست می‌کند و داده را تحتِ RLS می‌نویسد.
      - scope جدا: این تابع فقط patient_report_tokens را می‌خواند، نه card_tokens.
    """
    if not token_str:
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT patient_link_id, tenant_id "
            "FROM clinical.report_resolve_token(%s)",
            [token_str],
        )
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "patient_link_id": row[0],
        "tenant_id": row[1],
    }


def mark_used(token_str: str, tenant_id: int) -> bool:
    """
    توکن را یک‌بارمصرف می‌کند (UPDATE used_at=now()).

    باید بعد از INSERT موفقِ vital_reading فراخوانده شود.
    اگر توکن پیدا نشد (یا قبلاً used) → False.

    GUC-scoped: RLS این UPDATE را به tenant محدود می‌کند.
    Note: caller باید set_tenant_guc(tenant_id) را قبل از فراخوانی ست کرده باشد.
    """
    now = dj_timezone.now()
    updated = PatientReportToken.objects.filter(
        token=token_str,
        tenant_id=tenant_id,
        used_at__isnull=True,
    ).update(used_at=now)
    return updated > 0
