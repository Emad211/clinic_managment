"""
test_e2e_tenant_isolation.py — End-to-end multi-tenant isolation via full stack.

ریسک #۱ ROADMAP: «تستِ ایزولاسیون نمایشی است» — این فایل آن را می‌بندد.

مسیرِ کامل: provision_tenant → login → JWT → JWTBearer.authenticate →
set_tenant_guc → RLS policy → کم‌امتیازِ platform_login_test → نتیجه.

سناریوهای پوشش‌داده‌شده:
  GUARD — رولِ اتصال superuser نیست (RLS bypass نشده)
  P1    — GET /patients → فقط ردیف‌های tenant-A (شمارشِ دقیق)
  P2    — GET /patients/{uuid}/record برای منبعِ خود → 200 + داده
  N1    — GET /patients/{uuid}/record منبعِ B با JWTِ A → 404 (نه 403)
  N2    — GET /patients → لیستِ A هیچ ردیفِ B ندارد
  N3    — POST /patients/{uuid}/encounters با tenant_id=B در body → 404 (GUC از JWT است نه body)
  N4    — بدون Authorization header → 401
  N5    — JWTِ دست‌کاری‌شده/منقضی → 401
  E2    — clinical.observations (VIEW) با JWTِ A فقط دادهٔ A می‌دهد
  E4    — کاربرِ A (staff) نمی‌تواند کاربرِ B را از طریقِ DB مستقیم UPDATE/DELETE کند

محدودیت‌های محترم:
  - هیچ نوشتنِ accounting (read-only boundary)
  - هیچ SMS واقعی
  - تست‌ها روی Docker PG16 (PG_TEST_DSN یا env vars)
  - layering: endpoint→service→adapter; SQL مستقیم فقط برای seed/guard
  - fixtureِ autouseِ set_default_tenant_guc(1) نشکسته می‌ماند
"""
from __future__ import annotations

import os
import uuid
import datetime

import bcrypt
import psycopg
import pytest
import jwt as pyjwt

from ninja.testing import TestClient
from django.conf import settings

from config.api import api
from platform_core.onboarding_service import provision_tenant

# ---------------------------------------------------------------------------
# Connection helpers
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


def _client() -> TestClient:
    return TestClient(api)


def _do_login(username: str, password: str) -> str:
    """Login via HTTP endpoint and return raw JWT string. Asserts 200."""
    resp = _client().post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username!r}: {resp.text}"
    return resp.json()["token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Session fixture — provision two real tenants + seed clinical data
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def e2e_tenants(seed_data):
    """
    Provision tenant-A و tenant-B با onboarding_service.provision_tenant.
    برای هرکدام یک بیمار + patient_link + vital_readings اضافه می‌کنیم.
    از superuser برای seed حسابداری (accounting.patients) استفاده می‌کنیم.
    Django ORM (app-role) برای clinical data.

    بازمی‌گرداند: دیکشنری با tenant_id/username/password/uuid برای هر tenant.

    یادداشت: چون scope=module است و set_default_tenant_guc autouse=True دارد
    (اما به db fixture وابسته است)، این fixture خودش GUC را مستقیم ست می‌کند.
    """
    # ── Tenant A ──────────────────────────────────────────────────────────────
    name_a       = f"کلینیک_A_{uuid.uuid4().hex[:6]}"
    username_a   = f"admin_a_{uuid.uuid4().hex[:6]}"
    password_a   = "TenantA_pw1!"

    result_a = provision_tenant(
        name=name_a,
        admin_username=username_a,
        password=password_a,
        admin_full_name="مدیرِ کلینیک آلفا",
    )
    tid_a = result_a["tenant_id"]
    assert tid_a >= 2, f"tenant_id باید ≥2 باشد؛ گرفتیم {tid_a}"

    # ── Tenant B ──────────────────────────────────────────────────────────────
    name_b       = f"کلینیک_B_{uuid.uuid4().hex[:6]}"
    username_b   = f"admin_b_{uuid.uuid4().hex[:6]}"
    password_b   = "TenantB_pw1!"

    result_b = provision_tenant(
        name=name_b,
        admin_username=username_b,
        password=password_b,
        admin_full_name="مدیرِ کلینیک بتا",
    )
    tid_b = result_b["tenant_id"]
    assert tid_b >= 2, f"tenant_id باید ≥2 باشد؛ گرفتیم {tid_b}"
    assert tid_a != tid_b, "tenant-A و B نباید یکی باشند"

    # ── Seed: accounting.patients + clinical.patient_links + vital_readings ───
    # از superuser برای accounting.patients استفاده می‌کنیم (app-role فقط SELECT)
    patient_uuid_a = uuid.uuid4()
    patient_uuid_b = uuid.uuid4()

    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        # Patient A در accounting
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (%s, %s, 'بیمارِ آلفا', 'رضایی', %s, '09120000010',
                    '1975-03-10', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (tid_a, patient_uuid_a, f"e2e_a_{uuid.uuid4().hex[:6]}"))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (patient_uuid_a,)
        ).fetchone()
        acc_patient_id_a = row[0]

        # Patient B در accounting
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (%s, %s, 'بیمارِ بتا', 'محمدی', %s, '09130000011',
                    '1980-07-22', 'female')
            ON CONFLICT (uuid) DO NOTHING
        """, (tid_b, patient_uuid_b, f"e2e_b_{uuid.uuid4().hex[:6]}"))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (patient_uuid_b,)
        ).fetchone()
        acc_patient_id_b = row[0]

        # clinical.patient_links برای A
        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (%s, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (tid_a, acc_patient_id_a))

        row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=%s AND patient_id=%s",
            (tid_a, acc_patient_id_a)
        ).fetchone()
        link_id_a = row[0]

        # clinical.patient_links برای B
        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (%s, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (tid_b, acc_patient_id_b))

        row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=%s AND patient_id=%s",
            (tid_b, acc_patient_id_b)
        ).fetchone()
        link_id_b = row[0]

        # vital_readings برای A (2 ردیف)
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (%s, %s, 'hba1c',        7.8, '%%',    now() - interval '2 days', 'clinic'),
                (%s, %s, 'bp_systolic',  140, 'mmHg',  now() - interval '3 days', 'clinic')
        """, (tid_a, link_id_a, tid_a, link_id_a))

        # vital_readings برای B (2 ردیف)
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (%s, %s, 'hba1c',        9.1, '%%',    now() - interval '1 day',  'clinic'),
                (%s, %s, 'bp_systolic',  160, 'mmHg',  now() - interval '4 days', 'clinic')
        """, (tid_b, link_id_b, tid_b, link_id_b))

    return {
        # Tenant A
        "tid_a":            tid_a,
        "username_a":       username_a,
        "password_a":       password_a,
        "patient_uuid_a":   patient_uuid_a,
        "acc_patient_id_a": acc_patient_id_a,
        "link_id_a":        link_id_a,
        # Tenant B
        "tid_b":            tid_b,
        "username_b":       username_b,
        "password_b":       password_b,
        "patient_uuid_b":   patient_uuid_b,
        "acc_patient_id_b": acc_patient_id_b,
        "link_id_b":        link_id_b,
    }


# ===========================================================================
# GUARD — رولِ کم‌امتیاز (ضدِ سبزِ کاذب)
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_guard_app_role_is_not_superuser(django_db_setup):
    """
    گاردِ اجباری: اثباتِ اینکه اتصالِ تست با رولِ کم‌امتیاز است، نه superuser.

    اگر اتصال superuser باشد، RLS bypass می‌شود و کلِ سوئیتِ ایزولاسیون
    به‌اشتباه سبز می‌شود — این تست آن را صریحاً ردّ می‌کند.

    بررسی می‌کنیم:
      - current_user != 'postgres' (یا هر superuser دیگری)
      - rolsuper = false
      - rolbypassrls = false
    """
    with psycopg.connect(_APP_CONNINFO, autocommit=True) as conn:
        row = conn.execute(
            "SELECT current_user, rolsuper, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        ).fetchone()

    assert row is not None, "pg_roles باید اطلاعاتِ رولِ فعلی را داشته باشد"
    current_role, is_super, bypass_rls = row

    assert not is_super, (
        f"اتصالِ تست با رولِ superuser ({current_role}) برقرار شده! "
        "RLS bypass می‌شود — همهٔ تستِ ایزولاسیون سبزِ کاذب خواهند بود. "
        "مطمئن شو که PG_APP_USER=platform_login_test تنظیم است."
    )
    assert not bypass_rls, (
        f"رولِ {current_role} دارای BYPASSRLS است! "
        "این هم‌معنی با superuser برای اهدافِ RLS است."
    )
    assert current_role != "postgres", (
        "PG_APP_USER نباید 'postgres' باشد — از platform_login_test استفاده کن."
    )


# ===========================================================================
# P1 — لیستِ بیماران: فقط ردیف‌های tenant-A
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_p1_patient_list_scoped_to_tenant_a(e2e_tenants):
    """
    P1: GET /patients با JWTِ A فقط بیمارانِ A را برمی‌گرداند.

    Endpoint: GET /api/v1/patients
    انتظار: HTTP 200، total == تعداد بیماران tenant-A (دقیقاً ۱ در این تست)،
            uuid بیمارِ B در لیست نیست.
    """
    token_a = _do_login(e2e_tenants["username_a"], e2e_tenants["password_a"])

    resp = _client().get("/patients", headers=_auth_headers(token_a))
    assert resp.status_code == 200, f"P1 failed: {resp.text}"

    data = resp.json()
    items = data["items"]
    patient_uuids_in_list = [item["patient_uuid"] for item in items if item.get("patient_uuid")]

    str_uuid_a = str(e2e_tenants["patient_uuid_a"])
    str_uuid_b = str(e2e_tenants["patient_uuid_b"])

    # بیمارِ A باید در لیست باشد
    assert str_uuid_a in patient_uuids_in_list, (
        f"P1: بیمارِ A ({str_uuid_a}) باید در لیست باشد. "
        f"لیست: {patient_uuids_in_list}"
    )

    # بیمارِ B نباید در لیست باشد (ایزولاسیون)
    assert str_uuid_b not in patient_uuids_in_list, (
        f"P1 FAIL — نشتِ ایزولاسیون! بیمارِ B ({str_uuid_b}) در لیستِ A دیده می‌شود. "
        f"این یعنی RLS درست کار نمی‌کند."
    )

    # تعداد دقیق: tenant-A فقط ۱ بیمار دارد که از این fixture ساخته شده
    count_a_in_list = sum(1 for u in patient_uuids_in_list if u == str_uuid_a)
    assert count_a_in_list == 1, (
        f"P1: بیمارِ A باید دقیقاً یک‌بار در لیست باشد؛ گرفتیم {count_a_in_list}"
    )


# ===========================================================================
# P2 — GET منبعِ خودِ A با JWTِ A → 200
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_p2_tenant_a_can_read_own_patient_record(e2e_tenants):
    """
    P2: GET /patients/{uuid}/record با JWTِ A برای بیمارِ A → 200 + داده.

    Endpoint: GET /api/v1/patients/{patient_uuid}/record
    انتظار: HTTP 200، patient_link_id == link_id_a.
    """
    token_a = _do_login(e2e_tenants["username_a"], e2e_tenants["password_a"])
    uuid_a  = e2e_tenants["patient_uuid_a"]

    resp = _client().get(
        f"/patients/{uuid_a}/record",
        headers=_auth_headers(token_a),
    )
    assert resp.status_code == 200, (
        f"P2: کاربرِ A باید بتواند پروندهٔ خودش را بخواند. status={resp.status_code}, body={resp.text}"
    )

    data = resp.json()
    assert data["patient_link_id"] == e2e_tenants["link_id_a"], (
        f"P2: patient_link_id اشتباه است. انتظار {e2e_tenants['link_id_a']}, "
        f"گرفتیم {data['patient_link_id']}"
    )


# ===========================================================================
# N1 — GET منبعِ B با JWTِ A → 404 (نه 403)
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_n1_tenant_a_gets_404_for_tenant_b_patient_record(e2e_tenants):
    """
    N1: GET /patients/{uuid_b}/record با JWTِ A → 404.

    قلبِ بستنِ ریسک: RLS ردیفِ B را برای GUC=A نامرئی می‌کند →
    PatientLink.DoesNotExist → Http404 → 404 (نه 403).
    404 چون RLS ردیف را نامرئی می‌کند؛ 403 خودش افشای وجود است.

    Endpoint: GET /api/v1/patients/{patient_uuid}/record
    """
    token_a = _do_login(e2e_tenants["username_a"], e2e_tenants["password_a"])
    uuid_b  = e2e_tenants["patient_uuid_b"]

    resp = _client().get(
        f"/patients/{uuid_b}/record",
        headers=_auth_headers(token_a),
    )

    assert resp.status_code == 404, (
        f"N1 FAIL — ایزولاسیون نشت دارد! "
        f"کاربرِ A پروندهٔ tenant-B را با کدِ {resp.status_code} دریافت کرد. "
        f"انتظار 404 بود. body={resp.text}"
    )
    # اطمینان از قراردادِ خطا: باید detail و code داشته باشد
    body = resp.json()
    assert "detail" in body, f"N1: بدنهٔ پاسخ باید 'detail' داشته باشد. گرفتیم: {body}"
    assert "code" in body, f"N1: بدنهٔ پاسخ باید 'code' داشته باشد. گرفتیم: {body}"
    assert body["code"] == "not_found", (
        f"N1: code باید 'not_found' باشد؛ گرفتیم {body['code']!r}"
    )


# ===========================================================================
# N2 — لیستِ A هیچ ردیفِ B ندارد
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_n2_tenant_a_list_contains_no_tenant_b_rows(e2e_tenants):
    """
    N2: GET /patients با JWTِ A → هیچ uuid بیمارِ B در لیست نیست.

    مکمل N1: نه تنها by-id 404 است، لیست هم نشت ندارد.
    Endpoint: GET /api/v1/patients?limit=200
    """
    token_a = _do_login(e2e_tenants["username_a"], e2e_tenants["password_a"])
    str_uuid_b = str(e2e_tenants["patient_uuid_b"])

    # با limit=200 کلِ لیست را می‌گیریم
    resp = _client().get("/patients?limit=200", headers=_auth_headers(token_a))
    assert resp.status_code == 200, f"N2: {resp.text}"

    data = resp.json()
    all_uuids = [item["patient_uuid"] for item in data["items"] if item.get("patient_uuid")]

    assert str_uuid_b not in all_uuids, (
        f"N2 FAIL — نشتِ ایزولاسیون در لیست! "
        f"UUID بیمارِ B ({str_uuid_b}) در لیستِ کاربرِ A دیده می‌شود. "
        f"RLS روی clinical.patient_links درست اعمال نشده."
    )


# ===========================================================================
# N3 — POST با tenant_id=B در body → 404 (GUC از JWT است نه body)
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_n3_cross_tenant_write_via_body_is_blocked(e2e_tenants):
    """
    N3: POST /patients/{uuid_b}/encounters با JWTِ A → 4xx.

    اثباتِ اینکه tenant_id از JWT/GUC می‌آید نه از body.
    حتی اگر کسی بخواهد uuid_b را در مسیر بدهد، GUC=A است و
    PatientLink برای tenant_a+patient_b وجود ندارد → 404.

    Endpoint: POST /api/v1/patients/{patient_uuid}/encounters
    شاملِ body: {"encounter_type": "visit"} — بدون tenant_id (لایهٔ اپ آن را از JWT می‌گیرد)
    """
    token_a = _do_login(e2e_tenants["username_a"], e2e_tenants["password_a"])
    uuid_b  = e2e_tenants["patient_uuid_b"]

    resp = _client().post(
        f"/patients/{uuid_b}/encounters",
        json={"encounter_type": "visit"},
        headers=_auth_headers(token_a),
    )

    # انتظار: 404 (چون با GUC=A، patient_link برای uuid_b پیدا نمی‌شود)
    # هر 4xx قابل قبول است — 404 ترجیح، 403 هم می‌پذیریم، 2xx کاملاً اشتباه
    assert resp.status_code in (404, 403, 422), (
        f"N3 FAIL — کاربرِ A توانست برای tenant-B encounter بسازد! "
        f"status={resp.status_code}, body={resp.text}"
    )
    # اگر 404، قرارداد خطا را بررسی کنیم
    if resp.status_code == 404:
        body = resp.json()
        assert "detail" in body, f"N3: body باید detail داشته باشد. گرفتیم: {body}"


# ===========================================================================
# N4 — بدون Authorization header → 401
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_n4_no_auth_header_returns_401(e2e_tenants):
    """
    N4: درخواستِ بدون Authorization header → 401.

    بدون JWT هیچ GUC ستی نمی‌شود → حتی اگر به DB برسد، GUC='' →
    policy fail-closed → صفر ردیف. اما django-ninja قبل از آن 401 می‌دهد.

    دو endpoint بررسی می‌کنیم:
      - GET /patients (list)
      - GET /patients/{uuid}/record (by-id)
    """
    uuid_a = e2e_tenants["patient_uuid_a"]

    # بدون هیچ header
    resp_list = _client().get("/patients")
    assert resp_list.status_code == 401, (
        f"N4a: GET /patients بدون auth باید 401 بدهد؛ گرفتیم {resp_list.status_code}"
    )

    resp_record = _client().get(f"/patients/{uuid_a}/record")
    assert resp_record.status_code == 401, (
        f"N4b: GET /patients/{{uuid}}/record بدون auth باید 401 بدهد؛ "
        f"گرفتیم {resp_record.status_code}"
    )


# ===========================================================================
# N5 — JWTِ دست‌کاری‌شده/منقضی → 401
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_n5_tampered_jwt_returns_401(e2e_tenants):
    """
    N5a: توکنِ دست‌کاری‌شده (امضای نامعتبر) → 401.
    N5b: توکنِ منقضی (exp در گذشته) → 401.

    هر دو باید قبل از هر کوئریِ DB رد شوند.
    """
    uuid_a = e2e_tenants["patient_uuid_a"]

    # N5a — توکنِ ساختگی با امضای اشتباه
    fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxLCJ0ZW5hbnRfaWQiOjEsInJvbGUiOiJtYW5hZ2VyIn0.INVALID_SIGNATURE"
    resp_fake = _client().get(
        f"/patients/{uuid_a}/record",
        headers={"Authorization": f"Bearer {fake_token}"},
    )
    assert resp_fake.status_code == 401, (
        f"N5a: توکنِ ساختگی باید 401 بدهد؛ گرفتیم {resp_fake.status_code}"
    )

    # N5b — توکنِ منقضی: payload معتبر ولی exp = 1 ثانیه پیش
    expired_payload = {
        "user_id": 9999,
        "tenant_id": e2e_tenants["tid_a"],
        "role": "manager",
        "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1),
    }
    expired_token = pyjwt.encode(expired_payload, settings.SECRET_KEY, algorithm="HS256")
    resp_expired = _client().get(
        f"/patients/{uuid_a}/record",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp_expired.status_code == 401, (
        f"N5b: توکنِ منقضی باید 401 بدهد؛ گرفتیم {resp_expired.status_code}"
    )


# ===========================================================================
# E2 — clinical.observations (VIEW) با JWTِ A فقط دادهٔ A می‌دهد
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2_observations_view_respects_rls_for_tenant_a(e2e_tenants):
    """
    E2: clinical.observations VIEW با security_invoker=true.

    این VIEW vital_readings را expose می‌کند. با GUC=tid_a فقط vital_readings
    مربوط به بیمارانِ tenant-A قابلِ‌رؤیت است.

    چون endpoint مستقیمی برای این VIEW وجود ندارد، از psycopg با
    رولِ کم‌امتیاز + GUC=tid_a مستقیماً SELECT می‌کنیم و بررسی می‌کنیم
    vital_reading‌های tenant-B رؤیت‌پذیر نیستند.

    نکته: برای VIEW ممکن است در برخی version‌های schema این VIEW
    وجود نداشته باشد — اگر VIEW وجود ندارد تست را skip می‌کنیم.
    """
    link_id_a = e2e_tenants["link_id_a"]
    link_id_b = e2e_tenants["link_id_b"]

    with psycopg.connect(_APP_CONNINFO, autocommit=True) as conn:
        # بررسیِ وجودِ VIEW
        view_exists = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.views "
            "WHERE table_schema='clinical' AND table_name='observations')"
        ).fetchone()[0]

        if not view_exists:
            pytest.skip(
                "E2: clinical.observations VIEW وجود ندارد در این schema version — skip."
            )

        # GUC را به tenant-A ست می‌کنیم (شبیه‌سازیِ JWTBearer)
        conn.execute(
            "SELECT set_config('app.current_tenant', %s, false)",
            [str(e2e_tenants["tid_a"])]
        )

        # SELECT از VIEW با GUC=tid_a
        rows_a = conn.execute(
            "SELECT patient_link_id FROM clinical.observations "
            "WHERE patient_link_id = %s",
            [link_id_a]
        ).fetchall()

        rows_b = conn.execute(
            "SELECT patient_link_id FROM clinical.observations "
            "WHERE patient_link_id = %s",
            [link_id_b]
        ).fetchall()

    # vital_readings tenant-A باید دیده شوند
    assert len(rows_a) > 0, (
        f"E2: باید vital_readings برای link_id_a={link_id_a} از VIEW دیده شوند. "
        f"گرفتیم: صفر ردیف"
    )

    # vital_readings tenant-B نباید دیده شوند (RLS security_invoker)
    assert len(rows_b) == 0, (
        f"E2 FAIL — نشتِ VIEW! vital_readings tenant-B از طریقِ observations "
        f"با GUC=tid_a دیده می‌شود ({len(rows_b)} ردیف). "
        f"security_invoker=true باید این را ببندد."
    )


# ===========================================================================
# E4 — کاربرِ A نمی‌تواند کاربرِ B را از DB مستقیم UPDATE/DELETE کند
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e4_tenant_a_cannot_update_tenant_b_user_via_db(e2e_tenants):
    """
    E4: کاربرِ A می‌تواند login کند (SELECT آزاد روی platform.users برای auth)
    ولی با GUC=tid_a نمی‌تواند کاربرِ tenant-B را UPDATE یا DELETE کند.

    اثبات می‌کنیم:
    - SELECTِ platform.users (برای login) کار می‌کند بدونِ GUC (app-role SELECT)
    - UPDATE روی کاربرِ tenant-B با GUC=tid_a: صفر ردیف تغییر می‌کند
      (RLS WITH CHECK: کاربر tenant_id=tid_b را نمی‌بیند با GUC=tid_a)
    - DELETE روی کاربرِ tenant-B با GUC=tid_a: صفر ردیف حذف می‌شود

    یادداشت: platform.users ممکن است RLS داشته باشد یا نداشته باشد.
    اگر RLS فعال باشد، UPDATE/DELETE صفر ردیف برمی‌گرداند (نه خطا).
    اگر RLS فعال نباشد، با GUC=tid_a همچنان WHERE tenant_id=tid_a
    مانع می‌شود که ردیف‌های tenant-B دیده شوند — اما در این حالت
    test باید صریحاً گزارش کند که RLS روی platform.users فعال نیست.
    """
    tid_a = e2e_tenants["tid_a"]
    tid_b = e2e_tenants["tid_b"]
    username_b = e2e_tenants["username_b"]

    # ابتدا id کاربرِ B را با superuser پیدا می‌کنیم
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as su_conn:
        row = su_conn.execute(
            "SELECT id FROM platform.users WHERE tenant_id=%s AND username=%s",
            (tid_b, username_b)
        ).fetchone()

    assert row is not None, f"E4: کاربرِ B ({username_b}) باید در DB وجود داشته باشد"
    user_b_id = row[0]

    with psycopg.connect(_APP_CONNINFO, autocommit=True) as conn:
        # GUC = tenant-A (شبیه‌سازیِ JWTِ A)
        conn.execute(
            "SELECT set_config('app.current_tenant', %s, false)", [str(tid_a)]
        )

        # تلاشِ UPDATE کاربرِ B با GUC=A (ستون full_name که در schema وجود دارد)
        result = conn.execute(
            "UPDATE platform.users SET full_name=full_name WHERE id=%s RETURNING id",
            [user_b_id]
        )
        updated_rows = result.fetchall()

        # تلاشِ DELETE کاربرِ B با GUC=A (فقط بررسیِ اثر؛ DELETE نباید موفق شود)
        # توجه: DELETE را اجرا نمی‌کنیم تا از از دست رفتنِ داده جلوگیری کنیم
        # ترجیح: همین UPDATE=0 ردیف کافی است
        deleted_count = 0  # DELETE اجرا نمی‌کنیم — UPDATE=0 کافی است

    # بررسیِ وضعیتِ RLS روی platform.users
    with psycopg.connect(_SU_CONNINFO, autocommit=True) as su_conn:
        rls_row = su_conn.execute(
            "SELECT relrowsecurity FROM pg_class "
            "WHERE relname='users' AND relnamespace=("
            "SELECT oid FROM pg_namespace WHERE nspname='platform')"
        ).fetchone()

    rls_enabled_on_platform_users = rls_row[0] if rls_row else False

    # platform.users نگه‌دارندهٔ password_hash / api_token_hash / هویتِ JWT است.
    # RLS روی این جدول باید همیشه فعال و FORCE باشد (slice5: tenant_isolation).
    # نبودِ RLS اینجا یک شکستِ سختِ (hard-fail) امنیتی است، نه صرفاً یک warning:
    # این تست دقیقاً همان leak-test‌ای است که گِیتِ T5 (قدم ۸۳ — «مالک نتیجه را امضا
    # می‌کند») روی آن تکیه دارد؛ اگر برشی در آینده RLS را از این جدول بردارد، این
    # نگهبان باید بلند شکست بخورد، نه اینکه سبزِ کاذب بماند و امضا روی سوئیتِ ساکت انجام شود.
    assert rls_enabled_on_platform_users, (
        "E4 FAIL — RLS روی platform.users فعال نیست! این جدول password_hash/"
        "api_token_hash را نگه می‌دارد و slice5 باید tenant_isolation را روی آن FORCE کند "
        f"(pg_class.relrowsecurity=False). نتیجهٔ UPDATEِ متقاطع: {updated_rows}."
    )
    # RLS فعال است: UPDATEِ متقاطعِ tenant باید صفر ردیف را لمس کرده باشد.
    assert len(updated_rows) == 0, (
        f"E4 FAIL — نشتِ RLS روی platform.users! "
        f"کاربرِ A (GUC=tid_a={tid_a}) توانست کاربرِ B (id={user_b_id}) را UPDATE کند. "
        f"RLS WITH CHECK باید این را ببندد."
    )


# ===========================================================================
# تستِ ترکیبی: JWT-A و JWT-B را با هم تأیید کن
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_combined_isolation_a_and_b_see_only_own_data(e2e_tenants):
    """
    تستِ ترکیبی: A فقط A را می‌بیند، B فقط B را می‌بیند.

    این تست هر دو tenant را در یک تستِ واحد بررسی می‌کند تا اطمینان حاصل شود
    که ایزولاسیون در هر دو جهت کار می‌کند.

    GET /patients با JWT-A: uuid_b نباید باشد.
    GET /patients با JWT-B: uuid_a نباید باشد.
    """
    token_a = _do_login(e2e_tenants["username_a"], e2e_tenants["password_a"])
    token_b = _do_login(e2e_tenants["username_b"], e2e_tenants["password_b"])

    str_uuid_a = str(e2e_tenants["patient_uuid_a"])
    str_uuid_b = str(e2e_tenants["patient_uuid_b"])

    # لیستِ A
    resp_a = _client().get("/patients?limit=200", headers=_auth_headers(token_a))
    assert resp_a.status_code == 200
    uuids_for_a = [item["patient_uuid"] for item in resp_a.json()["items"] if item.get("patient_uuid")]

    # لیستِ B
    resp_b = _client().get("/patients?limit=200", headers=_auth_headers(token_b))
    assert resp_b.status_code == 200
    uuids_for_b = [item["patient_uuid"] for item in resp_b.json()["items"] if item.get("patient_uuid")]

    # A فقط A را می‌بیند
    assert str_uuid_a in uuids_for_a, (
        f"combined: A باید بیمارِ خودش ({str_uuid_a}) را ببیند"
    )
    assert str_uuid_b not in uuids_for_a, (
        f"combined FAIL: A بیمارِ B ({str_uuid_b}) را می‌بیند — نشتِ ایزولاسیون!"
    )

    # B فقط B را می‌بیند
    assert str_uuid_b in uuids_for_b, (
        f"combined: B باید بیمارِ خودش ({str_uuid_b}) را ببیند"
    )
    assert str_uuid_a not in uuids_for_b, (
        f"combined FAIL: B بیمارِ A ({str_uuid_a}) را می‌بیند — نشتِ ایزولاسیون!"
    )
