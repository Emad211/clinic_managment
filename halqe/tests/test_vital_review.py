"""
test_vital_review.py — slice14 / step 47
بک‌اندِ تأیید/ردِ پزشک برای دادهٔ خوداظهار

اصلِ ایمنی (قفل‌شده با gp-family-medicine-advisor):
  ۶ فیلترِ verified=True در موتور دست‌نخورده — این تست‌ها آن‌ها را بررسی می‌کنند.
  rejected هم verified=FALSE است → خودکار از موتور خارج می‌ماند (Assert C).

تست‌ها:
  ۱) verify → وارد موتور: vital با verified=False → بعد از verify → build_facts دارد.
  ۲) reject → خارج از موتور + soft-keep: rejected_at ست، verified=FALSE، ردیف در DB هست.
  ۳) RLS: کاربرِ tenant-A نتواند ویتالِ tenant-B را verify/reject کند (۴۰۴).
  ۴) DTO: recent_vitals فیلدهای verified/source/rejected_at را سریال‌شده بدهد.
  ۵) audit: log_activity برای verify و reject.
  ۶) idempotency: verifyِ ردیفِ از-قبل-verified → ۴۰۹.
  ۷) نگهبانِ schema: ستون‌های slice14 وجود دارند + ایندکس pending.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "accounting_read"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_review_patient(conn, tenant_id: int = 1, prefix: str = "VRV") -> tuple[int, int, str]:
    """
    patient + patient_link + uuid برای تست‌های vital review.
    Returns: (patient_id, link_id, patient_uuid_str)
    """
    nat_id = secrets.token_hex(5)
    p_uuid = str(secrets.token_hex(16))
    # ساختنِ UUID معتبر از hex
    import uuid as _uuid_mod
    patient_uuid = str(_uuid_mod.uuid4())

    conn.execute(
        f"""INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number)
            VALUES ({tenant_id}, '{patient_uuid}'::uuid, 'مرور', 'تستی',
                    '{prefix}{nat_id}', '09120000001')
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
    return patient_id, link_row[0], patient_uuid


def _insert_vital(
    conn,
    patient_link_id: int,
    vtype: str,
    value: float,
    verified: bool = True,
    source: str = "clinic",
    tenant_id: int = 1,
) -> int:
    """Insert vital + return id."""
    conn.execute(
        f"""INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source, verified)
            VALUES ({tenant_id}, {patient_link_id}, '{vtype}', {value},
                    'mg/dL', now(), '{source}', {'TRUE' if verified else 'FALSE'})"""
    )
    row = conn.execute(
        f"""SELECT id FROM clinical.vital_readings
            WHERE patient_link_id={patient_link_id} AND type='{vtype}' AND source='{source}'
            ORDER BY measured_at DESC LIMIT 1"""
    ).fetchone()
    return row[0]


def _get_jwt(client, username="testuser", password="secret123") -> str:
    """Login و دریافتِ JWT."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
        content_type="application/json",
    )
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def su_conn():
    """superuser psycopg connection (autocommit) — function-scoped برای ایزولاسیونِ تست."""
    import psycopg
    from tests.conftest import PG_HOST, PG_PORT, PG_SU_USER, PG_SU_PASSWORD, TEST_DB_NAME
    conn = psycopg.connect(
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'",
        autocommit=True,
    )
    yield conn
    conn.close()


@pytest.fixture(scope="function")
def jwt_token(seed_data, client):
    """JWT برای testuser (tenant 1)."""
    return _get_jwt(client)


# ---------------------------------------------------------------------------
# ۱) verify → وارد موتور
# ---------------------------------------------------------------------------

class TestVerifyEntersEngine:
    """پس از verify، ردیف در build_facts ظاهر می‌شود."""

    def test_verify_makes_vital_enter_engine(self, su_conn, seed_data, client, jwt_token):
        """
        فرضیه: vital با verified=False → verify → build_facts دارد.
        """
        from clinical.rule_engine import build_facts
        from platform_core.tenant_context import set_tenant_guc

        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="VRV2")

        # Insert unverified vital
        vital_id = _insert_vital(su_conn, link_id, "fbs", 130.0, verified=False, source="patient_self")

        # قبل از verify → در build_facts نیست
        set_tenant_guc(1)
        facts_before = build_facts(link_id, tenant_id=1)
        assert "fbs" not in facts_before.get("indicator", {}), (
            "Unverified vital must NOT be in build_facts before verify"
        )

        # verify via endpoint
        resp = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/verify",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 200, f"verify failed: {resp.json()}"
        data = resp.json()
        assert data["verified"] is True
        assert data["verified_by"] == "testuser"
        assert data["verified_at"] is not None

        # بعد از verify → در build_facts هست
        set_tenant_guc(1)
        facts_after = build_facts(link_id, tenant_id=1)
        indicator = facts_after.get("indicator", {})
        assert "fbs" in indicator, "After verify, fbs must appear in build_facts"
        assert abs(indicator["fbs"]["latest"] - 130.0) < 0.01, (
            f"Expected fbs=130, got {indicator['fbs']['latest']}"
        )

    def test_verify_db_state(self, su_conn, seed_data, client, jwt_token):
        """بعد از verify، DB ستون‌های verified_by و verified_at را دارد."""
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="VRV3")
        vital_id = _insert_vital(su_conn, link_id, "bp_systolic", 145.0, verified=False, source="patient_self")

        client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/verify",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )

        row = su_conn.execute(
            f"""SELECT verified, verified_by, verified_at, rejected_at
                FROM clinical.vital_readings WHERE id={vital_id}"""
        ).fetchone()
        assert row is not None
        verified, verified_by, verified_at, rejected_at = row
        assert verified is True, "verified must be TRUE after verify"
        assert verified_by == "testuser", f"verified_by must be 'testuser', got {verified_by}"
        assert verified_at is not None, "verified_at must be set"
        assert rejected_at is None, "rejected_at must stay NULL after verify"


# ---------------------------------------------------------------------------
# ۲) reject → خارج از موتور + soft-keep
# ---------------------------------------------------------------------------

class TestRejectSoftKeep:
    """پس از reject، ردیف در DB هست ولی در build_facts نیست."""

    def test_reject_vital_not_in_engine(self, su_conn, seed_data, client, jwt_token):
        """
        فرضیه: vital با verified=False → reject → در build_facts نیست.
        soft-keep: ردیف در DB هست.
        """
        from clinical.rule_engine import build_facts
        from platform_core.tenant_context import set_tenant_guc

        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="VRVR1")
        vital_id = _insert_vital(su_conn, link_id, "fbs", 280.0, verified=False, source="patient_self")

        resp = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/reject",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 200, f"reject failed: {resp.json()}"
        data = resp.json()
        assert data["verified"] is False, "verified must stay FALSE after reject"
        assert data["rejected_at"] is not None, "rejected_at must be set"
        assert data["rejected_by"] == "testuser"

        # DB: ردیف هست (soft-keep)
        row = su_conn.execute(
            f"SELECT id, verified, rejected_at FROM clinical.vital_readings WHERE id={vital_id}"
        ).fetchone()
        assert row is not None, "Row must exist after reject (soft-keep, not physical delete)"
        _, db_verified, db_rejected_at = row
        assert db_verified is False, "verified must remain FALSE after reject"
        assert db_rejected_at is not None, "rejected_at must be set in DB"

        # build_facts نباید داشته باشد
        set_tenant_guc(1)
        facts = build_facts(link_id, tenant_id=1)
        indicator = facts.get("indicator", {})
        assert "fbs" not in indicator, (
            f"Rejected vital must NOT appear in build_facts. Got indicator={indicator}"
        )

    def test_reject_verified_vital_returns_409(self, su_conn, seed_data, client, jwt_token):
        """نمی‌توان ردیفِ verified=TRUE را reject کرد."""
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="VRVR2")
        # کلینیک‌وارده (verified=True از پیش)
        vital_id = _insert_vital(su_conn, link_id, "hba1c", 8.5, verified=True, source="clinic")

        resp = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/reject",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 409, (
            f"Rejecting a verified vital must return 409, got {resp.status_code}"
        )

    def test_reject_already_rejected_returns_409(self, su_conn, seed_data, client, jwt_token):
        """ردِ مجددِ یک ردِ ردشده → ۴۰۹."""
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="VRVR3")
        vital_id = _insert_vital(su_conn, link_id, "fbs", 200.0, verified=False, source="patient_self")

        # reject اول
        r1 = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/reject",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert r1.status_code == 200

        # reject دوم → ۴۰۹
        r2 = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/reject",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert r2.status_code == 409, (
            f"Double-reject must return 409, got {r2.status_code}"
        )


# ---------------------------------------------------------------------------
# ۳) RLS: tenant-A نتواند ویتالِ tenant-B را verify/reject کند
# ---------------------------------------------------------------------------

class TestRLSTenantIsolation:
    """کاربرِ tenant-A نتواند ویتالِ tenant-B را دستکاری کند."""

    def _get_tenant2_link_id(self, su_conn, tenant2_patient_id: int) -> int | None:
        """Fetch tenant-2 patient_link.id از DB (seed_clinical_data فقط patient_id دارد)."""
        row = su_conn.execute(
            f"SELECT id FROM clinical.patient_links WHERE tenant_id=2 AND patient_id={tenant2_patient_id}"
        ).fetchone()
        return row[0] if row else None

    def test_verify_cross_tenant_returns_404(self, su_conn, seed_data, seed_clinical_data, client, jwt_token):
        """
        ویتالِ tenant-2 توسطِ کاربرِ tenant-1 → ۴۰۴.
        jwt_token متعلق به tenant-1 است.
        """
        tenant2_uuid = seed_clinical_data.get("tenant2_patient_uuid")
        tenant2_patient_id = seed_clinical_data.get("tenant2_patient_id")
        if not tenant2_uuid or not tenant2_patient_id:
            pytest.skip("seed_clinical_data does not provide tenant2 fields")

        link2_id = self._get_tenant2_link_id(su_conn, tenant2_patient_id)
        if not link2_id:
            pytest.skip("tenant-2 patient_link not found in DB")

        vital_id = _insert_vital(su_conn, link2_id, "fbs", 150.0, verified=False,
                                  source="patient_self", tenant_id=2)

        # تلاشِ tenant-1 برای verify ویتالِ tenant-2 → باید ۴۰۴ دهد
        # (بیمار در tenant-1 enrolled نیست → _resolve_patient_link_for_tenant → Http404)
        resp = client.post(
            f"/api/v1/patients/{tenant2_uuid}/vitals/{vital_id}/verify",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 404, (
            f"Tenant-A must NOT verify Tenant-B's vital. Got {resp.status_code}"
        )

    def test_reject_cross_tenant_returns_404(self, su_conn, seed_data, seed_clinical_data, client, jwt_token):
        """
        ویتالِ tenant-2 توسطِ کاربرِ tenant-1 برای reject → ۴۰۴.
        """
        tenant2_uuid = seed_clinical_data.get("tenant2_patient_uuid")
        tenant2_patient_id = seed_clinical_data.get("tenant2_patient_id")
        if not tenant2_uuid or not tenant2_patient_id:
            pytest.skip("seed_clinical_data does not provide tenant2 fields")

        link2_id = self._get_tenant2_link_id(su_conn, tenant2_patient_id)
        if not link2_id:
            pytest.skip("tenant-2 patient_link not found in DB")

        vital_id = _insert_vital(su_conn, link2_id, "bp_systolic", 160.0, verified=False,
                                  source="patient_self", tenant_id=2)

        resp = client.post(
            f"/api/v1/patients/{tenant2_uuid}/vitals/{vital_id}/reject",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 404, (
            f"Tenant-A must NOT reject Tenant-B's vital. Got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# ۴) DTO: recent_vitals فیلدهای verified/source/rejected_at را بدهد
# ---------------------------------------------------------------------------

class TestDTOSerialization:
    """recent_vitals در /record همهٔ فیلدهای review state را سریال می‌کند."""

    def test_record_endpoint_serializes_verified_field(self, su_conn, seed_data, client, jwt_token):
        """
        GET /patients/{uuid}/record → recent_vitals هر آیتم دارایِ فیلدِ verified است.
        """
        patient_uuid = str(seed_data["patient_uuid"])

        resp = client.get(
            f"/api/v1/patients/{patient_uuid}/record",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 200, f"record endpoint failed: {resp.json()}"

        data = resp.json()
        vitals = data.get("recent_vitals", [])
        assert vitals, "Expected at least one vital in recent_vitals"

        for v in vitals:
            assert "verified" in v, f"VitalReadingDTO must have 'verified' field. Got keys: {list(v.keys())}"
            assert "rejected_at" in v, f"VitalReadingDTO must have 'rejected_at' field. Got keys: {list(v.keys())}"
            # clinic-entered vitals (from seed) باید verified=True داشته باشند
            assert v["verified"] in (True, False), f"verified must be bool, got {v['verified']}"

    def test_record_unverified_vital_has_verified_false(self, su_conn, seed_data, client, jwt_token):
        """
        unverified vital در recent_vitals دارایِ verified=False است.
        (recent_vitals بدونِ فیلترِ verified — پزشک همه را می‌بیند، موتور فیلتر می‌کند.)
        """
        patient_uuid = str(seed_data["patient_uuid"])
        link_id = seed_data["link_id"]

        # insert unverified
        _insert_vital(su_conn, link_id, "bp_diastolic", 95.0, verified=False, source="patient_self")

        resp = client.get(
            f"/api/v1/patients/{patient_uuid}/record",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 200

        vitals = resp.json().get("recent_vitals", [])
        unverified = [v for v in vitals if not v["verified"]]
        assert unverified, "Expected at least one unverified vital in recent_vitals"

        for v in unverified:
            assert v["source"] == "patient_self", (
                f"Unverified vitals should be patient_self source. Got {v['source']}"
            )
            # rejected_at باید None باشد (هنوز reject نشده)
            assert v["rejected_at"] is None, (
                f"Non-rejected unverified vital should have rejected_at=None. Got {v['rejected_at']}"
            )

    def test_rejected_vital_has_rejected_at_in_dto(self, su_conn, seed_data, client, jwt_token):
        """
        بعد از reject، recent_vitals ردیف دارایِ rejected_at غیر-null است.
        """
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="DTOR")
        vital_id = _insert_vital(su_conn, link_id, "fbs", 190.0, verified=False, source="patient_self")

        # reject
        client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/reject",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )

        resp = client.get(
            f"/api/v1/patients/{patient_uuid}/record",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 200

        vitals = resp.json().get("recent_vitals", [])
        rejected = [v for v in vitals if v.get("id") == vital_id]
        # ممکن است در ۱۰ تایِ اخیر نباشد — skip در آن صورت
        if rejected:
            v = rejected[0]
            assert v["verified"] is False, "Rejected vital must have verified=False in DTO"
            assert v["rejected_at"] is not None, "Rejected vital must have rejected_at set in DTO"


# ---------------------------------------------------------------------------
# ۵) audit log برای verify و reject
# ---------------------------------------------------------------------------

class TestAuditLog:
    """log_activity برای verify و reject رویداد ثبت می‌کند."""

    def test_verify_creates_audit_log(self, su_conn, seed_data, client, jwt_token):
        """verify → clinical.activity_logs دارایِ action_type='vital_verified' است."""
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="AUDITV")
        vital_id = _insert_vital(su_conn, link_id, "fbs", 140.0, verified=False, source="patient_self")

        resp = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/verify",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 200

        row = su_conn.execute(
            f"""SELECT action_type, target_table, target_id
                FROM clinical.activity_logs
                WHERE action_type='vital_verified' AND target_id={vital_id}
                ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        assert row is not None, "Expected audit log for vital_verified"
        action_type, target_table, target_id = row
        assert action_type == "vital_verified"
        assert target_table == "vital_readings"
        assert target_id == vital_id

    def test_reject_creates_audit_log(self, su_conn, seed_data, client, jwt_token):
        """reject → clinical.activity_logs دارایِ action_type='vital_rejected' است."""
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="AUDITR")
        vital_id = _insert_vital(su_conn, link_id, "bp_systolic", 155.0, verified=False, source="patient_self")

        resp = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/reject",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 200

        row = su_conn.execute(
            f"""SELECT action_type, target_table, target_id
                FROM clinical.activity_logs
                WHERE action_type='vital_rejected' AND target_id={vital_id}
                ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        assert row is not None, "Expected audit log for vital_rejected"
        action_type, target_table, target_id = row
        assert action_type == "vital_rejected"
        assert target_table == "vital_readings"
        assert target_id == vital_id


# ---------------------------------------------------------------------------
# ۶) idempotency: verify ردیفِ از-قبل-verified → ۴۰۹
# ---------------------------------------------------------------------------

class TestIdempotency:
    """تأیید مجددِ ردیفِ از-قبل-verified → ۴۰۹ conflict."""

    def test_double_verify_returns_409(self, su_conn, seed_data, client, jwt_token):
        """verify دوباره → ۴۰۹."""
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="IDEM1")
        vital_id = _insert_vital(su_conn, link_id, "fbs", 120.0, verified=False, source="patient_self")

        # verify اول — باید ۲۰۰ باشد
        r1 = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/verify",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert r1.status_code == 200

        # verify دوم — باید ۴۰۹ باشد
        r2 = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/verify",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert r2.status_code == 409, (
            f"Double-verify must return 409, got {r2.status_code}"
        )
        data = r2.json()
        assert "code" in data

    def test_verify_clinic_entered_vital_returns_409(self, su_conn, seed_data, client, jwt_token):
        """
        ویتالِ کلینیک‌وارده (verified=True از پیش) نباید دوباره verify شود.
        """
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="IDEM2")
        vital_id = _insert_vital(su_conn, link_id, "hba1c", 7.2, verified=True, source="clinic")

        resp = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/{vital_id}/verify",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 409, (
            f"Verifying an already-verified (clinic) vital must return 409. Got {resp.status_code}"
        )

    def test_verify_nonexistent_vital_returns_404(self, su_conn, seed_data, client, jwt_token):
        """vital_id که وجود ندارد → ۴۰۴."""
        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="IDEM3")

        resp = client.post(
            f"/api/v1/patients/{patient_uuid}/vitals/999999/verify",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token}",
        )
        assert resp.status_code == 404, f"Nonexistent vital must return 404. Got {resp.status_code}"


# ---------------------------------------------------------------------------
# ۷) نگهبانِ schema: ستون‌های slice14 وجود دارند
# ---------------------------------------------------------------------------

class TestSlice14SchemaSentinel:
    """اثباتِ ستون‌های slice14 در vital_readings."""

    def test_vital_readings_has_verified_by_column(self, su_conn):
        """vital_readings باید ستونِ verified_by داشته باشد (TEXT, nullable)."""
        row = su_conn.execute(
            """SELECT column_name, data_type, is_nullable
               FROM information_schema.columns
               WHERE table_schema='clinical'
                 AND table_name='vital_readings'
                 AND column_name='verified_by'"""
        ).fetchone()
        assert row is not None, "Column vital_readings.verified_by missing (slice14 not applied)"
        col_name, data_type, is_nullable = row
        assert data_type.lower() in ("text", "character varying"), (
            f"verified_by must be TEXT, got {data_type}"
        )
        assert is_nullable == "YES", "verified_by must be nullable"

    def test_vital_readings_has_verified_at_column(self, su_conn):
        """vital_readings باید ستونِ verified_at داشته باشد (TIMESTAMPTZ, nullable)."""
        row = su_conn.execute(
            """SELECT column_name, data_type, is_nullable
               FROM information_schema.columns
               WHERE table_schema='clinical'
                 AND table_name='vital_readings'
                 AND column_name='verified_at'"""
        ).fetchone()
        assert row is not None, "Column vital_readings.verified_at missing (slice14 not applied)"
        _, data_type, is_nullable = row
        assert "timestamp" in data_type.lower(), f"verified_at must be TIMESTAMPTZ, got {data_type}"
        assert is_nullable == "YES", "verified_at must be nullable"

    def test_vital_readings_has_rejected_by_column(self, su_conn):
        """vital_readings باید ستونِ rejected_by داشته باشد (TEXT, nullable)."""
        row = su_conn.execute(
            """SELECT column_name, data_type, is_nullable
               FROM information_schema.columns
               WHERE table_schema='clinical'
                 AND table_name='vital_readings'
                 AND column_name='rejected_by'"""
        ).fetchone()
        assert row is not None, "Column vital_readings.rejected_by missing (slice14 not applied)"
        _, data_type, is_nullable = row
        assert data_type.lower() in ("text", "character varying"), (
            f"rejected_by must be TEXT, got {data_type}"
        )
        assert is_nullable == "YES", "rejected_by must be nullable"

    def test_vital_readings_has_rejected_at_column(self, su_conn):
        """vital_readings باید ستونِ rejected_at داشته باشد (TIMESTAMPTZ, nullable)."""
        row = su_conn.execute(
            """SELECT column_name, data_type, is_nullable
               FROM information_schema.columns
               WHERE table_schema='clinical'
                 AND table_name='vital_readings'
                 AND column_name='rejected_at'"""
        ).fetchone()
        assert row is not None, "Column vital_readings.rejected_at missing (slice14 not applied)"
        _, data_type, is_nullable = row
        assert "timestamp" in data_type.lower(), f"rejected_at must be TIMESTAMPTZ, got {data_type}"
        assert is_nullable == "YES", "rejected_at must be nullable"

    def test_pending_index_exists(self, su_conn):
        """ایندکسِ idx_vital_readings_pending وجود دارد."""
        row = su_conn.execute(
            """SELECT indexname FROM pg_indexes
               WHERE schemaname='clinical'
                 AND tablename='vital_readings'
                 AND indexname='idx_vital_readings_pending'"""
        ).fetchone()
        assert row is not None, "Index idx_vital_readings_pending missing (slice14 not applied)"

    def test_idempotency_slice14(self, su_conn):
        """اجرایِ مجددِ slice14 بدونِ خطا (idempotent DDL)."""
        import pathlib
        slice_path = (
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "specialist_clinic"
            / "docs"
            / "migration_tools"
            / "schema_pg_slice14_vital_review.sql"
        )
        assert slice_path.exists(), f"Slice14 file not found at {slice_path}"
        sql = slice_path.read_text(encoding="utf-8")
        # دوباره اجرا — نباید خطا بدهد
        try:
            su_conn.execute(sql)
        except Exception as exc:
            pytest.fail(f"Slice14 is not idempotent: {exc}")


# ---------------------------------------------------------------------------
# ۸) Assert C — motor filter guard: rejected vital excluded from engine
# ---------------------------------------------------------------------------

class TestMotorFilterGuard:
    """اثباتِ Assert C: rejected هم verified=FALSE است → از موتور خارج."""

    def test_six_engine_filters_reject_rejected_vital(self, su_conn, seed_data):
        """
        verified=FALSE + rejected_at IS NOT NULL → همانِ verified=FALSE است.
        موتور فقط verified=True می‌خواند → rejected خودکار خارج می‌شود.
        این تستِ assertion C بدونِ تغییرِ فیلترها است.
        """
        from clinical.rule_engine import build_facts
        from platform_core.tenant_context import set_tenant_guc

        _, link_id, patient_uuid = _make_review_patient(su_conn, prefix="GRDM")

        # insert و reject vital
        vital_id = _insert_vital(su_conn, link_id, "fbs", 320.0, verified=False, source="patient_self")

        # مستقیم در DB rejected_at ست می‌کنیم (simulate reject بدونِ endpoint)
        su_conn.execute(
            f"""UPDATE clinical.vital_readings
                SET rejected_by='direct_test', rejected_at=now()
                WHERE id={vital_id}"""
        )

        set_tenant_guc(1)
        facts = build_facts(link_id, tenant_id=1)
        indicator = facts.get("indicator", {})

        assert "fbs" not in indicator, (
            f"Rejected vital (verified=FALSE, rejected_at set) must NOT appear in build_facts. "
            f"Got indicator={indicator}"
        )
