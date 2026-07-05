"""
clinical/allergy_service.py — Allergy CRUD service (فاز ۱ کاکپیت).

مسئولیت
────────
منطقِ نوشتن/خواندنِ حساسیت‌های بیمار روی جدولِ کانونیِ ``clinical.allergies``
(slice2 + slice18). router نازک است و همهٔ کوئری/درج/حذف اینجا (لایهٔ سرویس/ORM)
انجام می‌شود — هیچ SQLِ خامی در route.

قواعدِ نوشتن
────────────
  - Tenant scoping: هر کوئری روی (tenant_id) فیلتر می‌شود؛ set_tenant_guc پیش از
    هر عملیات ست می‌شود تا RLS (slice5) دقیقاً همان مستأجر را ببیند. مسیرِ حذف
    با tenant_id فیلتر می‌شود تا مستأجرِ دیگر نتواند ردیفِ کسی را probe/حذف کند.
  - severity: DB یک CHECK دارد (slice4a): NULL | mild | moderate | severe |
    anaphylaxis. سرویس severity را پیش از درج اعتبارسنجی می‌کند و در صورتِ
    نامعتبر بودن ``InvalidAllergySeverity`` می‌اندازد (تا router به 422 نگاشت کند
    و به‌جای CheckViolationِ خام یک پیامِ روشن برگردد). رشتهٔ خالی → NULL.
  - substance اجباری است (NOT NULL در DB)؛ خالی/فضای‌سفید → ``AllergyValidationError``.
  - created_at: پیش‌فرضِ DB now() است — در INSERT پاس داده نمی‌شود تا DB مهرِ زمان
    بزند (وقتِ ایران via USE_TZ=True/Asia/Tehran؛ معادلِ iran_now).

Audit
─────
  add/delete هر دو یک ردیف به ``clinical.activity_logs`` می‌افزایند (best-effort؛
  شکستِ audit عملیاتِ اصلی را متوقف نمی‌کند) via ``clinical.audit.log_activity``.
    action_type     = 'allergy_added' | 'allergy_deleted'
    action_category = 'clinical'
    target_table    = 'allergies'
    target_id       = PK ردیفِ ساخته/حذف‌شده
    patient_link_id = allergy.patient_link_id
"""
from __future__ import annotations

from typing import Optional

from clinical.models import Allergy
from clinical.audit import log_activity
from platform_core.tenant_context import set_tenant_guc


# ---------------------------------------------------------------------------
# مقادیرِ مجازِ severity — آینهٔ CHECKِ DB (slice4a). NULL هم مجاز است.
# منبعِ حقیقت خودِ DB است؛ این‌جا فقط برای پیامِ خطای بهترِ زودهنگام تکرار شده.
# ---------------------------------------------------------------------------
ALLOWED_SEVERITIES = frozenset({"mild", "moderate", "severe", "anaphylaxis"})


# ---------------------------------------------------------------------------
# Exceptions — router این‌ها را به کدهای HTTP نگاشت می‌کند.
# ---------------------------------------------------------------------------
class AllergyServiceError(Exception):
    """پایهٔ خطاهای سرویسِ allergy."""


class AllergyValidationError(AllergyServiceError):
    """substance خالی/نامعتبر → 422."""


class InvalidAllergySeverity(AllergyServiceError):
    """severity خارج از مجموعهٔ مجاز → 422."""


class AllergyNotFound(AllergyServiceError):
    """ردیفِ allergy برای این (id, tenant) پیدا نشد → 404."""


# ---------------------------------------------------------------------------
# خواندن — حساسیت‌های یک بیمار (tenant-scoped، جدیدترین اول)
# ---------------------------------------------------------------------------
def list_allergies(*, tenant_id: int, patient_link_id: int) -> list[Allergy]:
    """
    فهرستِ حساسیت‌های یک بیمار برای این مستأجر (جدیدترین اول).

    RLS: GUC ست می‌شود؛ فیلترِ صریحِ tenant_id هم به‌عنوانِ دفاعِ لایه‌ایِ دوم.
    ordering از Meta.ordering مدل (-created_at) می‌آید.
    """
    set_tenant_guc(tenant_id)
    return list(
        Allergy.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        )
    )


# ---------------------------------------------------------------------------
# نوشتن — افزودنِ یک حساسیت
# ---------------------------------------------------------------------------
def _clean_severity(severity: Optional[str]) -> Optional[str]:
    """
    severity را نرمال می‌کند: رشتهٔ خالی/فضای‌سفید → None؛ در غیرِ این‌صورت باید
    عضوِ ALLOWED_SEVERITIES باشد (آینهٔ CHECKِ DB) وگرنه InvalidAllergySeverity.
    """
    if severity is None:
        return None
    s = severity.strip()
    if s == "":
        return None
    if s not in ALLOWED_SEVERITIES:
        raise InvalidAllergySeverity(
            f"severity={severity!r} نامعتبر است. مقادیرِ مجاز: "
            f"{sorted(ALLOWED_SEVERITIES)} یا خالی."
        )
    return s


def add_allergy(
    *,
    tenant_id: int,
    patient_link_id: int,
    substance: str,
    severity: Optional[str] = None,
    note: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> Allergy:
    """
    افزودنِ یک ردیفِ حساسیت برای بیمار + لاگِ activity.

    - substance اجباری (trim می‌شود؛ خالی → AllergyValidationError).
    - severity اعتبارسنجی می‌شود (خالی → NULL؛ نامعتبر → InvalidAllergySeverity).
    - note اختیاری (رشتهٔ خالی → NULL برای تمیزی).
    - created_at پاس داده نمی‌شود → DB با now() مهر می‌زند.
    - tenant_id روی خودِ ردیف نوشته می‌شود؛ set_tenant_guc پیش از درج تا
      WITH CHECKِ RLS اجازه دهد.

    راه‌اندازیِ منطقِ خواننده روی این ردیف در لایهٔ بالینی خارج از scope است.
    """
    set_tenant_guc(tenant_id)

    clean_substance = (substance or "").strip()
    if clean_substance == "":
        raise AllergyValidationError("نامِ مادهٔ حساسیت‌زا (substance) الزامی است.")

    clean_severity = _clean_severity(severity)
    clean_note = note.strip() if note and note.strip() else None

    allergy = Allergy.objects.create(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        substance=clean_substance,
        severity=clean_severity,
        note=clean_note,
    )

    # Audit — نوشتنِ state-changing، append-only، best-effort.
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_id,
        username=actor_username,
        action_type="allergy_added",
        action_category="clinical",
        target_table="allergies",
        target_id=allergy.id,
        patient_link_id=patient_link_id,
        description=f"substance={clean_substance}, severity={clean_severity}",
    )
    return allergy


# ---------------------------------------------------------------------------
# حذف — حذفِ یک حساسیت (tenant-scoped)
# ---------------------------------------------------------------------------
def delete_allergy(
    *,
    tenant_id: int,
    patient_link_id: int,
    allergy_id: int,
    actor_username: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> None:
    """
    حذفِ یک ردیفِ حساسیت + لاگِ activity.

    - با (id, tenant_id, patient_link_id) فیلتر می‌شود تا حذفِ cross-tenant یا
      حذفِ ردیفی که به این بیمار تعلق ندارد ممکن نباشد.
    - اگر ردیف پیدا نشد → AllergyNotFound (router → 404).
    """
    set_tenant_guc(tenant_id)

    try:
        allergy = Allergy.objects.get(
            id=allergy_id,
            tenant_id=tenant_id,
            patient_link_id=patient_link_id,
        )
    except Allergy.DoesNotExist:
        raise AllergyNotFound(
            f"Allergy id={allergy_id} برای این بیمار/مستأجر پیدا نشد."
        )

    substance = allergy.substance
    allergy.delete()

    # Audit — نوشتنِ state-changing، append-only، best-effort.
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_id,
        username=actor_username,
        action_type="allergy_deleted",
        action_category="clinical",
        target_table="allergies",
        target_id=allergy_id,
        patient_link_id=patient_link_id,
        description=f"substance={substance}",
    )
