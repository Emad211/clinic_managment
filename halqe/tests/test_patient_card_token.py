"""
test_patient_card_token.py — خوشهٔ J، قدم ۴۴
ADR-0004 port — کارتِ عمومیِ بیمار

assertهای امنیتی (قفل‌شده با security-privacy-advisor):
  ۱) بدونِ PHI: national_id/تماس/نامِ دارو/بیماری در پاسخ نیست.
  ۲) zero-write: هیچ نوشتنی در GET /card/{token}.
  ۳) توکن: revoked→404؛ expired→404؛ نامعتبر→404؛ معتبر→200+projection.
  ۴) one-active-at-a-time: issue جدید، قبلی را revoke می‌کند.
  ۵) RLS/SECURITY DEFINER: مسیرِ عمومی بدونِ GUC کار می‌کند.
  ۶) تستِ سطحِ API برای هر endpoint.
  ۷) tenant isolation: توکنِ tenant-A دادهٔ tenant-B نمی‌دهد.

این تست‌ها روی Django in-memory/SQLite اجرا نمی‌شوند — به Docker Postgres نیاز دارند.
اگر PG_TEST_DSN ست نشده باشد: skip.

نکتهٔ مهم: conftest.py موجود (session-scoped django_db_setup) برای این تست‌ها کافی است.
این فایل fixture اضافه برای card-token seed تعریف می‌کند.
"""
import secrets
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone


# ---------------------------------------------------------------------------
# Skip اگر Docker PG در دسترس نیست (مثلِ CI محلی بدونِ Docker)
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "accounting_read"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_card_patient(conn, tenant_id: int = 1, name: str = "کارت") -> tuple[int, int]:
    """
    یک بیمارِ accounting + patient_link می‌سازد و (patient_id, link_id) را برمی‌گرداند.
    با superuser psycopg connection اجرا می‌شود (خارج از Django ORM).
    """
    import psycopg
    nat_id = secrets.token_hex(5)
    conn.execute(
        f"""INSERT INTO accounting.patients
                (tenant_id, name, family_name, national_id, phone_number)
            VALUES ({tenant_id}, 'کارتی', 'تستی', 'CARD{nat_id}', '09990000000')
            ON CONFLICT DO NOTHING""",
    )
    row = conn.execute(
        f"SELECT id FROM accounting.patients WHERE national_id='CARD{nat_id}'"
    ).fetchone()
    patient_id = row[0]

    conn.execute(
        f"""INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES ({tenant_id}, {patient_id}, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING"""
    )
    link_row = conn.execute(
        f"SELECT id FROM clinical.patient_links WHERE tenant_id={tenant_id} AND patient_id={patient_id}"
    ).fetchone()
    link_id = link_row[0]

    return patient_id, link_id


def _insert_vital(conn, patient_link_id: int, vtype: str, value: float, tenant_id: int = 1):
    conn.execute(
        f"""INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES ({tenant_id}, {patient_link_id}, '{vtype}', {value}, 'mg/dL', now(), 'clinic')"""
    )


def _insert_medication(conn, patient_link_id: int, drug_name: str, tenant_id: int = 1):
    conn.execute(
        f"""INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, dose, is_active, created_at)
            VALUES ({tenant_id}, {patient_link_id}, '{drug_name}', '500mg', TRUE, now())"""
    )


def _insert_condition(conn, patient_link_id: int, code: str, name: str, tenant_id: int = 1):
    """Insert condition and patient_condition; uses ON CONFLICT based on actual DB constraints."""
    # clinical.conditions: UNIQUE(tenant_id, name) — not on (tenant_id, code)
    # Use unique name to avoid conflict; if exists, fetch it.
    try:
        conn.execute(
            f"""INSERT INTO clinical.conditions (tenant_id, code, name, is_chronic, display_order)
                VALUES ({tenant_id}, '{code}', '{name}', TRUE, 99)
                ON CONFLICT (tenant_id, name) DO NOTHING"""
        )
    except Exception:
        pass
    cond_row = conn.execute(
        f"SELECT id FROM clinical.conditions WHERE tenant_id={tenant_id} AND name='{name}'"
    ).fetchone()
    if not cond_row:
        return
    cond_id = cond_row[0]
    try:
        conn.execute(
            f"""INSERT INTO clinical.patient_conditions
                    (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
                VALUES ({tenant_id}, {patient_link_id}, {cond_id}, TRUE, now())
                ON CONFLICT DO NOTHING"""
        )
    except Exception:
        pass


def _issue_token_via_service(patient_link_id: int, tenant_id: int = 1, ttl_hours: int = 8) -> str:
    """Issue a card token via the service (Django ORM path — needs GUC)."""
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(tenant_id)
    from clinical.card_token_service import issue
    token_str, _ = issue(patient_link_id, tenant_id, issued_by="test_staff", ttl_hours=ttl_hours)
    return token_str


def _issue_expired_token_via_db(conn, patient_link_id: int, tenant_id: int = 1) -> str:
    """توکنِ منقضی مستقیم در DB (برای تستِ expired path)."""
    token_str = secrets.token_urlsafe(32)
    past = (timezone.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S%z")
    conn.execute(
        f"""INSERT INTO clinical.patient_card_tokens
                (tenant_id, patient_link_id, token, expires_at, issued_by)
            VALUES ({tenant_id}, {patient_link_id}, '{token_str}', '{past}', 'test')"""
    )
    return token_str


# ---------------------------------------------------------------------------
# Fixtures — superuser connection برای seed
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def su_conn():
    """superuser psycopg connection به test DB."""
    import os
    import psycopg
    from tests.conftest import (
        PG_HOST, PG_PORT, PG_SU_USER, PG_SU_PASSWORD, TEST_DB_NAME
    )
    conn = psycopg.connect(
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'",
        autocommit=True,
    )
    yield conn
    # Teardown: remove every CARD% accounting patient + its clinical cascade.
    # These rows are inserted via autocommit (raw psycopg), so Django's per-test
    # rollback does NOT clean them up — without this they leak into the shared DB
    # with recent enrolled_at and push older seeded patients off page 1 of the
    # patient list, breaking later tests (e.g. test_patient_record). Best-effort.
    try:
        rows = conn.execute(
            "SELECT id FROM accounting.patients WHERE national_id LIKE 'CARD%'"
        ).fetchall()
        pids = [r[0] for r in rows]
        if pids:
            link_subq = (
                "SELECT id FROM clinical.patient_links WHERE patient_id = ANY(%s)"
            )
            conn.execute(
                f"DELETE FROM clinical.patient_card_tokens WHERE patient_link_id IN ({link_subq})",
                (pids,),
            )
            for tbl in ("vital_readings", "patient_medications", "patient_conditions"):
                conn.execute(
                    f"DELETE FROM clinical.{tbl} WHERE patient_link_id IN ({link_subq})",
                    (pids,),
                )
            conn.execute(
                "DELETE FROM clinical.patient_links WHERE patient_id = ANY(%s)", (pids,)
            )
            conn.execute(
                "DELETE FROM accounting.patients WHERE national_id LIKE 'CARD%'"
            )
    except Exception:
        pass
    conn.close()


@pytest.fixture()
def card_patient(su_conn, seed_data):
    """یک بیمار با ویتال، دارو، و بیماری برای تست‌های card."""
    patient_id, link_id = _insert_card_patient(su_conn, tenant_id=1, name="کارتِ تست")
    _insert_vital(su_conn, link_id, "fbs", 130, tenant_id=1)
    _insert_vital(su_conn, link_id, "bp_systolic", 135, tenant_id=1)
    _insert_medication(su_conn, link_id, "متفورمین_UNIQUE_CARD_TEST", tenant_id=1)
    _insert_condition(su_conn, link_id, "card_diab_test", "دیابتِ_کارت_تست", tenant_id=1)
    return {"patient_id": patient_id, "link_id": link_id}


# ===========================================================================
# ۱) تستِ بدونِ PHI — national_id/تماس/دارو/بیماری در پاسخ نیست
# ===========================================================================

class TestNoPHIInCardResponse:
    """ادعاهایِ اصلیِ PHI: اطلاعاتِ حساس در payload وجود ندارد."""

    def test_national_id_not_in_response(self, client, card_patient):
        """national_id (۱۰ رقمی) در پاسخِ JSON کارت نباشد."""
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        body = resp.json()
        import re
        # national_id معمولاً ۱۰ رقم است؛ هیچ کلیدِ 'national_id' در JSON نباشد
        assert "national_id" not in body, (
            "national_id نباید در payload کارت باشد"
        )
        # بررسیِ اضافی: هیچ رشتهٔ ۱۰-رقمیِ ایرانی در مقادیرِ text نباشد
        body_str = str(body)
        ten_digit_patterns = re.findall(r'\b\d{10}\b', body_str)
        assert not ten_digit_patterns, (
            f"یک یا چند رشتهٔ ۱۰-رقمی در پاسخ یافت شد: {ten_digit_patterns}"
        )

    def test_drug_name_not_in_response(self, client, card_patient):
        """نامِ داروی یکتا در پاسخِ JSON نباشد."""
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        body_str = str(resp.json())
        assert "متفورمین_UNIQUE_CARD_TEST" not in body_str, (
            "نامِ داروی یکتا نباید در payload کارت باشد"
        )

    def test_condition_not_in_response(self, client, card_patient):
        """نامِ بیماریِ یکتا در پاسخِ JSON نباشد."""
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        body_str = str(resp.json())
        assert "دیابتِ_کارت_تست" not in body_str, (
            "نامِ بیماریِ یکتا نباید در payload کارت باشد"
        )
        assert "card_diab_test" not in body_str, (
            "کدِ بیماری نباید در payload کارت باشد"
        )

    def test_phone_not_in_response(self, client, card_patient):
        """شمارهٔ تلفنِ بیمار در پاسخِ JSON نباشد."""
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        body_str = str(resp.json())
        assert "09990000000" not in body_str, (
            "شمارهٔ تلفنِ بیمار نباید در payload کارت باشد"
        )

    def test_response_shape_is_minimum_necessary(self, client, card_patient):
        """payload فقط کلیدهایِ مجاز دارد (minimum-necessary)."""
        ALLOWED_KEYS = {"first_name", "clinic_name", "vitals", "next_appointment", "framing"}
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        body = resp.json()
        unexpected = set(body.keys()) - ALLOWED_KEYS
        assert not unexpected, (
            f"payload کلیدهایِ غیرمجاز دارد: {unexpected}"
        )


# ===========================================================================
# ۲) تستِ zero-write — هیچ نوشتنی در GET /card/{token}
# ===========================================================================

class TestZeroWriteOnPublicCard:
    """GET /card/{token} هیچ نوشتنی روی DB انجام نمی‌دهد."""

    def test_xact_write_count_is_zero(self, client, card_patient, su_conn):
        """
        pg_stat_user_tables.n_tup_upd + n_tup_ins + n_tup_del قبل و بعد از GET یکسان.

        این تست cumulative stats را مقایسه می‌کند.
        به دلیلِ اینکه conftest از transaction=True استفاده می‌کند، نوشتن‌های
        سایرِ تست‌ها rollback می‌شوند — اما pg_stat stats rollback نمی‌شوند.
        پس فقط clinical.patient_card_tokens (جدولِ توکن) را check می‌کنیم:
        GET نباید روی این جدول INSERT/UPDATE/DELETE کند.
        """
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)

        # stats قبل از GET
        row_before = su_conn.execute(
            "SELECT n_tup_ins, n_tup_upd, n_tup_del "
            "FROM pg_stat_user_tables "
            "WHERE schemaname='clinical' AND relname='patient_card_tokens'"
        ).fetchone()

        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

        # stats بعد از GET
        row_after = su_conn.execute(
            "SELECT n_tup_ins, n_tup_upd, n_tup_del "
            "FROM pg_stat_user_tables "
            "WHERE schemaname='clinical' AND relname='patient_card_tokens'"
        ).fetchone()

        if row_before and row_after:
            assert row_before == row_after, (
                f"GET /card/token نوشتنی روی patient_card_tokens انجام داد!\n"
                f"  قبل: ins={row_before[0]}, upd={row_before[1]}, del={row_before[2]}\n"
                f"  بعد: ins={row_after[0]}, upd={row_after[1]}, del={row_after[2]}"
            )


# ===========================================================================
# ۳) تستِ توکن: revoked/expired/نامعتبر/معتبر + one-active-at-a-time
# ===========================================================================

class TestTokenLifecycle:
    """چرخهٔ عمرِ توکن و صحتِ HTTP response."""

    def test_valid_token_returns_200_with_projection(self, client, card_patient):
        """توکنِ معتبر → ۲۰۰ + payload معتبر."""
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        body = resp.json()
        assert "vitals" in body
        assert isinstance(body["vitals"], list)

    def test_unknown_token_returns_404(self, client):
        """توکنِ ناشناخته → ۴۰۴."""
        resp = client.get("/api/v1/card/totallyUnknownToken000XYZ")
        assert resp.status_code == 404

    def test_revoked_token_returns_404(self, client, card_patient):
        """توکنِ revoke‌شده → ۴۰۴."""
        from platform_core.tenant_context import set_tenant_guc
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)

        # revoke from service
        set_tenant_guc(1)
        from clinical.card_token_service import revoke
        from clinical.models import PatientCardToken
        tok_obj = PatientCardToken.objects.filter(token=token).first()
        assert tok_obj is not None
        revoke(tok_obj.id, tenant_id=1)

        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 404

    def test_expired_token_returns_404(self, client, card_patient, su_conn):
        """توکنِ منقضی → ۴۰۴."""
        link_id = card_patient["link_id"]
        expired_token = _issue_expired_token_via_db(su_conn, link_id, tenant_id=1)
        resp = client.get(f"/api/v1/card/{expired_token}")
        assert resp.status_code == 404

    def test_one_active_at_a_time_issue_revokes_previous(self, card_patient):
        """issue جدید → توکنِ قبلی revoke‌شده."""
        from clinical.models import PatientCardToken
        from platform_core.tenant_context import set_tenant_guc

        link_id = card_patient["link_id"]
        set_tenant_guc(1)

        token1 = _issue_token_via_service(link_id)
        token2 = _issue_token_via_service(link_id)

        row1 = PatientCardToken.objects.get(token=token1)
        row2 = PatientCardToken.objects.get(token=token2)

        assert row1.revoked_at is not None, "توکنِ اول بعد از issue جدید باید revoke شده باشد"
        assert row2.revoked_at is None, "توکنِ دوم نباید revoke شده باشد"

    def test_resolve_token_returns_correct_ids(self, card_patient):
        """resolve_token توکنِ معتبر → (patient_link_id, tenant_id) درست."""
        from clinical.card_token_service import resolve_token

        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)

        result = resolve_token(token)
        assert result is not None
        assert result["patient_link_id"] == link_id
        assert result["tenant_id"] == 1

    def test_resolve_token_returns_none_for_unknown(self):
        """resolve_token با توکنِ ناشناخته → None."""
        from clinical.card_token_service import resolve_token
        result = resolve_token("completely-bogus-token-xyz-123")
        assert result is None


# ===========================================================================
# ۴) تستِ RLS/SECURITY DEFINER — مسیرِ عمومی بدونِ GUC
# ===========================================================================

class TestSecurityDefinerResolve:
    """card_resolve_token() SECURITY DEFINER بدونِ GUC کار می‌کند."""

    def test_resolve_works_without_guc(self, card_patient, su_conn):
        """
        resolve_token با GUC='' (بدونِ tenant) باید توکنِ معتبر را پیدا کند.

        این اثباتِ اصلیِ SECURITY DEFINER است: endpoint عمومی GUC ندارد
        اما می‌تواند توکن را resolve کند.
        """
        from django.db import connection
        from clinical.card_token_service import resolve_token, issue

        link_id = card_patient["link_id"]

        # issue با GUC ست
        from platform_core.tenant_context import set_tenant_guc, clear_tenant_guc
        set_tenant_guc(1)
        token_str, _ = issue(link_id, tenant_id=1, issued_by="test")

        # حالا GUC را پاک کن (شبیه‌سازیِ مسیرِ عمومی)
        clear_tenant_guc()

        # resolve باید بدونِ GUC کار کند (SECURITY DEFINER)
        result = resolve_token(token_str)
        assert result is not None, (
            "card_resolve_token() باید بدونِ GUC توکنِ معتبر را پیدا کند (SECURITY DEFINER)"
        )
        assert result["patient_link_id"] == link_id
        assert result["tenant_id"] == 1

    def test_tenant_a_token_cannot_get_tenant_b_data(self, client, su_conn, seed_clinical_data):
        """
        توکنِ tenant-1 نباید دادهٔ tenant-2 را نشان دهد.

        این تستِ اصلیِ tenant isolation است: بعد از resolve و set_tenant_guc(1)،
        تمامِ queryهای بالینی فقط tenant-1 را می‌بینند.

        از seed_clinical_data استفاده می‌کنیم چون tenant-2 در آن seed شده است.
        """
        from platform_core.tenant_context import set_tenant_guc

        # tenant-2 از seed_clinical_data موجود است؛ یک بیمارِ tenant-2 با ویتالِ ۲۰۰ می‌سازیم
        # (فقط اگر tenant-2 در accounting.tenants وجود دارد — که seed_clinical_data آن را ساخته)
        try:
            patient_id_2, link_id_2 = _insert_card_patient(su_conn, tenant_id=2, name="تنانتِ دو")
            _insert_vital(su_conn, link_id_2, "fbs", 200, tenant_id=2)
        except Exception:
            pytest.skip("tenant-2 در accounting.tenants یافت نشد — seed_clinical_data اجرا نشده")

        # بیمارِ tenant-1 و توکن
        patient_id_1, link_id_1 = _insert_card_patient(su_conn, tenant_id=1, name="تنانتِ یک")
        _insert_vital(su_conn, link_id_1, "fbs", 100, tenant_id=1)

        set_tenant_guc(1)
        from clinical.card_token_service import issue
        token_str, _ = issue(link_id_1, tenant_id=1, issued_by="test")

        resp = client.get(f"/api/v1/card/{token_str}")
        assert resp.status_code == 200
        body = resp.json()
        # ویتالِ tenant-2 (fbs=200) نباید در پاسخ باشد
        vitals = body.get("vitals", [])
        fbs_values = [v["value"] for v in vitals if v["key"] == "fbs"]
        assert 200.0 not in fbs_values, (
            f"ویتالِ tenant-2 (fbs=200) در پاسخِ کارتِ tenant-1 یافت شد: {fbs_values}"
        )


# ===========================================================================
# ۵) تستِ سطحِ API — شکلِ قرارداد serialized
# ===========================================================================

class TestAPIContract:
    """قراردادِ سریال‌شدهٔ API endpoints."""

    def test_public_card_response_has_correct_keys(self, client, card_patient):
        """GET /card/{token} payload شکلِ درست دارد."""
        link_id = card_patient["link_id"]
        token = _issue_token_via_service(link_id)
        resp = client.get(f"/api/v1/card/{token}")
        assert resp.status_code == 200
        body = resp.json()
        assert "first_name" in body
        assert "clinic_name" in body
        assert "vitals" in body
        assert "next_appointment" in body
        assert "framing" in body
        # vitals باید list باشد
        assert isinstance(body["vitals"], list)
        # هر ویتال کلیدهایِ مجاز دارد
        for vital in body["vitals"]:
            assert "key" in vital
            assert "label" in vital
            assert "value" in vital
            assert "unit" in vital
            assert "status" in vital
            assert vital["status"] in ("ok", "warn", "danger")

    def test_issue_token_staff_endpoint(self, client, seed_data):
        """POST /patients/{uuid}/card-token توکن می‌سازد و CardTokenOut برمی‌گرداند."""
        # لاگینِ staff
        login_resp = client.post(
            "/api/v1/auth/login",
            data='{"username": "testuser", "password": "secret123"}',
            content_type="application/json",
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        patient_uuid = str(seed_data["patient_uuid"])
        resp = client.post(
            f"/api/v1/patients/{patient_uuid}/card-token",
            **headers,
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.json()}"
        body = resp.json()
        assert "token" in body
        assert "expires_at" in body
        assert "card_url" in body
        assert body["card_url"].startswith("/card/")
        # توکن باید url-safe base64 (~43 chars) باشد
        assert len(body["token"]) >= 40

    def test_revoke_token_staff_endpoint(self, client, seed_data):
        """POST /patients/{uuid}/card-token/revoke توکن را revoke می‌کند."""
        # لاگین
        login_resp = client.post(
            "/api/v1/auth/login",
            data='{"username": "testuser", "password": "secret123"}',
            content_type="application/json",
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        patient_uuid = str(seed_data["patient_uuid"])

        # issue
        issue_resp = client.post(
            f"/api/v1/patients/{patient_uuid}/card-token",
            **headers,
        )
        assert issue_resp.status_code == 201
        issued_token_str = issue_resp.json()["token"]

        # پیدا کردنِ token_id از DB
        from clinical.models import PatientCardToken
        from platform_core.tenant_context import set_tenant_guc
        set_tenant_guc(1)
        tok_obj = PatientCardToken.objects.filter(token=issued_token_str).first()
        assert tok_obj is not None
        token_id = tok_obj.id

        # revoke
        revoke_resp = client.post(
            f"/api/v1/patients/{patient_uuid}/card-token/revoke",
            data=f'{{"token_id": {token_id}}}',
            content_type="application/json",
            **headers,
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json().get("status") == "revoked"

        # تأیید: توکن دیگر ۲۰۰ نمی‌دهد
        card_resp = client.get(f"/api/v1/card/{issued_token_str}")
        assert card_resp.status_code == 404

    def test_unknown_patient_uuid_returns_404_for_issue(self, client, seed_data):
        """issue با UUID ناشناخته → ۴۰۴."""
        login_resp = client.post(
            "/api/v1/auth/login",
            data='{"username": "testuser", "password": "secret123"}',
            content_type="application/json",
        )
        token = login_resp.json()["token"]
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        fake_uuid = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/patients/{fake_uuid}/card-token",
            **headers,
        )
        assert resp.status_code == 404


# ===========================================================================
# ۶) نگهبانِ معماری: SECURITY DEFINER function در DB
#    این تست‌ها opt-in (PG_TEST_DSN) هستند — در conftest skip می‌شوند اگر ست نشود.
#    اینجا مستقیم به PG وصل می‌شویم تا ساختارِ DB را اثبات کنیم.
# ===========================================================================

@pytest.fixture(scope="module")
def pg_schema_conn():
    """Direct superuser connection برای تستِ نگهبانِ schema."""
    try:
        import psycopg
        from tests.conftest import (
            PG_HOST, PG_PORT, PG_SU_USER, PG_SU_PASSWORD, TEST_DB_NAME
        )
        conn = psycopg.connect(
            f"host='{PG_HOST}' port='{PG_PORT}' "
            f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'",
            autocommit=True,
        )
        yield conn
        conn.close()
    except Exception:
        yield None


class TestSchemaGuard:
    """نگهبانِ ساختارِ DB: جدول + RLS + FORCE + تابعِ SECURITY DEFINER + GRANT."""

    def test_patient_card_tokens_table_exists(self, pg_schema_conn):
        """clinical.patient_card_tokens وجود دارد."""
        if not pg_schema_conn:
            pytest.skip("PG connection not available")
        row = pg_schema_conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='clinical' AND table_name='patient_card_tokens'"
        ).fetchone()
        assert row, "clinical.patient_card_tokens باید وجود داشته باشد"

    def test_token_unique_constraint(self, pg_schema_conn):
        """token ستون UNIQUE constraint دارد."""
        if not pg_schema_conn:
            pytest.skip("PG connection not available")
        row = pg_schema_conn.execute(
            """SELECT 1 FROM information_schema.table_constraints tc
               JOIN information_schema.constraint_column_usage ccu
                 ON tc.constraint_name = ccu.constraint_name
               WHERE tc.table_schema='clinical'
                 AND tc.table_name='patient_card_tokens'
                 AND tc.constraint_type='UNIQUE'
                 AND ccu.column_name='token'"""
        ).fetchone()
        assert row, "token column باید UNIQUE constraint داشته باشد"

    def test_rls_enabled_and_force(self, pg_schema_conn):
        """RLS فعال و FORCE روی clinical.patient_card_tokens."""
        if not pg_schema_conn:
            pytest.skip("PG connection not available")
        row = pg_schema_conn.execute(
            """SELECT relrowsecurity, relforcerowsecurity
               FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname='clinical' AND c.relname='patient_card_tokens'"""
        ).fetchone()
        assert row, "جدول patient_card_tokens در pg_class یافت نشد"
        assert row[0] is True, "RLS باید فعال باشد (relrowsecurity=true)"
        assert row[1] is True, "FORCE RLS باید فعال باشد (relforcerowsecurity=true)"

    def test_tenant_isolation_policy_exists(self, pg_schema_conn):
        """policy tenant_isolation روی جدول وجود دارد."""
        if not pg_schema_conn:
            pytest.skip("PG connection not available")
        row = pg_schema_conn.execute(
            """SELECT 1 FROM pg_policy p
               JOIN pg_class c ON c.oid = p.polrelid
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname='clinical'
                 AND c.relname='patient_card_tokens'
                 AND p.polname='tenant_isolation'"""
        ).fetchone()
        assert row, "policy tenant_isolation روی patient_card_tokens باید وجود داشته باشد"

    def test_card_resolve_token_function_exists_and_security_definer(self, pg_schema_conn):
        """clinical.card_resolve_token(text) با SECURITY DEFINER موجود است."""
        if not pg_schema_conn:
            pytest.skip("PG connection not available")
        row = pg_schema_conn.execute(
            """SELECT p.prosecdef, p.provolatile
               FROM pg_proc p
               JOIN pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname='clinical' AND p.proname='card_resolve_token'"""
        ).fetchone()
        assert row, "clinical.card_resolve_token باید در pg_proc باشد"
        assert row[0] is True, "card_resolve_token باید SECURITY DEFINER باشد (prosecdef=true)"
        assert row[1] == 's', "card_resolve_token باید STABLE باشد (provolatile='s')"

    def test_public_does_not_have_execute_on_function(self, pg_schema_conn):
        """PUBLIC حقِ EXECUTE روی card_resolve_token ندارد."""
        if not pg_schema_conn:
            pytest.skip("PG connection not available")
        row = pg_schema_conn.execute(
            """SELECT has_function_privilege('public',
               'clinical.card_resolve_token(text)', 'EXECUTE')"""
        ).fetchone()
        # PUBLIC نباید EXECUTE داشته باشد
        assert row[0] is False, (
            "PUBLIC نباید EXECUTE روی card_resolve_token داشته باشد"
        )

    def test_platform_app_has_execute_on_function(self, pg_schema_conn):
        """platform_app حقِ EXECUTE روی card_resolve_token دارد."""
        if not pg_schema_conn:
            pytest.skip("PG connection not available")
        row = pg_schema_conn.execute(
            """SELECT has_function_privilege('platform_app',
               'clinical.card_resolve_token(text)', 'EXECUTE')"""
        ).fetchone()
        assert row[0] is True, (
            "platform_app باید EXECUTE روی card_resolve_token داشته باشد"
        )

    def test_idempotent_slice_rerun(self, pg_schema_conn):
        """اجرای مجددِ slice12 بدونِ خطا (idempotency)."""
        if not pg_schema_conn:
            pytest.skip("PG connection not available")
        import os
        slice_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "specialist_clinic", "docs", "migration_tools",
            "schema_pg_slice12_patient_card_tokens.sql",
        )
        slice_path = os.path.normpath(slice_path)
        assert os.path.exists(slice_path), f"slice12 پیدا نشد: {slice_path}"
        with open(slice_path, encoding="utf-8") as f:
            sql = f.read()
        # بدونِ خطا اجرا شود
        pg_schema_conn.execute(sql)
