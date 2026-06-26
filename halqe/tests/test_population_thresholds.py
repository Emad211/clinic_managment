"""
test_population_thresholds.py — قدمِ ۳۹: مکانیزمِ گرید red-flag per-population

تست‌ها:
  ۱) patient_populations: منطقِ gate برای هر زیرجمعیت
  ۲) draft inert (مهم‌ترین): override در حالتِ draft هیچ تغییری در رفتار ندارد
  ۳) مکانیزم با approved: اگر ردیفِ frail/hba1c approved شود، آستانه‌ها تغییر می‌کنند
  ۴) young_lowrisk approved: آستانهٔ تنگ‌تر اعمال می‌شود
  ۵) عدمِ regression: کلِ سوئیتِ red-flag/level/suggestion بدون تغییر سبز
  ۶) API: GET /manager/population-thresholds با manager → 200 + draftها؛ با staff → 403
  ۷) نگهبان schema: جدول + RLS + GRANT + شمارشِ seedِ draft + idempotency
"""
import copy
import uuid
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api
from clinical.population_service import patient_populations, apply_population_overrides
from clinical.models import PopulationThreshold

# ── DB connection params (same as conftest) ───────────────────────────────────
_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_token(username: str, password: str) -> str:
    """Get a JWT token for the given user."""
    client = TestClient(api)
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()["token"]


# ===========================================================================
# ۱) patient_populations — منطقِ gate
# ===========================================================================

class TestPatientPopulations:
    """Unit tests for patient_populations() — no DB required."""

    def test_frail_by_flag_complex(self):
        """frailty='complex' → frail"""
        pops = patient_populations({"frailty": "complex"}, age=50)
        assert "frail" in pops

    def test_frail_by_age_75(self):
        """age=75, بدونِ frailty → frail"""
        pops = patient_populations({}, age=75)
        assert "frail" in pops

    def test_frail_by_age_76(self):
        """age=76 → frail"""
        pops = patient_populations({"frailty": "robust"}, age=76)
        assert "frail" in pops

    def test_not_frail_age_74_robust(self):
        """age=74 + frailty='robust' → NOT frail"""
        pops = patient_populations({"frailty": "robust"}, age=74)
        assert "frail" not in pops

    def test_hypo_high(self):
        """hypo_risk='high' → hypo_high"""
        pops = patient_populations({"hypo_risk": "high"}, age=50)
        assert "hypo_high" in pops

    def test_not_hypo_high_atrisk(self):
        """hypo_risk='atrisk' → NOT hypo_high (فقط 'high' trigger است)"""
        pops = patient_populations({"hypo_risk": "atrisk"}, age=50)
        assert "hypo_high" not in pops

    def test_young_lowrisk_minimal(self):
        """age=30, بدون flag → young_lowrisk"""
        pops = patient_populations({}, age=30)
        assert "young_lowrisk" in pops

    def test_young_lowrisk_with_robust(self):
        """age=40, frailty='robust', hypo_risk='low' → young_lowrisk"""
        pops = patient_populations({"frailty": "robust", "hypo_risk": "low"}, age=40)
        assert "young_lowrisk" in pops

    def test_not_young_lowrisk_age_45(self):
        """age=45 → NOT young_lowrisk (gate: age<45 strict)"""
        pops = patient_populations({}, age=45)
        assert "young_lowrisk" not in pops

    def test_not_young_lowrisk_complex(self):
        """frailty='complex' → NOT young_lowrisk"""
        pops = patient_populations({"frailty": "complex"}, age=30)
        assert "young_lowrisk" not in pops

    def test_not_young_lowrisk_hypo_high(self):
        """hypo_risk='high' → NOT young_lowrisk"""
        pops = patient_populations({"hypo_risk": "high"}, age=30)
        assert "young_lowrisk" not in pops

    def test_empty_all_flags_none_age_50(self):
        """بیمارِ معمولی: age=50, بدونِ flag → set خالی"""
        pops = patient_populations({}, age=50)
        assert pops == set()

    def test_frail_and_hypo_high_together(self):
        """TEST0007-style: frailty=complex + hypo_risk=high → هر دو"""
        pops = patient_populations({"frailty": "complex", "hypo_risk": "high"}, age=70)
        assert "frail" in pops
        assert "hypo_high" in pops

    def test_age_none_no_age_gate(self):
        """age=None → frail از طریقِ age نمی‌شود؛ hypo_high ممکن است"""
        pops = patient_populations({"hypo_risk": "high"}, age=None)
        assert "hypo_high" in pops
        assert "young_lowrisk" not in pops  # age=None → young_lowrisk gate ناکام

    def test_age_none_frail_via_flag(self):
        """age=None + frailty=complex → frail (از طریقِ flag نه age)"""
        pops = patient_populations({"frailty": "complex"}, age=None)
        assert "frail" in pops


# ===========================================================================
# ۲) draft inert — مهم‌ترین تست ایمنی
# ===========================================================================

class TestDraftInert:
    """
    تأیید می‌کند که override در حالتِ draft هیچ تغییری در indicator_map ایجاد نمی‌کند.
    seed همه 'draft' است، پس در شرایطِ عادی apply_population_overrides باید
    indicator_map را دست‌نخورده برگرداند.
    """

    @pytest.mark.django_db
    def test_draft_overrides_do_not_change_indicator_map(self, seed_clinical_data):
        """
        بیمارِ frail با HbA1c=8.5 — override draft است → indicator_map دست‌نخورده.
        (این مهم‌ترینِ اصلِ ایمنی است — draft هرگز زنده نمی‌شود)
        """
        from clinical.models import ClinicalIndicator

        tenant_id = 1
        indicator_map = {
            row.key: row
            for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
        }

        # مطمئن شو که هیچ approved وجود ندارد (seed همه draft هستند)
        approved_count = PopulationThreshold.objects.filter(
            tenant_id=tenant_id, approval_status="approved"
        ).count()
        assert approved_count == 0, (
            f"Unexpected approved overrides in seed: {approved_count}. "
            "Seed should only contain 'draft' rows."
        )

        # بیمارِ frail + hypo_high (TEST0007-like)
        pops = patient_populations({"frailty": "complex", "hypo_risk": "high"}, age=70)
        result_map = apply_population_overrides(indicator_map, pops, tenant_id)

        # چون همه draft هستند، indicator_map باید دست‌نخورده باشد
        # (apply_population_overrides همان object برمی‌گرداند — identity check)
        assert result_map is indicator_map, (
            "apply_population_overrides should return the base indicator_map "
            "unchanged when all overrides are 'draft'."
        )

    @pytest.mark.django_db
    def test_draft_hba1c_level_unchanged(self, seed_clinical_data):
        """
        HbA1c=8.5 برای بیمارِ frail:
        پایه: warn=7.0, danger=8.0 → 8.5 باید 'danger' بماند.
        (اگر override draft بود و فعال می‌شد: warn=8.0, danger=9.0 → 8.5 می‌شد 'warn')
        """
        from clinical.models import ClinicalIndicator
        from clinical.rule_engine import _evaluate_reading

        tenant_id = 1
        indicator_map = {
            row.key: row
            for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
        }

        pops = patient_populations({"frailty": "complex"}, age=75)
        effective_map = apply_population_overrides(indicator_map, pops, tenant_id)

        # با draft: effective_map همان base است → danger=8.0 → 8.5 = 'danger'
        level = _evaluate_reading("hba1c", 8.5, effective_map)
        assert level == "danger", (
            f"Expected 'danger' for HbA1c=8.5 with base thresholds (draft overrides inactive), "
            f"got '{level}'"
        )


# ===========================================================================
# ۳) مکانیزم با approved — اثباتِ کارِ override
# ===========================================================================

class TestApprovedOverrideMechanism:
    """
    در تست موقتاً یک ردیف را approve می‌کنیم تا مکانیزم را اثبات کنیم.
    این approve فقط در تست است — seed همیشه draft باقی می‌ماند.
    """

    @pytest.mark.django_db(transaction=True)
    def test_approved_frail_hba1c_changes_level(self, seed_clinical_data):
        """
        اگر override frail/hba1c را approved کنیم:
        - HbA1c=8.5 با پایه: 'danger' (danger=8.0)
        - HbA1c=8.5 با override approved (danger=9.0): باید 'warn' شود (warn=8.0)
        """
        from clinical.models import ClinicalIndicator
        from clinical.rule_engine import _evaluate_reading

        tenant_id = 1
        indicator_map = {
            row.key: row
            for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
        }

        # تأییدِ موقت (فقط در تست — rollback می‌شود چون transaction=True)
        updated = PopulationThreshold.objects.filter(
            tenant_id=tenant_id,
            indicator_key="hba1c",
            population_key="frail",
            bound="high",
        ).update(approval_status="approved", approved_by="test_physician")
        assert updated == 1, "frail/hba1c override row not found in DB"

        pops = patient_populations({"frailty": "complex"}, age=75)
        effective_map = apply_population_overrides(indicator_map, pops, tenant_id)

        # با override approved (warn=8.0, danger=9.0): 8.5 باید 'warn' باشد
        level = _evaluate_reading("hba1c", 8.5, effective_map)
        assert level == "warn", (
            f"Expected 'warn' for HbA1c=8.5 with approved frail override "
            f"(warn=8.0, danger=9.0), got '{level}'"
        )

        # ۹.۵ باید 'danger' باشد (بالاتر از danger=9.0 در override)
        level_95 = _evaluate_reading("hba1c", 9.5, effective_map)
        assert level_95 == "danger", (
            f"Expected 'danger' for HbA1c=9.5 with approved frail override, got '{level_95}'"
        )

    @pytest.mark.django_db(transaction=True)
    def test_approved_frail_does_not_affect_non_frail(self, seed_clinical_data):
        """
        override frail/hba1c approved → تنها بیمارِ frail تأثیر می‌گیرد.
        بیمارِ معمولی (age=50, بدونِ flag) همچنان threshold پایه دارد.
        """
        from clinical.models import ClinicalIndicator
        from clinical.rule_engine import _evaluate_reading

        tenant_id = 1
        indicator_map = {
            row.key: row
            for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
        }

        # approve کن
        PopulationThreshold.objects.filter(
            tenant_id=tenant_id,
            indicator_key="hba1c",
            population_key="frail",
            bound="high",
        ).update(approval_status="approved", approved_by="test_physician")

        # بیمارِ معمولی
        ordinary_pops = patient_populations({}, age=50)
        effective_ordinary = apply_population_overrides(indicator_map, ordinary_pops, tenant_id)

        # برای بیمارِ معمولی: effective_map == base (identity)
        assert effective_ordinary is indicator_map, (
            "Non-frail patient should get the base indicator_map unchanged."
        )

        # پس level هم باید پایه‌ای باشد: 8.5 → 'danger' (danger=8.0 پایه)
        level = _evaluate_reading("hba1c", 8.5, effective_ordinary)
        assert level == "danger"


# ===========================================================================
# ۴) young_lowrisk approved — آستانهٔ تنگ‌تر
# ===========================================================================

class TestYoungLowriskApproved:

    @pytest.mark.django_db(transaction=True)
    def test_approved_young_lowrisk_tighter_threshold(self, seed_clinical_data):
        """
        young_lowrisk hba1c approved (warn=6.5, پایه warn=7.0):
        HbA1c=6.7 → با پایه 'ok'؛ با override 'warn'
        """
        from clinical.models import ClinicalIndicator
        from clinical.rule_engine import _evaluate_reading

        tenant_id = 1
        indicator_map = {
            row.key: row
            for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
        }

        # قبل از approve: 6.7 < 7.0 → 'ok'
        pops = patient_populations({}, age=30)
        base_level = _evaluate_reading("hba1c", 6.7, indicator_map)
        assert base_level == "ok", f"Expected 'ok' before override, got '{base_level}'"

        # approve کن
        PopulationThreshold.objects.filter(
            tenant_id=tenant_id,
            indicator_key="hba1c",
            population_key="young_lowrisk",
            bound="high",
        ).update(approval_status="approved", approved_by="test_physician")

        effective_map = apply_population_overrides(indicator_map, pops, tenant_id)

        # بعد از approve: 6.7 >= 6.5 → 'warn'
        level = _evaluate_reading("hba1c", 6.7, effective_map)
        assert level == "warn", (
            f"Expected 'warn' for HbA1c=6.7 with approved young_lowrisk override "
            f"(warn=6.5), got '{level}'"
        )


# ===========================================================================
# ۵) عدمِ regression — تستِ مکمل (اثبات با suite موجود)
# ===========================================================================

class TestNoRegression:
    """
    تأیید می‌کند که رفتارِ موجودِ red-flag/level با seed draft دست‌نخورده است.
    این‌ها "golden path" هستند که نباید با قدمِ ۳۹ تغییر کنند.
    """

    @pytest.mark.django_db
    def test_base_hba1c_thresholds_unchanged(self, seed_clinical_data):
        """آستانه‌های پایهٔ HbA1c بدونِ population override."""
        from clinical.models import ClinicalIndicator
        from clinical.rule_engine import _evaluate_reading

        tenant_id = 1
        indicator_map = {
            row.key: row
            for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
        }
        # پایه: warn=7.0, danger=8.0
        assert _evaluate_reading("hba1c", 6.9, indicator_map) == "ok"
        assert _evaluate_reading("hba1c", 7.1, indicator_map) == "warn"
        assert _evaluate_reading("hba1c", 8.1, indicator_map) == "danger"

    @pytest.mark.django_db
    def test_ordinary_patient_gets_base_thresholds(self, seed_clinical_data):
        """بیمارِ معمولی (age=50, بدونِ flag) → effective map = base."""
        from clinical.models import ClinicalIndicator

        tenant_id = 1
        indicator_map = {
            row.key: row
            for row in ClinicalIndicator.objects.filter(tenant_id=tenant_id, is_active=True)
        }
        pops = patient_populations({}, age=50)
        effective = apply_population_overrides(indicator_map, pops, tenant_id)
        # بدونِ approved override، identity باید حفظ شود
        assert effective is indicator_map


# ===========================================================================
# ۶) API tests — GET /manager/population-thresholds
# ===========================================================================

@pytest.fixture(scope="module")
def manager_user(seed_clinical_data):
    """Insert a manager user for this test module."""
    import bcrypt
    test_db_conninfo = (
        "host='localhost' port='55432' "
        "user='postgres' password='validate_only' "
        "dbname='halqe_app_test'"
    )
    pw_hash = bcrypt.hashpw(b"manager_pw", bcrypt.gensalt())
    with psycopg.connect(test_db_conninfo, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (1, 'manager_pop_test', %s, 'manager', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    is_active = TRUE,
                    failed_attempts = 0,
                    locked_until = NULL
        """, (pw_hash,))
    return {"username": "manager_pop_test", "password": "manager_pw"}


class TestPopulationThresholdAPI:

    @pytest.mark.django_db
    def test_manager_gets_200_with_drafts(self, seed_clinical_data, manager_user):
        """GET /manager/population-thresholds با manager → 200 + همهٔ دraftها."""
        token = _get_token(manager_user["username"], manager_user["password"])
        client = TestClient(api)
        resp = client.get(
            "/manager/population-thresholds",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "framing" in data
        assert data["framing"] == "پیش‌نویس — نیازمندِ تأییدِ پزشک"
        # seed: ۱۰ ردیف
        # 4 (frail/high) + 2 (hypo_high/high) + 2 (young_lowrisk/high) + 2 (frail/low)
        assert data["total"] == 10, (
            f"Expected 10 seed rows, got {data['total']}"
        )
        # همه باید draft باشند
        for item in data["items"]:
            assert item["approval_status"] == "draft", (
                f"Seed row {item['id']} should be 'draft', got {item['approval_status']}"
            )

    @pytest.mark.django_db
    def test_staff_gets_403(self, seed_clinical_data):
        """GET /manager/population-thresholds با staff → 403."""
        token = _get_token("testuser", "secret123")
        client = TestClient(api)
        resp = client.get(
            "/manager/population-thresholds",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"Expected 403 for staff user, got {resp.status_code}: {resp.json()}"
        )
        data = resp.json()
        assert data.get("code") == "forbidden"

    @pytest.mark.django_db
    def test_no_auth_gets_401(self, seed_clinical_data):
        """GET /manager/population-thresholds بدونِ JWT → 401."""
        client = TestClient(api)
        resp = client.get("/manager/population-thresholds")
        assert resp.status_code == 401, (
            f"Expected 401 without auth, got {resp.status_code}"
        )

    @pytest.mark.django_db
    def test_response_fields_complete(self, seed_clinical_data, manager_user):
        """همهٔ فیلدهای لازم در response سریال می‌شوند."""
        token = _get_token(manager_user["username"], manager_user["password"])
        client = TestClient(api)
        resp = client.get(
            "/manager/population-thresholds",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) > 0

        required_fields = {
            "id", "tenant_id", "indicator_key", "population_key",
            "bound", "approval_status", "created_at",
        }
        for item in items:
            missing = required_fields - set(item.keys())
            assert not missing, f"Missing fields in response item: {missing}"


# ===========================================================================
# ۷) نگهبانِ schema — جدول + RLS + GRANT + seed count + idempotency
# ===========================================================================

@pytest.fixture(scope="module")
def pg_conn(django_db_setup):
    """اتصالِ مستقیمِ Postgres برای تستِ نگهبان."""
    with psycopg.connect(_CONNINFO) as conn:
        yield conn


class TestSchemaGuardSlice9:
    """نگهبانِ schemaِ برشِ ۹ — اجرا فقط روی Docker PG."""

    def test_table_exists(self, pg_conn):
        """جدولِ clinical.population_thresholds وجود دارد."""
        row = pg_conn.execute("""
            SELECT COUNT(*) FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'clinical' AND c.relname = 'population_thresholds'
        """).fetchone()
        assert row[0] == 1, "clinical.population_thresholds table missing"

    def test_rls_enabled_and_forced(self, pg_conn):
        """RLS فعال است با FORCE."""
        row = pg_conn.execute("""
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'clinical' AND c.relname = 'population_thresholds'
        """).fetchone()
        assert row is not None, "Table not found in pg_class"
        assert row[0] is True, "relrowsecurity (ENABLE RLS) should be TRUE"
        assert row[1] is True, "relforcerowsecurity (FORCE RLS) should be TRUE"

    def test_tenant_isolation_policy_exists(self, pg_conn):
        """policy tenant_isolation روی جدول وجود دارد."""
        row = pg_conn.execute("""
            SELECT COUNT(*) FROM pg_catalog.pg_policy p
            JOIN pg_catalog.pg_class c ON c.oid = p.polrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'clinical'
              AND c.relname = 'population_thresholds'
              AND p.polname = 'tenant_isolation'
        """).fetchone()
        assert row[0] == 1, "tenant_isolation policy missing on population_thresholds"

    def test_grant_clinical_app(self, pg_conn):
        """clinical_app GRANT روی جدول دارد."""
        row = pg_conn.execute("""
            SELECT has_table_privilege('clinical_app',
                'clinical.population_thresholds', 'SELECT')
        """).fetchone()
        assert row[0] is True, "clinical_app should have SELECT on population_thresholds"

    def test_grant_platform_app(self, pg_conn):
        """platform_app GRANT روی جدول دارد."""
        row = pg_conn.execute("""
            SELECT has_table_privilege('platform_app',
                'clinical.population_thresholds', 'SELECT')
        """).fetchone()
        assert row[0] is True, "platform_app should have SELECT on population_thresholds"

    def test_seed_count_10_draft_rows(self, pg_conn):
        """۱۰ ردیفِ seed با approval_status='draft' وجود دارد.
        4 (frail/high) + 2 (hypo_high/high) + 2 (young_lowrisk/high) + 2 (frail/low)
        """
        row = pg_conn.execute("""
            SELECT COUNT(*) FROM clinical.population_thresholds
            WHERE approval_status = 'draft'
        """).fetchone()
        assert row[0] == 10, (
            f"Expected 10 draft seed rows, got {row[0]}. "
            "Check the INSERT statements in slice9."
        )

    def test_no_approved_in_seed(self, pg_conn):
        """هیچ ردیفِ approved در seed وجود ندارد."""
        row = pg_conn.execute("""
            SELECT COUNT(*) FROM clinical.population_thresholds
            WHERE approval_status = 'approved'
        """).fetchone()
        assert row[0] == 0, (
            f"Seed should contain NO 'approved' rows, found {row[0]}. "
            "Physician approval must never be fabricated."
        )

    def test_idempotency(self, pg_conn):
        """
        اجرای مجددِ slice9 بدونِ خطا (ON CONFLICT DO NOTHING).
        آمارِ ردیف‌ها بعد از re-apply تغییر نمی‌کند.
        """
        import pathlib

        count_before = pg_conn.execute(
            "SELECT COUNT(*) FROM clinical.population_thresholds"
        ).fetchone()[0]

        # re-apply slice9
        slice_path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "db"
            / "schema"
            / "schema_pg_slice9_population_thresholds.sql"
        )
        sql = slice_path.read_text(encoding="utf-8")
        # باید بدونِ خطا اجرا شود
        pg_conn.execute(sql)

        count_after = pg_conn.execute(
            "SELECT COUNT(*) FROM clinical.population_thresholds"
        ).fetchone()[0]
        assert count_after == count_before, (
            f"Row count changed after re-applying slice9: {count_before} → {count_after}. "
            "Seed should be idempotent."
        )

    def test_unique_constraint_enforced(self, pg_conn):
        """UNIQUE(tenant_id, indicator_key, population_key, bound) enforced."""
        # تلاش برای insert تکراری باید fail شود
        import psycopg.errors
        with pytest.raises(psycopg.errors.UniqueViolation):
            pg_conn.execute("""
                INSERT INTO clinical.population_thresholds
                    (tenant_id, indicator_key, population_key, bound, approval_status)
                VALUES (1, 'hba1c', 'frail', 'high', 'draft')
            """)
        pg_conn.rollback()

    def test_check_constraint_bound(self, pg_conn):
        """CHECK (bound IN ('high','low')) enforced."""
        import psycopg.errors
        with pytest.raises(psycopg.errors.CheckViolation):
            pg_conn.execute("""
                INSERT INTO clinical.population_thresholds
                    (tenant_id, indicator_key, population_key, bound, approval_status)
                VALUES (1, 'hba1c', 'test_pop', 'invalid_bound', 'draft')
            """)
        pg_conn.rollback()

    def test_check_constraint_approval_status(self, pg_conn):
        """CHECK (approval_status IN ('draft','approved')) enforced."""
        import psycopg.errors
        with pytest.raises(psycopg.errors.CheckViolation):
            pg_conn.execute("""
                INSERT INTO clinical.population_thresholds
                    (tenant_id, indicator_key, population_key, bound, approval_status)
                VALUES (1, 'hba1c', 'test_pop', 'high', 'pending')
            """)
        pg_conn.rollback()
