"""
Patient card token service — خوشهٔ J، قدم ۴۴.

مسئولیت‌ها:
  - issue(patient_link_id, tenant_id, issued_by, ttl_hours): صدورِ توکنِ جدید.
    one-active-at-a-time: توکنِ قبلیِ همان بیمار (در همان tenant) قبل از ساختنِ
    توکنِ جدید revoke می‌شود. برمی‌گرداند: (token_str, expires_at).
  - revoke(token_id, tenant_id): revoke توکن (GUC-scoped، staff-only).
  - resolve_token(token_str): lookup عمومی از طریقِ card_resolve_token() SECURITY
    DEFINER (بدونِ GUC) → dict{patient_link_id, tenant_id} یا None.

معماریِ امنیتی:
  - issue/revoke از مسیرِ JWT + GUC → RLS اعمال می‌شود.
  - resolve_token از card_resolve_token() SECURITY DEFINER استفاده می‌کند که
    RLS را فقط برای lookup عبور می‌دهد.
  - این ماژول هرگز national_id را نمی‌خواند یا برنمی‌گرداند.

LAN-vs-internet gate:
  مسیرِ SMS-link نساخته‌ایم (KYC بلاک). این سرویس فقط LAN (QR/tablet) را
  پشتیبانی می‌کند. ایجادِ لینکِ SMS نیازِ TTLِ کوتاه‌تر، TLS، و رتِ توزیع‌شده دارد.

Rate-limit:
  rate-limitِ in-process (per-process مثلِ specialist_clinic) روی endpoint عمومی
  اعمال می‌شود. برای deployment چند-instance، باید Redis/DB-backed شود.
"""
from __future__ import annotations

import secrets
from datetime import timedelta, timezone

from django.db import connection
from django.utils import timezone as dj_timezone

from clinical.models import PatientCardToken

# TTLِ پیش‌فرض برای LAN (QR/tablet در مطب). برای SMS-link (آینده) کوتاه‌تر شود.
DEFAULT_TTL_HOURS: int = 8


def issue(
    patient_link_id: int,
    tenant_id: int,
    issued_by: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> tuple[str, object]:
    """
    صدورِ توکنِ کارتِ عمومی برای بیمار.

    one-active-at-a-time: ابتدا تمامِ توکن‌های فعالِ قبلیِ همان بیمار در همان
    tenant را revoke می‌کند (UPDATE revoked_at)، سپس توکنِ جدید می‌سازد.

    دلیلِ انجامِ revoke قبل از INSERT:
      اگر staff اشتباهاً دو بار issue کند، توکنِ قبلی فوری غیرفعال می‌شود و
      بیمار نمی‌تواند با توکنِ قدیمی دسترسی داشته باشد (جلوگیری از نشتِ session).

    Args:
      patient_link_id: ID ردیف در clinical.patient_links
      tenant_id: مستأجرِ کاربرِ staff (از JWT)
      issued_by: نامِ کاربرِ staff (برای audit trail)
      ttl_hours: طولِ عمرِ توکن به ساعت (پیش‌فرض ۸ ساعت)

    Returns:
      (token_string, expires_at): توکنِ opaque و زمانِ انقضا (TIMESTAMPTZ)
    """
    now = dj_timezone.now()
    expires_at = now + timedelta(hours=ttl_hours)
    token_str = secrets.token_urlsafe(32)

    # revoke active tokens for this patient in this tenant (one-active-at-a-time)
    PatientCardToken.objects.filter(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    PatientCardToken.objects.create(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        token=token_str,
        expires_at=expires_at,
        issued_by=issued_by,
    )

    return token_str, expires_at


def revoke(token_id: int, tenant_id: int) -> bool:
    """
    Revoke یک توکنِ فعال برای tenant مشخص.

    GUC-scoped: RLS روی clinical.patient_card_tokens این UPDATE را به tenant
    محدود می‌کند. staff نمی‌تواند توکنِ tenantِ دیگر را revoke کند.

    Returns:
      True اگر توکن پیدا شد و revoke شد؛ False اگر پیدا نشد (یا قبلاً revoke بود).
    """
    now = dj_timezone.now()
    updated = PatientCardToken.objects.filter(
        id=token_id,
        tenant_id=tenant_id,
        revoked_at__isnull=True,
    ).update(revoked_at=now)
    return updated > 0


def resolve_token(token_str: str) -> dict | None:
    """
    رزولوِ عمومیِ توکن از طریقِ SECURITY DEFINER function.

    این تابع بدونِ GUC (مسیرِ عمومی) کار می‌کند و card_resolve_token() را که
    RLS را برای همین lookup bypass می‌کند صدا می‌زند.

    اگر توکن معتبر نباشد (ناشناخته، منقضی، revoke‌شده) → None.
    اگر معتبر → {'patient_link_id': int, 'tenant_id': int}.

    ایمنی:
      - این تابع هرگز اطلاعاتِ بیشتری (national_id، نامِ دارو، تشخیص) برنمی‌گرداند.
      - endpoint پس از دریافتِ tenant_id، GUC را ست می‌کند و داده را تحتِ RLS می‌خواند.
      - zero-write: این تابع هیچ چیزی نمی‌نویسد.

    LAN-vs-internet note:
      این تابع in-process است. در future multi-instance deployment، connection
      pooling را در نظر بگیر (set_config is connection-scoped).
    """
    if not token_str:
        return None

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT patient_link_id, tenant_id "
            "FROM clinical.card_resolve_token(%s)",
            [token_str],
        )
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "patient_link_id": row[0],
        "tenant_id": row[1],
    }


def active_for_patient(patient_link_id: int, tenant_id: int) -> PatientCardToken | None:
    """
    توکنِ فعالِ بیمار را برمی‌گرداند (برای staff UI).

    GUC-scoped: RLS این query را به tenant محدود می‌کند.
    Returns: PatientCardToken یا None.
    """
    now = dj_timezone.now()
    return (
        PatientCardToken.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        .order_by("-issued_at")
        .first()
    )


def list_for_patient(patient_link_id: int, tenant_id: int) -> list[PatientCardToken]:
    """
    تاریخچهٔ توکن‌های یک بیمار (برای staff UI — همه، نه فقط فعال).

    GUC-scoped: RLS این query را به tenant محدود می‌کند.
    """
    return list(
        PatientCardToken.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        ).order_by("-issued_at")
    )
