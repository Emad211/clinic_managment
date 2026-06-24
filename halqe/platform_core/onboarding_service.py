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

from typing import Optional

import bcrypt
from django.db import connection


class ProvisioningError(Exception):
    """خطای کلیِ provisioning — با پیامِ فارسی/انگلیسی."""
    pass


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
