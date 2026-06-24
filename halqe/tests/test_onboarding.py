"""
Onboarding tests — provisioning tenant + admin user.

Coverage:
  1. provision_tenant() یک tenant + کاربرِ مدیر می‌سازد؛ tenant_id ≠ 1 دارد.
  2. idempotent: فراخوانیِ دوباره با همان name → همان tenant_id، بدونِ duplicate.
  3. کاربرِ ساخته‌شده با auth_service.login() قابلِ ورود است (bcrypt معتبر).
  4. provisioning از طریقِ رولِ کم‌امتیازِ platform_app کار می‌کند
     (اثباتِ اینکه EXECUTE GRANT روی تابعِ SECURITY DEFINER درست است).
  5. tenant_id برگشتی ≠ 1 (نشتِ به tenant پیش‌فرض نشده).

همهٔ تست‌ها روی Docker PG16 اجرا می‌شوند (PG_TEST_DSN).
DB بدونِ پیامکِ واقعی — NullProvider — و بدونِ لمسِ accounting.
fixture autouseِ set_default_tenant_guc(1) از conftest نشکسته می‌ماند.
"""
from __future__ import annotations

import uuid
import pytest
import psycopg
import os

from platform_core.onboarding_service import provision_tenant, ProvisioningError

# ---------------------------------------------------------------------------
# Connection helpers — همان الگوی conftest.py
# ---------------------------------------------------------------------------
_PG_HOST = os.environ.get("PG_HOST", "localhost")
_PG_PORT = os.environ.get("PG_PORT", "55432")
_TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
_SU_USER = os.environ.get("PG_USER", "postgres")
_SU_PW   = os.environ.get("PG_PASSWORD", "validate_only")
_APP_USER = os.environ.get("PG_APP_USER", "platform_login_test")
_APP_PW   = os.environ.get("PG_APP_PASSWORD", "test_pw")

_SU_CONNINFO = (
    f"host='{_PG_HOST}' port='{_PG_PORT}' "
    f"user='{_SU_USER}' password='{_SU_PW}' dbname='{_TEST_DB}'"
)
_APP_CONNINFO = (
    f"host='{_PG_HOST}' port='{_PG_PORT}' "
    f"user='{_APP_USER}' password='{_APP_PW}' dbname='{_TEST_DB}'"
)


def _unique_name(prefix: str = "کلینیک_تست") -> str:
    """نامِ یکتا برای هر تست تا از تداخل جلوگیری شود."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Test 1 — provision_tenant یک tenant + کاربر می‌سازد، tenant_id ≠ 1
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_provision_creates_tenant_and_admin_user(seed_data):
    """
    provision_tenant() باید:
      - یک tenant با name منحصربه‌فرد بسازد
      - یک کاربرِ manager برای آن بسازد
      - tenant_id ≠ 1 برگرداند (نشتِ به tenant پیش‌فرض نشده)

    از seed_data استفاده می‌کنیم (نه django_db_setup مستقیم) چون seed_data
    قبلاً sequence را جلو برده — از تداخلِ IDENTITY با tenant 1 موجود جلوگیری می‌شود.
    """
    tenant_name    = _unique_name("کلینیک_نمونه")
    admin_username = f"admin_{uuid.uuid4().hex[:6]}"
    admin_pw       = "SecureTestPw1!"
    admin_fullname = "دکتر تست اول"

    result = provision_tenant(
        name=tenant_name,
        admin_username=admin_username,
        password=admin_pw,
        admin_full_name=admin_fullname,
    )

    # ساختار خروجی
    assert "tenant_id" in result
    assert "tenant_name" in result
    assert "admin_username" in result
    assert result["tenant_name"] == tenant_name
    assert result["admin_username"] == admin_username

    # tenant_id باید ≠ 1 باشد (tenant 1 از قبل موجود است و برای این name جدید است)
    assert result["tenant_id"] != 1, (
        f"tenant_id نباید 1 باشد — tenant پیش‌فرض نباید برگردانده شود؛ "
        f"گرفتیم: {result['tenant_id']}"
    )
    assert result["tenant_id"] > 0

    # تأییدِ مستقیم در DB که tenant و کاربر ساخته شده‌اند
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        t_row = conn.execute(
            "SELECT id, name, is_active FROM platform.tenants WHERE id=%s",
            (result["tenant_id"],)
        ).fetchone()
        assert t_row is not None, "tenant باید در DB موجود باشد"
        assert t_row[1] == tenant_name
        assert t_row[2] is True  # is_active

        u_row = conn.execute(
            "SELECT id, role, app, full_name, is_active FROM platform.users "
            "WHERE tenant_id=%s AND username=%s",
            (result["tenant_id"], admin_username)
        ).fetchone()
        assert u_row is not None, "کاربرِ مدیر باید در DB موجود باشد"
        user_id, role, app, full_name, is_active = u_row
        assert role == "manager", f"نقش باید 'manager' باشد؛ گرفتیم: {role}"
        assert app == "platform", f"app باید 'platform' باشد؛ گرفتیم: {app}"
        assert full_name == admin_fullname
        assert is_active is True


# ---------------------------------------------------------------------------
# Test 2 — idempotent: دوبار = یک ردیف
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_provision_is_idempotent(seed_data):
    """
    فراخوانیِ provision_tenant با همان name دوبار:
      - خطا نمی‌دهد
      - همان tenant_id برمی‌گرداند
      - duplicate ردیف نمی‌سازد
    """
    tenant_name    = _unique_name("کلینیک_idem")
    admin_username = f"admin_idem_{uuid.uuid4().hex[:6]}"
    admin_pw       = "IdemTestPw1!"

    # اولین فراخوانی
    result1 = provision_tenant(
        name=tenant_name,
        admin_username=admin_username,
        password=admin_pw,
    )
    tid = result1["tenant_id"]
    assert tid > 1  # نه tenant پیش‌فرض

    # دومین فراخوانیِ کاملاً مشابه — باید همان tenant_id بازگردد
    result2 = provision_tenant(
        name=tenant_name,
        admin_username=admin_username,
        password=admin_pw,
    )
    assert result2["tenant_id"] == tid, (
        f"فراخوانیِ دوم باید همان tenant_id={tid} بازگرداند؛ "
        f"گرفتیم: {result2['tenant_id']}"
    )

    # شمارشِ ردیف‌ها در DB — نباید duplicate داشته باشیم
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        t_count = conn.execute(
            "SELECT count(*) FROM platform.tenants WHERE name=%s",
            (tenant_name,)
        ).fetchone()[0]
        assert t_count == 1, f"فقط یک tenant با این name باید باشد؛ گرفتیم: {t_count}"

        u_count = conn.execute(
            "SELECT count(*) FROM platform.users WHERE tenant_id=%s AND username=%s",
            (tid, admin_username)
        ).fetchone()[0]
        assert u_count == 1, f"فقط یک کاربر باید باشد؛ گرفتیم: {u_count}"


# ---------------------------------------------------------------------------
# Test 3 — کاربرِ ساخته‌شده با auth_service.login قابلِ ورود است
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_provisioned_user_can_login(seed_data):
    """
    کاربرِ مدیری که با provision_tenant ساخته شده باید بتواند
    از طریقِ auth_service.login() وارد شود — bcrypt hash معتبر است.
    """
    from platform_core.auth_service import login, InvalidCredentials
    import jwt as pyjwt
    from django.conf import settings

    tenant_name    = _unique_name("کلینیک_login")
    admin_username = f"admin_login_{uuid.uuid4().hex[:6]}"
    admin_pw       = "LoginTestPw1!"

    result = provision_tenant(
        name=tenant_name,
        admin_username=admin_username,
        password=admin_pw,
    )
    new_tid = result["tenant_id"]

    # login باید موفق شود
    token = login(admin_username, admin_pw)
    assert token, "auth_service.login باید توکن بازگرداند"

    # توکن باید tenant_id درست داشته باشد
    claims = pyjwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    assert claims["tenant_id"] == new_tid, (
        f"توکن باید tenant_id={new_tid} داشته باشد؛ گرفتیم: {claims['tenant_id']}"
    )
    assert claims["role"] == "manager", (
        f"توکن باید role='manager' داشته باشد؛ گرفتیم: {claims['role']}"
    )

    # رمزِ اشتباه باید InvalidCredentials بدهد
    with pytest.raises(InvalidCredentials):
        login(admin_username, "wrong_password_for_this_user")


# ---------------------------------------------------------------------------
# Test 4 — کار از طریقِ رولِ کم‌امتیاز (EXECUTE GRANT اثبات می‌شود)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_provision_works_via_app_role(seed_data):
    """
    تابعِ platform.provision_tenant از طریقِ رولِ کم‌امتیازِ platform_app
    (که platform_login_test از آن ارث می‌برد) قابلِ فراخوانی است.

    این تست نشان می‌دهد EXECUTE GRANT روی تابعِ SECURITY DEFINER درست کار می‌کند.
    Django ORM از همین رول استفاده می‌کند — پس اگر provision_tenant() در تستِ Django
    کار کند، proof است که GRANT EXECUTE ... TO platform_app فعال است.

    برای تأیید اضافی، مستقیماً با psycopg از رولِ app‌ هم فراخوانی می‌کنیم.
    """
    tenant_name    = _unique_name("کلینیک_approle")
    admin_username = f"admin_ar_{uuid.uuid4().hex[:6]}"
    admin_pw       = "AppRoleTestPw1!"

    # ۱) از طریقِ Django ORM (که با platform_login_test وصل می‌شود)
    result = provision_tenant(
        name=tenant_name,
        admin_username=admin_username,
        password=admin_pw,
    )
    assert result["tenant_id"] > 1

    # ۲) مستقیم با psycopg از رولِ app — باید EXECUTE GRANT داشته باشد
    import bcrypt as _bcrypt
    pw_hash = _bcrypt.hashpw(b"another_pw", _bcrypt.gensalt())

    tenant_name2    = _unique_name("کلینیک_approle2")
    admin_username2 = f"admin_ar2_{uuid.uuid4().hex[:6]}"

    with psycopg.connect(_APP_CONNINFO, autocommit=True) as conn:
        # GUC ست می‌کنیم (مثلِ اتصالِ معمولِ app) — اما SECURITY DEFINER آن را نادیده می‌گیرد
        conn.execute("SELECT set_config('app.current_tenant', '1', false)")

        row = conn.execute(
            "SELECT platform.provision_tenant(%s, %s, %s, %s)",
            [tenant_name2, admin_username2, pw_hash, None]
        ).fetchone()

        assert row is not None, "تابع باید مقدار برگرداند"
        new_tid2 = row[0]
        assert new_tid2 is not None and new_tid2 > 1, (
            f"tenant_id باید > 1 باشد؛ گرفتیم: {new_tid2}"
        )

    # تأیید در DB
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        u_row = conn.execute(
            "SELECT role FROM platform.users WHERE tenant_id=%s AND username=%s",
            (new_tid2, admin_username2)
        ).fetchone()
        assert u_row is not None, "کاربر باید در DB ساخته شده باشد"
        assert u_row[0] == "manager"


# ---------------------------------------------------------------------------
# Test 5 — tenant_id ≠ 1 (گارد در برابرِ نشتِ به tenant پیش‌فرض)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_provisioned_tenant_id_is_not_1(seed_data):
    """
    هر tenant جدیدی که ساخته می‌شود باید id ≠ 1 داشته باشد.
    tenant 1 (پیش‌فرض) از قبل موجود است و نباید به‌عنوانِ خروجی برگردانده شود
    مگر اینکه مستقیماً همان name=«پیش‌فرض» درخواست شده باشد.
    """
    # با name کاملاً جدید
    result = provision_tenant(
        name=_unique_name("کلینیک_t1guard"),
        admin_username=f"admin_g1_{uuid.uuid4().hex[:6]}",
        password="GuardPw1!",
    )
    assert result["tenant_id"] != 1, (
        f"tenant_id نباید 1 باشد برای نامِ جدید؛ گرفتیم: {result['tenant_id']}"
    )

    # و باید بزرگ‌تر از صفر باشد
    assert result["tenant_id"] > 0


# ---------------------------------------------------------------------------
# Test 6 — ورودیِ نامعتبر: name خالی یا username خالی
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_provision_raises_on_empty_name(seed_data):
    """name خالی باید ProvisioningError بدهد، نه خطای DB."""
    with pytest.raises(ProvisioningError):
        provision_tenant(name="", admin_username="user1", password="pw1!")


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_provision_raises_on_empty_username(seed_data):
    """admin_username خالی باید ProvisioningError بدهد."""
    with pytest.raises(ProvisioningError):
        provision_tenant(
            name=_unique_name("کلینیک_val"),
            admin_username="",
            password="pw1!",
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_provision_raises_on_empty_password(seed_data):
    """password خالی باید ProvisioningError بدهد."""
    with pytest.raises(ProvisioningError):
        provision_tenant(
            name=_unique_name("کلینیک_val2"),
            admin_username="admin_val",
            password="",
        )
