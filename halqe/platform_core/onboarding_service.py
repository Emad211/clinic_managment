"""
Onboarding service — tenant provisioning for halqe platform.

Layering: این ماژول تنها نقطه‌ای است که platform.provision_tenant را صدا
می‌زند. هیچ SQL مستقیمی جز فراخوانیِ همین تابع اینجا نیست — منطقِ
درج/idempotency در PL/pgSQL تابع است (SECURITY DEFINER).

رمز با bcrypt hash می‌شود — همان الگوی auth_service.py — قبل از ارسال به DB.
رمزِ متنی هرگز در DB ذخیره نمی‌شود.

استفاده:
    from platform_core.onboarding_service import provision_tenant

    result = provision_tenant(
        name="کلینیک نمونه",
        admin_username="admin_clinic",
        password="SecurePass123",
        admin_full_name="دکتر نمونه",
    )
    # result = {"tenant_id": 3, "tenant_name": "کلینیک نمونه",
    #           "admin_username": "admin_clinic"}
"""
from __future__ import annotations

import os
from typing import Optional

import bcrypt
from django.db import connection

from config.env import is_production


class ProvisioningError(Exception):
    """خطای کلیِ provisioning — با پیامِ فارسی/انگلیسی."""
    pass


# ---------------------------------------------------------------------------
# Single-tenant deployment guarantee (MVP step 74 / S2)
# ---------------------------------------------------------------------------
# tenant id=1 is the system/default tenant seeded by slice0; a real pilot clinic
# is the first *provisioned* tenant (id>=2, asserted in test_onboarding). The MVP
# pilot is single-tenant: at most ONE non-default tenant. In PRODUCTION, refuse to
# provision a second non-default tenant unless explicitly acknowledged — clinic #2
# is the T1 trigger, which gets its own full cross-tenant isolation audit.
#
# This is DEFENSE-IN-DEPTH, not the primary control: row isolation is enforced by
# RLS+FORCE on every tenant table (proven by tests/test_rls_coverage.py). The guard
# only reduces blast radius — it stops the realistic accidental path (an operator
# re-running the onboard_tenant CLI for a second clinic) from landing clinic #2's
# real PHI on top of any latent, not-yet-audited isolation regression before T1.
#
# Scope (decided by orchestrator, arbitrating qa-test-advisor [prod-only Python] vs
# security-privacy-advisor [hard DB-level]): the bypass-resistant DB-level guard is
# DEFERRED to the T1/clinic-#2 gate — a uniform DB guard would force the ACK into
# ~10 dev/test provision sites (test_onboarding + test_e2e), heavy churn for a
# defense-in-depth control. This prod-only Python guard covers the realistic CLI
# path; dev/test (is_production False) is untouched, so the multi-tenant isolation
# tests keep provisioning freely.
_SYSTEM_TENANT_ID = 1
_ALLOW_ADDITIONAL_TENANT_ACK = "clinic-2-approved"


def _allow_additional_tenant(environ: dict) -> bool:
    """True only when ALLOW_ADDITIONAL_TENANT carries the exact ACK string."""
    return (environ.get("ALLOW_ADDITIONAL_TENANT", "") or "").strip() == _ALLOW_ADDITIONAL_TENANT_ACK


def _guard_single_tenant(name: str) -> None:
    """
    In production, block provisioning a NEW (second) non-default tenant unless ACKed.

    No-ops outside production, when the ACK is set, or when `name` already exists
    (idempotent re-provisioning of an existing tenant creates nothing → always safe).
    platform.tenants has no tenant_id column, so it is not RLS-protected and the
    app role can read it directly with no GUC dependency.
    """
    if not is_production(os.environ):
        return
    if _allow_additional_tenant(os.environ):
        return

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM platform.tenants WHERE name = %s)", [name]
        )
        name_exists = cursor.fetchone()[0]
        if name_exists:
            return  # idempotent re-provision — never blocked
        cursor.execute(
            "SELECT count(*) FROM platform.tenants WHERE id <> %s", [_SYSTEM_TENANT_ID]
        )
        nondefault_count = cursor.fetchone()[0]

    if nondefault_count >= 1:
        raise ProvisioningError(
            "تضمینِ تک‌مستأجریِ پایلوت: در production نمی‌توان کلینیکِ دوم را provision کرد "
            "(یک مستأجرِ غیرپیش‌فرض از قبل وجود دارد). افزودنِ کلینیکِ دوم تریگرِ T1 است و "
            "نیازِ auditِ ایزولاسیونِ کاملِ چندمستأجری دارد. برای اجازهٔ آگاهانه، متغیرِ محیطیِ "
            f"ALLOW_ADDITIONAL_TENANT={_ALLOW_ADDITIONAL_TENANT_ACK} را ست کنید. "
            "(Single-tenant pilot guarantee — MVP step 74; hard DB-level enforcement deferred to T1.)"
        )


def provision_tenant(
    name: str,
    admin_username: str,
    password: str,
    admin_full_name: Optional[str] = None,
) -> dict:
    """
    ساختِ idempotentِ یک tenant + کاربرِ مدیرِ اولیه.

    آرگومان‌ها:
        name             — نامِ tenant (کلیدِ طبیعی؛ idempotency روی آن است)
        admin_username   — نامِ کاربری مدیر
        password         — رمزِ متنی (hash می‌شود با bcrypt پیش از ارسال)
        admin_full_name  — نامِ کاملِ مدیر (اختیاری)

    خروجی:
        {
            "tenant_id":      int,    # id تازه‌ساخته یا موجود
            "tenant_name":    str,    # همانِ name ورودی
            "admin_username": str,    # نامِ کاربری مدیرِ ثبت‌شده
        }

    تضمین‌ها:
        - idempotent: فراخوانیِ دوباره با همان name → همان tenant_id.
        - رمز با bcrypt hash می‌شود قبل از ارسال به DB.
        - تابعِ SQL با SECURITY DEFINER اجرا می‌شود — RLS را برای این عملِ
          provisioning دور می‌زند بدون اینکه سیاستِ کلیِ RLS تضعیف شود.

    Raises:
        ProvisioningError — اگر DB از تابع خطا بازگرداند یا ارتباط برقرار نشود.
    """
    if not name or not name.strip():
        raise ProvisioningError("نامِ tenant نمی‌تواند خالی باشد.")
    if not admin_username or not admin_username.strip():
        raise ProvisioningError("نامِ کاربری مدیر نمی‌تواند خالی باشد.")
    if not password:
        raise ProvisioningError("رمز نمی‌تواند خالی باشد.")

    # Single-tenant pilot guarantee (step 74 / S2) — prod-only, ACK-overridable,
    # idempotent-safe. No-op in dev/test. See _guard_single_tenant above.
    _guard_single_tenant(name)

    # bcrypt hash — همان الگوی auth_service._make_jwt / auth_service.login
    # gensalt() هر بار salt جدید تولید می‌کند (cost=12 default)
    pw_hash: bytes = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    try:
        with connection.cursor() as cursor:
            # فراخوانیِ تابعِ SECURITY DEFINER — تنها SQL در این سرویس
            # platform_app حقِ EXECUTE این تابع را دارد (slice6)
            cursor.execute(
                "SELECT platform.provision_tenant(%s, %s, %s, %s)",
                [name, admin_username, pw_hash, admin_full_name],
            )
            row = cursor.fetchone()

        if row is None or row[0] is None:
            raise ProvisioningError(
                "provision_tenant: تابعِ DB مقداری برنگرداند."
            )

        tenant_id: int = int(row[0])

    except ProvisioningError:
        raise
    except Exception as exc:
        raise ProvisioningError(
            f"خطا در provisioning tenant '{name}': {exc}"
        ) from exc

    return {
        "tenant_id": tenant_id,
        "tenant_name": name,
        "admin_username": admin_username,
    }
