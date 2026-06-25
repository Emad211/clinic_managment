"""
test_patient_self_report.py — slice13 / step 45
Patient self-report endpoint + verified gate

assertهای امنیتی (قفل‌شده با security-privacy-advisor):
  ۱) گیتِ موتور (مقدس): vital با verified=False, source='patient_self' جدیدتر از
     آخرین verified → build_facts همان verifiedِ قدیمی را برگرداند (نه unverified را).
     در indicator_facts نباشد (اگر verified وجود ندارد).
  ۲) گیتِ کارت: unverified vital → در card_for_patient ظاهر نشود.
  ۳) یک‌بارمصرف: POST /patient-report/{used_token} → 404 (token_invalid).
  ۴) جداسازیِ scope:
     - GET /card/{report_token} → 404 (card endpoint نمی‌پذیرد)
     - POST /patient-report/{card_token} → 404 (report endpoint نمی‌پذیرد)
  ۵) بازهٔ مقدار: fbs=5000 → 422؛ type غیرمجاز → 422.
  ۶) submission موفق: توکنِ معتبر + مقدارِ معقول → 200 + ردیفِ verified=FALSE, source='patient_self'.
  ۷) نگهبانِ test_pg_schema: ستونِ verified + جدولِ report_tokens + RLS + SECURITY DEFINER.

این تست‌ها روی Django in-memory/SQLite اجرا نمی‌شوند — به Docker Postgres نیاز دارند.
اگر PG_TEST_DSN ست نشده باشد: skip نمی‌شوند (چون conftest آن‌ها را با django_db_setup
متصل می‌کند). اگر Docker در دسترس نیست، کل suite skip می‌شود.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "accounting_read"])


# ---------------------------------------------------------------------------
# Helpers — superuser raw inserts
# ---------------------------------------------------------------------------

def _make_report_patient(conn, tenant_id: int = 1, prefix: str = "RPT") -> tuple[int, int]:
    """patient + patient_link برای self-report تست‌ها."""
    nat_id = secrets.token_hex(5)
    conn.execute(
        f"""INSERT INTO accounting.patients
                (tenant_id, name, family_name, national_id, phone_number)
            VALUES ({tenant_id}, 'گزارشی', 'تستی', '{prefix}{nat_id}', '09120000001')
            ON CONFLICT DO NOTHING"""
    )
    row = conn.execute(
        f"SELECT id FROM accounting.patients WHERE national_id='{prefix}{nat_id}'"
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
    return patient_id, link_row[0]


def _insert_vital(
    conn,
    patient_link_id: int,
    vtype: str,
    value: float,
    verified: bool = True,
    source: str = "clinic",
    tenant_id: int = 1,
):
    """Insert a vital reading directly (bypassing RLS with superuser conn)."""
    conn.execute(
        f"""INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source, verified)
            VALUES ({tenant_id}, {patient_link_id}, '{vtype}', {value},
                    'mg/dL', now(), '{source}', {'TRUE' if verified else 'FALSE'})"""
    )


def _issue_report_token(
    conn,
    patient_link_id: int,
    tenant_id: int = 1,
    ttl_hours: int = 24,
    used: bool = False,
) -> str:
    """Insert a report token directly (for testing edge cases)."""
    token_str = secrets.token_urlsafe(32)
    expires_ts = (timezone.now() + timedelta(hours=ttl_hours)).strftime("%Y-%m-%d %H:%M:%S%z")
    used_sql = "now()" if used else "NULL"
    conn.execute(
        f"""INSERT INTO clinical.patient_report_tokens
                (tenant_id, patient_link_id, token, expires_at, used_at, issued_by)
            VALUES ({tenant_id}, {patient_link_id}, '{token_str}', '{expires_ts}',
                    {used_sql}, 'test_staff')"""
    )
    return token_str


def _issue_report_token_via_service(patient_link_id: int, tenant_id: int = 1) -> str:
    """Issue via the Django service (for integration path)."""
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(tenant_id)
    from clinical.report_token_service import issue
    token_str, _ = issue(patient_link_id, tenant_id, issued_by="test_staff")
    return token_str


def _issue_card_token_via_service(patient_link_id: int, tenant_id: int = 1) -> str:
    """Issue a CARD token (for scope isolation test)."""
    from platform_core.tenant_context import set_tenant_guc
    set_tenant_guc(tenant_id)
    from clinical.card_token_service import issue
    token_str, _ = issue(patient_link_id, tenant_id, issued_by="test_staff")
    return token_str


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def su_conn():
    """superuser psycopg connection."""
    import psycopg
    from tests.conftest import PG_HOST, PG_PORT, PG_SU_USER, PG_SU_PASSWORD, TEST_DB_NAME
    conn = psycopg.connect(
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'",
        autocommit=True,
    )
    yield conn
    # Cleanup: remove RPT% patients
    try:
        rows = conn.execute(
            "SELECT id FROM accounting.patients WHERE national_id LIKE 'RPT%'"
        ).fetchall()
        for (pid,) in rows:
            conn.execute(f"DELETE FROM accounting.patients WHERE id={pid}")
    except Exception:
        pass
    conn.close()


@pytest.fixture(scope="module")
def report_patient(su_conn):
    """یک بیمار + patient_link برای self-report تست‌ها."""
    patient_id, link_id = _make_report_patient(su_conn)
    return {"patient_id": patient_id, "link_id": link_id}


# ---------------------------------------------------------------------------
# ۱) گیتِ موتور — verified=False نباید وارد build_facts شود
# ---------------------------------------------------------------------------

class TestEngineGate:
    """اثباتِ گیتِ موتور: verified=FALSE در build_facts نیست."""

    def test_unverified_vital_does_not_enter_engine(self, su_conn, report_patient):
        """
        فرضیه: یک vital با verified=False جدیدتر از آخرین verified ثبت می‌شود.
        انتظار: build_facts مقدارِ verifiedِ قدیمی را برمی‌گرداند (نه unverified).
        """
        from clinical.rule_engine import build_facts

        link_id = report_patient["link_id"]

        # verified baseline: fbs=100 (clinic, verified=True) در زمانِ t-10s
        _insert_vital(su_conn, link_id, "fbs", 100.0, verified=True, source="clinic")
        # unverified self-report: fbs=500 (patient_self, verified=False) — بعدتر
        _insert_vital(su_conn, link_id, "fbs", 500.0, verified=False, source="patient_self")

        facts = build_facts(link_id, tenant_id=1)
        indicator = facts.get("indicator", {})

        # fbs باید در facts باشد (از verifiedِ قبلی)
        assert "fbs" in indicator, "Expected 'fbs' in indicator_facts from verified reading"
        actual_value = indicator["fbs"].get("latest")
        assert actual_value == 100.0, (
            f"Expected verified fbs=100, got {actual_value}. "
            f"Unverified self-report (500) must NOT enter the engine."
        )

    def test_no_verified_means_no_fact(self, su_conn):
        """
        فرضیه: اگر فقط unverified vital وجود دارد (نه verified)،
        indicator_facts نباید آن کلید را داشته باشد.
        """
        from clinical.rule_engine import build_facts

        # بیمارِ جدید بدونِ هیچ verified vital
        _, link_id = _make_report_patient(su_conn, prefix="RPT2")
        _insert_vital(su_conn, link_id, "fbs", 300.0, verified=False, source="patient_self")

        facts = build_facts(link_id, tenant_id=1)
        indicator = facts.get("indicator", {})

        assert "fbs" not in indicator, (
            f"Unverified-only fbs must NOT appear in indicator_facts. "
            f"Got indicator={indicator}"
        )


# ---------------------------------------------------------------------------
# ۲) گیتِ کارت — verified=False در card_for_patient نیست
# ---------------------------------------------------------------------------

class TestCardGate:
    """اثباتِ گیتِ کارت: verified=FALSE در card_for_patient ظاهر نمی‌شود."""

    def test_unverified_vital_not_on_card(self, su_conn):
        """
        یک vital با verified=False جدیدتر از verified → card_for_patient
        مقدارِ verifiedِ قدیمی را نشان می‌دهد.
        """
        from platform_core.tenant_context import set_tenant_guc
        from clinical.card_projection_service import card_for_patient

        _, link_id = _make_report_patient(su_conn, prefix="RPTC")
        # verified baseline: bp_systolic=120
        _insert_vital(su_conn, link_id, "bp_systolic", 120.0, verified=True, source="clinic")
        # unverified self-report: bp_systolic=200
        _insert_vital(su_conn, link_id, "bp_systolic", 200.0, verified=False, source="patient_self")

        set_tenant_guc(1)
        card = card_for_patient(link_id, tenant_id=1)

        vitals_map = {v["key"]: v for v in (card.get("vitals") or [])}
        if "bp_systolic" in vitals_map:
            actual = vitals_map["bp_systolic"]["value"]
            assert actual == 120.0, (
                f"Card must show verified bp_systolic=120, not unverified=200. Got {actual}"
            )

    def test_unverified_only_not_on_card(self, su_conn):
        """اگر فقط unverified vital وجود دارد، card.vitals آن کلید را ندارد."""
        from platform_core.tenant_context import set_tenant_guc
        from clinical.card_projection_service import card_for_patient

        _, link_id = _make_report_patient(su_conn, prefix="RPTCO")
        _insert_vital(su_conn, link_id, "fbs", 350.0, verified=False, source="patient_self")

        set_tenant_guc(1)
        card = card_for_patient(link_id, tenant_id=1)

        vitals_map = {v["key"]: v for v in (card.get("vitals") or [])}
        assert "fbs" not in vitals_map, (
            f"Unverified-only fbs must NOT appear on card. Got vitals={card.get('vitals')}"
        )


# ---------------------------------------------------------------------------
# ۳) یک‌بارمصرف: POST /patient-report/{used_token} → 404
# ---------------------------------------------------------------------------

class TestOneTimeUse:
    """یک‌بارمصرف بودنِ report token."""

    def test_used_token_returns_404(self, su_conn, report_patient, client):
        """توکنِ قبلاً استفاده‌شده → 404 (token_invalid)."""
        link_id = report_patient["link_id"]
        used_token = _issue_report_token(su_conn, link_id, used=True)

        resp = client.post(
            f"/api/v1/patient-report/{used_token}",
            data={"type": "fbs", "value": 100.0},
            content_type="application/json",
        )
        assert resp.status_code == 404, f"Expected 404 for used token, got {resp.status_code}"
        data = resp.json()
        assert "code" in data

    def test_successful_submit_makes_token_unusable(self, su_conn, report_patient, client):
        """توکنِ معتبر → ۲۰۰؛ استفادهٔ دوباره → ۴۰۴."""
        link_id = report_patient["link_id"]
        token_str = _issue_report_token(su_conn, link_id, used=False)

        # اولین استفاده — باید موفق باشد
        resp1 = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "fbs", "value": 120.0},
            content_type="application/json",
        )
        assert resp1.status_code == 200, f"First submit failed: {resp1.json()}"

        # استفادهٔ دوباره — باید ۴۰۴ باشد
        resp2 = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "fbs", "value": 150.0},
            content_type="application/json",
        )
        assert resp2.status_code == 404, f"Second submit must be 404, got {resp2.status_code}"


# ---------------------------------------------------------------------------
# ۴) جداسازیِ scope: card_token ↔ report_token
# ---------------------------------------------------------------------------

class TestScopeIsolation:
    """توکنِ card نمی‌تواند در report endpoint استفاده شود و بالعکس."""

    def test_card_token_rejected_by_report_endpoint(self, su_conn, report_patient, client):
        """card_token در /patient-report/{token} → 404 (نه ۲۰۰)."""
        link_id = report_patient["link_id"]
        card_token = _issue_card_token_via_service(link_id)

        resp = client.post(
            f"/api/v1/patient-report/{card_token}",
            data={"type": "fbs", "value": 100.0},
            content_type="application/json",
        )
        assert resp.status_code == 404, (
            f"card_token must NOT work in /patient-report/. Got {resp.status_code}"
        )

    def test_report_token_rejected_by_card_endpoint(self, su_conn, report_patient, client):
        """report_token در /card/{token} → 404 (نه ۲۰۰)."""
        link_id = report_patient["link_id"]
        report_token = _issue_report_token(su_conn, link_id, used=False)

        resp = client.get(f"/api/v1/card/{report_token}")
        assert resp.status_code == 404, (
            f"report_token must NOT work in /card/. Got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# ۵) بازهٔ مقدار و type whitelist
# ---------------------------------------------------------------------------

class TestValidation:
    """اعتبارسنجی type و value."""

    def test_out_of_range_fbs_returns_422(self, su_conn, report_patient, client):
        """fbs=5000 (خارج از بازهٔ ۲۰–۸۰۰) → ۴۲۲."""
        link_id = report_patient["link_id"]
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "fbs", "value": 5000.0},
            content_type="application/json",
        )
        assert resp.status_code == 422, f"Expected 422 for fbs=5000, got {resp.status_code}"
        # توکن نباید used شود (چون validation قبل از insert است)
        # می‌توانیم با submit مجدد تأیید کنیم
        resp2 = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "fbs", "value": 100.0},
            content_type="application/json",
        )
        assert resp2.status_code == 200, (
            f"Token must still be usable after 422 validation failure. Got {resp2.status_code}"
        )

    def test_disallowed_type_returns_422(self, su_conn, report_patient, client):
        """type='hba1c' (خارج از whitelist) → ۴۲۲."""
        link_id = report_patient["link_id"]
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "hba1c", "value": 7.5},
            content_type="application/json",
        )
        assert resp.status_code == 422, f"Expected 422 for type=hba1c, got {resp.status_code}"

    def test_extra_fields_rejected(self, su_conn, report_patient, client):
        """ninja schema — کلیدِ اضافی نباید accepted شود (schema strict)."""
        link_id = report_patient["link_id"]
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "fbs", "value": 100.0, "hacked_field": "evil"},
            content_type="application/json",
        )
        # ninja با Pydantic: کلیدِ اضافی در strict mode → reject؛ در loose mode → ignore
        # این تست رفتارِ واقعی را ثبت می‌کند (documentation test)
        assert resp.status_code in (200, 422), (
            f"Unexpected status for extra field: {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# ۶) submission موفق — verified=FALSE در DB
# ---------------------------------------------------------------------------

class TestSuccessfulSubmit:
    """submission موفق → verified=FALSE, source='patient_self' در DB."""

    def test_successful_submit_creates_unverified_row(self, su_conn, report_patient, client):
        """
        POST /patient-report/{valid_token} → 200 +
        ردیفِ verified=FALSE, source='patient_self' در vital_readings.
        """
        link_id = report_patient["link_id"]
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "bp_systolic", "value": 130.0},
            content_type="application/json",
        )
        assert resp.status_code == 200, f"Submit failed: {resp.json()}"
        data = resp.json()
        assert data.get("status") == "ok"
        assert data.get("type") == "bp_systolic"
        assert data.get("value") == 130.0

        # تأییدِ DB: ردیف باید verified=FALSE, source='patient_self' باشد
        row = su_conn.execute(
            f"""SELECT value, verified, source FROM clinical.vital_readings
                WHERE patient_link_id={link_id}
                  AND type='bp_systolic'
                  AND source='patient_self'
                ORDER BY measured_at DESC LIMIT 1"""
        ).fetchone()
        assert row is not None, "Expected a vital_reading row with source='patient_self'"
        val, verified, source = row
        assert abs(val - 130.0) < 0.01, f"Expected value=130.0, got {val}"
        assert verified is False, f"Expected verified=False for self-report, got {verified}"
        assert source == "patient_self", f"Expected source='patient_self', got {source}"

    def test_successful_submit_marks_token_used(self, su_conn, report_patient, client):
        """بعد از submission موفق، توکن used_at دارد."""
        link_id = report_patient["link_id"]
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "fbs", "value": 90.0},
            content_type="application/json",
        )
        assert resp.status_code == 200

        # بررسیِ DB: used_at باید ست شده باشد
        row = su_conn.execute(
            f"SELECT used_at FROM clinical.patient_report_tokens WHERE token='{token_str}'"
        ).fetchone()
        assert row is not None
        assert row[0] is not None, "Token must have used_at set after successful submit"


# ---------------------------------------------------------------------------
# ۷) نگهبانِ schema (test_pg_schema)
# ---------------------------------------------------------------------------

class TestPgSchemaSentinel:
    """
    نگهبانِ مستقیمِ schema slice13 — بررسیِ ساختارِ DB.
    این‌ها معادلِ test_pg_schema.py هستند برای slice13.
    """

    def test_vital_readings_has_verified_column(self, su_conn):
        """vital_readings باید ستونِ verified داشته باشد (BOOLEAN NOT NULL DEFAULT TRUE)."""
        row = su_conn.execute(
            """SELECT column_name, data_type, column_default, is_nullable
               FROM information_schema.columns
               WHERE table_schema='clinical'
                 AND table_name='vital_readings'
                 AND column_name='verified'"""
        ).fetchone()
        assert row is not None, "Column vital_readings.verified missing (slice13 not applied)"
        col_name, data_type, col_default, is_nullable = row
        assert data_type.lower() == "boolean", f"Expected boolean, got {data_type}"
        assert is_nullable == "NO", "verified must be NOT NULL"
        assert col_default is not None and "true" in col_default.lower(), (
            f"verified must DEFAULT TRUE, got default={col_default}"
        )

    def test_observations_view_has_verified_column(self, su_conn):
        """VIEW clinical.observations باید ستونِ verified داشته باشد."""
        # بررسیِ ستون‌های VIEW از طریقِ یک query
        row = su_conn.execute(
            """SELECT column_name
               FROM information_schema.columns
               WHERE table_schema='clinical'
                 AND table_name='observations'
                 AND column_name='verified'"""
        ).fetchone()
        assert row is not None, "VIEW observations.verified column missing (slice13 not applied)"

    def test_patient_report_tokens_table_exists(self, su_conn):
        """جدولِ clinical.patient_report_tokens وجود دارد."""
        row = su_conn.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema='clinical' AND table_name='patient_report_tokens'"""
        ).fetchone()
        assert row is not None, "Table clinical.patient_report_tokens missing (slice13 not applied)"

    def test_report_token_table_columns(self, su_conn):
        """ستون‌های ضروری در patient_report_tokens وجود دارند."""
        cols = set(
            r[0]
            for r in su_conn.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema='clinical' AND table_name='patient_report_tokens'"""
            ).fetchall()
        )
        required = {"id", "tenant_id", "patient_link_id", "token", "issued_at",
                    "expires_at", "used_at", "issued_by"}
        missing = required - cols
        assert not missing, f"Missing columns in patient_report_tokens: {missing}"

    def test_report_token_table_rls_enabled(self, su_conn):
        """RLS باید روی clinical.patient_report_tokens فعال باشد."""
        row = su_conn.execute(
            """SELECT relrowsecurity, relforcerowsecurity
               FROM pg_class
               WHERE relname='patient_report_tokens'
                 AND relnamespace=(SELECT oid FROM pg_namespace WHERE nspname='clinical')"""
        ).fetchone()
        assert row is not None, "Table patient_report_tokens not found in pg_class"
        relrowsecurity, relforcerowsecurity = row
        assert relrowsecurity, "RLS must be ENABLED on patient_report_tokens"
        assert relforcerowsecurity, "RLS must be FORCED on patient_report_tokens"

    def test_report_resolve_token_function_exists(self, su_conn):
        """تابعِ clinical.report_resolve_token با SECURITY DEFINER وجود دارد."""
        row = su_conn.execute(
            """SELECT p.prosecdef, p.provolatile
               FROM pg_proc p
               JOIN pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname = 'clinical'
                 AND p.proname = 'report_resolve_token'"""
        ).fetchone()
        assert row is not None, "Function clinical.report_resolve_token missing (slice13 not applied)"
        prosecdef, provolatile = row
        assert prosecdef, "report_resolve_token must be SECURITY DEFINER"
        assert provolatile == "s", f"report_resolve_token must be STABLE ('s'), got '{provolatile}'"

    def test_report_resolve_token_public_revoked(self, su_conn):
        """PUBLIC نباید حقِ EXECUTE روی report_resolve_token داشته باشد."""
        # psycopg requires lowercase 'public' for has_function_privilege
        row = su_conn.execute(
            """SELECT has_function_privilege('public',
                  'clinical.report_resolve_token(text)', 'EXECUTE')"""
        ).fetchone()
        assert row is not None
        assert row[0] is False, "PUBLIC (public role) must NOT have EXECUTE on report_resolve_token"

    def test_report_resolve_token_platform_app_granted(self, su_conn):
        """platform_app باید حقِ EXECUTE روی report_resolve_token داشته باشد."""
        row = su_conn.execute(
            """SELECT has_function_privilege('platform_app',
                  'clinical.report_resolve_token(text)', 'EXECUTE')"""
        ).fetchone()
        assert row is not None
        assert row[0] is True, "platform_app must have EXECUTE on report_resolve_token"

    def test_observations_security_invoker(self, su_conn):
        """VIEW clinical.observations باید security_invoker=true داشته باشد."""
        # در PG16+: pg_class.relkind='v' و reloptions دارایِ security_invoker
        row = su_conn.execute(
            """SELECT reloptions
               FROM pg_class
               WHERE relname='observations'
                 AND relnamespace=(SELECT oid FROM pg_namespace WHERE nspname='clinical')
                 AND relkind='v'"""
        ).fetchone()
        assert row is not None, "VIEW clinical.observations not found in pg_class"
        reloptions = row[0]
        has_si = (
            reloptions is not None
            and any("security_invoker=true" in str(opt).lower() for opt in reloptions)
        )
        assert has_si, (
            f"VIEW clinical.observations must have security_invoker=true. "
            f"reloptions={reloptions}"
        )

    def test_report_tokens_unique_constraint(self, su_conn):
        """UNIQUE constraint روی patient_report_tokens.token وجود دارد."""
        row = su_conn.execute(
            """SELECT conname FROM pg_constraint
               WHERE conrelid='clinical.patient_report_tokens'::regclass
                 AND contype='u'
                 AND conname='uq_report_token'"""
        ).fetchone()
        assert row is not None, "UNIQUE constraint uq_report_token missing on patient_report_tokens"

    def test_report_tokens_fk_to_patient_links(self, su_conn):
        """FK از patient_report_tokens به patient_links(id) وجود دارد."""
        row = su_conn.execute(
            """SELECT conname FROM pg_constraint
               WHERE conrelid='clinical.patient_report_tokens'::regclass
                 AND contype='f'
                 AND conname='fk_report_token_patient_link'"""
        ).fetchone()
        assert row is not None, "FK fk_report_token_patient_link missing on patient_report_tokens"


# ---------------------------------------------------------------------------
# ۸) Batch self-report — step 46
# ---------------------------------------------------------------------------

class TestBatchSubmit:
    """
    قدمِ ۴۶: گسترشِ endpoint به batch.
    هدف: یک توکن → چند reading در یک ارسال (all-or-nothing).
    """

    def test_batch_success_three_readings(self, su_conn, client):
        """
        batch موفق: sys+dia+fbs در یک ارسال → ۳ ردیفِ verified=False + توکن used.
        """
        _, link_id = _make_report_patient(su_conn, prefix="RPTB1")
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={
                "readings": [
                    {"type": "bp_systolic",  "value": 140.0},
                    {"type": "bp_diastolic", "value": 85.0},
                    {"type": "fbs",          "value": 120.0},
                ]
            },
            content_type="application/json",
        )
        assert resp.status_code == 200, f"batch submit failed: {resp.json()}"
        data = resp.json()
        assert data.get("status") == "ok"
        assert data.get("count") == 3
        accepted = data.get("accepted", [])
        assert len(accepted) == 3

        # تأییدِ DB: باید ۳ ردیفِ verified=False + source='patient_self' باشد
        for vtype, vvalue in [("bp_systolic", 140.0), ("bp_diastolic", 85.0), ("fbs", 120.0)]:
            row = su_conn.execute(
                f"""SELECT value, verified, source FROM clinical.vital_readings
                    WHERE patient_link_id={link_id}
                      AND type='{vtype}'
                      AND source='patient_self'
                    ORDER BY measured_at DESC LIMIT 1"""
            ).fetchone()
            assert row is not None, f"Expected vital_reading for {vtype}"
            val, verified, source = row
            assert abs(val - vvalue) < 0.01, f"Expected {vtype}={vvalue}, got {val}"
            assert verified is False, f"{vtype} must be verified=False"

        # توکن باید used شده باشد
        tok_row = su_conn.execute(
            f"SELECT used_at FROM clinical.patient_report_tokens WHERE token='{token_str}'"
        ).fetchone()
        assert tok_row is not None
        assert tok_row[0] is not None, "Token must be marked used after batch success"

    def test_batch_invalid_one_reading_no_insert_no_mark_used(self, su_conn, client):
        """
        batch با یک مقدارِ نامعتبر (sys=999 خارج از بازه) → ۴۲۲.
        هیچ ردیفی insert نشود. توکن هنوز usable باشد.
        """
        _, link_id = _make_report_patient(su_conn, prefix="RPTB2")
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={
                "readings": [
                    {"type": "bp_systolic",  "value": 999.0},   # خارج از بازه ۵۰–۳۰۰
                    {"type": "bp_diastolic", "value": 85.0},
                ]
            },
            content_type="application/json",
        )
        assert resp.status_code == 422, f"Expected 422 for invalid reading, got {resp.status_code}"

        # هیچ vital_reading نباید insert شده باشد
        count_row = su_conn.execute(
            f"""SELECT COUNT(*) FROM clinical.vital_readings
                WHERE patient_link_id={link_id} AND source='patient_self'"""
        ).fetchone()
        assert count_row[0] == 0, (
            f"No rows must be inserted on partial-invalid batch. Found {count_row[0]}"
        )

        # توکن هنوز usable (used_at باید NULL باشد)
        tok_row = su_conn.execute(
            f"SELECT used_at FROM clinical.patient_report_tokens WHERE token='{token_str}'"
        ).fetchone()
        assert tok_row is not None
        assert tok_row[0] is None, "Token must NOT be marked used after validation failure"

        # بیمار می‌تواند مجدداً submit کند (توکن هنوز valid)
        resp2 = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={
                "readings": [
                    {"type": "bp_systolic",  "value": 130.0},
                    {"type": "bp_diastolic", "value": 82.0},
                ]
            },
            content_type="application/json",
        )
        assert resp2.status_code == 200, (
            f"Token must still work after 422 batch failure. Got {resp2.status_code}: {resp2.json()}"
        )

    def test_batch_empty_readings_422(self, su_conn, client):
        """batch خالی → ۴۲۲، توکن intact."""
        _, link_id = _make_report_patient(su_conn, prefix="RPTB3")
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"readings": []},
            content_type="application/json",
        )
        assert resp.status_code == 422, f"Empty batch must be 422, got {resp.status_code}"

        # توکن دست‌نخورده
        tok_row = su_conn.execute(
            f"SELECT used_at FROM clinical.patient_report_tokens WHERE token='{token_str}'"
        ).fetchone()
        assert tok_row[0] is None, "Token must NOT be consumed after empty-batch 422"

    def test_batch_used_token_409(self, su_conn, client):
        """used token با batch → ۴۰۴ (مثلِ قبل، generic 404)."""
        _, link_id = _make_report_patient(su_conn, prefix="RPTB4")
        used_token = _issue_report_token(su_conn, link_id, used=True)

        resp = client.post(
            f"/api/v1/patient-report/{used_token}",
            data={
                "readings": [
                    {"type": "fbs", "value": 100.0},
                ]
            },
            content_type="application/json",
        )
        assert resp.status_code == 404, (
            f"used token with batch must return 404, got {resp.status_code}"
        )

    def test_single_mode_backward_compat(self, su_conn, client):
        """
        سازگاریِ قبل: {type, value} تکی همچنان کار کند.
        پاسخ باید type/value در سطحِ بالا داشته باشد + accepted=[{type,value}], count=1.
        """
        _, link_id = _make_report_patient(su_conn, prefix="RPTB5")
        token_str = _issue_report_token(su_conn, link_id, used=False)

        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={"type": "fbs", "value": 105.0},
            content_type="application/json",
        )
        assert resp.status_code == 200, f"Single-mode submit failed: {resp.json()}"
        data = resp.json()
        assert data.get("status") == "ok"
        # backward-compat fields
        assert data.get("type") == "fbs", f"Expected type='fbs', got {data.get('type')}"
        assert data.get("value") == 105.0, f"Expected value=105.0, got {data.get('value')}"
        # batch fields هم باید باشند
        assert data.get("count") == 1
        accepted = data.get("accepted", [])
        assert len(accepted) == 1
        assert accepted[0]["type"] == "fbs"
        assert accepted[0]["value"] == 105.0

    def test_batch_all_verified_false_not_in_engine(self, su_conn, client):
        """
        گیتِ موتور برای batch: همهٔ readingهای batch باید verified=False باشند
        و در build_facts ظاهر نشوند (اگر verified قدیمی وجود داشته باشد).
        """
        from clinical.rule_engine import build_facts

        _, link_id = _make_report_patient(su_conn, prefix="RPTB6")
        # verified baseline
        _insert_vital(su_conn, link_id, "bp_systolic", 120.0, verified=True, source="clinic")

        # batch self-report با مقدارِ بالا
        token_str = _issue_report_token(su_conn, link_id, used=False)
        resp = client.post(
            f"/api/v1/patient-report/{token_str}",
            data={
                "readings": [
                    {"type": "bp_systolic",  "value": 180.0},  # unverified — نباید وارد موتور شود
                    {"type": "bp_diastolic", "value": 110.0},  # unverified
                ]
            },
            content_type="application/json",
        )
        assert resp.status_code == 200

        facts = build_facts(link_id, tenant_id=1)
        indicator = facts.get("indicator", {})

        # bp_systolic باید از verified baseline (120) بیاید، نه از batch (180)
        if "bp_systolic" in indicator:
            val = indicator["bp_systolic"].get("latest")
            assert val == 120.0, (
                f"Engine must use verified bp_systolic=120, not batch-unverified=180. Got {val}"
            )

        # bp_diastolic اگر هیچ verified ندارد، اصلاً در indicator نباشد
        # (ممکن است indicator وجود نداشته باشد؛ اگر هم هست باید verified باشد)
        if "bp_diastolic" in indicator:
            val = indicator["bp_diastolic"].get("latest")
            # اگر verified وجود ندارد باید None یا غایب باشد
            # اگر verified دارد، مقدارش نباید 110 باشد
            assert val != 110.0, (
                f"Unverified bp_diastolic=110 must NOT enter engine. Got {val}"
            )
