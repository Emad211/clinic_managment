"""
pytest-django conftest for halqe vertical slice tests.

Session-scoped fixtures available to ALL test files:
  - django_db_setup   : create test DB, apply slices, create login role
  - seed_data         : one patient + link + vitals + testuser
  - seed_clinical_data: extends seed_data with conditions, meds, tenant-2 patient
  - seed_act_data     : extends seed_clinical_data with followup_tasks for worklist/audit tests

Strategy:
  - Use a throwaway Postgres DB 'halqe_app_test' on the Docker container.
  - Session-scoped fixture: create the DB (superuser), run apply_schema (all slices,
    superuser), seed data (superuser for accounting writes which the app role cannot do).
  - Django DATABASES 'default' and 'accounting_read' are pointed at the LEAST-PRIVILEGE
    app role (platform_login_test, member of platform_app) — NOT postgres superuser.
    This means the Django ORM/connection boundary is real: accounting writes are refused
    at the DB level, not just by the ORM router.
  - Tests run inside transactions (django_db) and see the seeded data via
    the session fixture which seeds BEFORE the transaction wraps.

Connection roles:
  - Superuser (PG_USER/PG_PASSWORD): DDL, GRANT, DROP/CREATE DB, seed accounting data.
  - App role  (PG_APP_USER/PG_APP_PASSWORD): all Django ORM operations + boundary tests.
    Platform_login_test is a LOGIN role member of platform_app (inherits its GRANTs).

Note: we do NOT use Django's built-in test runner DB creation because:
  1. managed=False — Django wouldn't create our tables anyway.
  2. We need to run the SQL slices which include DO $$ blocks / GRANT / etc.
     that require superuser + autocommit.
"""
import os
import uuid
import psycopg
import bcrypt
import pytest

# ---------------------------------------------------------------------------
# Credentials — two separate identities
# ---------------------------------------------------------------------------
TEST_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")

# Superuser — for DDL/seed/DROP/CREATE only
PG_SU_USER     = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")

# App role — for Django ORM connections (least-privilege)
PG_APP_USER     = os.environ.get("PG_APP_USER", "platform_login_test")
PG_APP_PASSWORD = os.environ.get("PG_APP_PASSWORD", "test_pw")

SCHEMA_SLICE_DIR = os.environ.get(
    "SCHEMA_SLICE_DIR",
    str(
        (
            __import__("pathlib").Path(__file__).resolve().parent.parent.parent
            / "specialist_clinic"
            / "docs"
            / "migration_tools"
        )
    ),
)


@pytest.fixture(scope="session")
def django_db_setup(django_test_environment, django_db_blocker):
    """
    Session-scoped: create halqe_app_test, apply all slices, create app role.

    Django DATABASES 'default' and 'accounting_read' are pointed at:
      - Test DB name (halqe_app_test)
      - The LEAST-PRIVILEGE app role (platform_login_test / platform_app)
        NOT the postgres superuser.

    The superuser psycopg connection is used ONLY for DDL/GRANT/seed steps
    (which legitimately need elevated privileges).
    """
    from django.conf import settings

    # Override DATABASES: test DB name + least-privilege app role credentials
    for alias in ("default", "accounting_read"):
        settings.DATABASES[alias]["NAME"] = TEST_DB_NAME
        settings.DATABASES[alias]["USER"] = PG_APP_USER
        settings.DATABASES[alias]["PASSWORD"] = PG_APP_PASSWORD

    # ── Superuser: create test DB (drop + recreate for clean state) ──────────
    superuser_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='postgres'"
    )
    with psycopg.connect(superuser_conninfo, autocommit=True) as conn:
        conn.execute(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")
        conn.execute(f"CREATE DATABASE {TEST_DB_NAME}")

    # ── Superuser: apply all schema slices ────────────────────────────────────
    su_test_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'"
    )
    from pathlib import Path
    slice_dir = Path(SCHEMA_SLICE_DIR)
    slice_files = sorted(slice_dir.glob("schema_pg_slice*.sql"))
    assert slice_files, f"No slice files found in {slice_dir}"

    with psycopg.connect(su_test_conninfo, autocommit=True) as conn:
        for sf in slice_files:
            conn.execute(sf.read_text(encoding="utf-8"))

        # ── Create the least-privilege app LOGIN role (cluster-level) ─────────
        # رفعِ شکنندگی: رمز را هر بار با ALTER ROLE بازنشانی کن — رول کلاستر-level است
        # و ممکن است از اجرایِ قبلی با رمزِ متفاوت موجود باشد.
        conn.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PG_APP_USER}') THEN
                    CREATE ROLE {PG_APP_USER} LOGIN PASSWORD '{PG_APP_PASSWORD}'
                        IN ROLE platform_app;
                END IF;
            END$$;
        """)
        conn.execute(f"ALTER ROLE {PG_APP_USER} PASSWORD '{PG_APP_PASSWORD}'")
        conn.execute(f"GRANT platform_app TO {PG_APP_USER}")

        # Grant the login role CONNECT on the test DB (object-level, not cluster-level)
        conn.execute(
            f"GRANT CONNECT ON DATABASE {TEST_DB_NAME} TO {PG_APP_USER}"
        )

    # Allow Django to use the DB (blocker context)
    with django_db_blocker.unblock():
        yield

    # ── Superuser: teardown — drop test DB ───────────────────────────────────
    with psycopg.connect(superuser_conninfo, autocommit=True) as conn:
        conn.execute(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")


# ---------------------------------------------------------------------------
# Seed fixture — inserts ONE patient, link, and vitals as superuser.
# Superuser is required for accounting.patients writes — the app role cannot.
# (outside any transaction wrapping so all tests see it)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def seed_data(django_db_setup):
    """
    Insert seed data into halqe_app_test as postgres SUPERUSER (not the app role).
    accounting.patients is in the accounting schema; the app role (platform_app) can
    only SELECT it — superuser is used here because seeding demo data is an out-of-band
    dev action, not an app write path.
    Returns a dict with the UUIDs/IDs tests need.
    """
    test_db_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'"
    )
    patient_uuid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    with psycopg.connect(test_db_conninfo, autocommit=True) as conn:
        # Insert accounting patient (superuser can do this; clinical_app cannot write)
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (1, %s, 'علی', 'رضایی', '1234567890', '09120000001',
                    '1990-05-15', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (patient_uuid,))

        # Get the patient id
        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid = %s",
            (patient_uuid,)
        ).fetchone()
        patient_id = row[0]

        # Insert clinical patient_link
        conn.execute("""
            INSERT INTO clinical.patient_links
                (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (patient_id,))

        link_row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE patient_id = %s",
            (patient_id,)
        ).fetchone()
        link_id = link_row[0]

        # Insert vital readings
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (1, %s, 'hba1c',       7.2, '%%',    now() - interval '1 day',  'clinic'),
                (1, %s, 'bp_systolic', 128, 'mmHg',  now() - interval '2 days', 'clinic'),
                (1, %s, 'hba1c',       7.5, '%%',    now() - interval '30 days','clinic')
        """, (link_id, link_id, link_id))

        # Seed a test user in platform.users for auth tests.
        # Known password 'secret123' — bcrypt hash computed here so tests can verify.
        test_password = "secret123"
        pw_hash = bcrypt.hashpw(test_password.encode(), bcrypt.gensalt())
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active,
                 failed_attempts)
            VALUES (1, 'testuser', %s, 'staff', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    is_active = TRUE,
                    failed_attempts = 0,
                    locked_until = NULL
        """, (pw_hash,))

        user_row = conn.execute(
            "SELECT id FROM platform.users WHERE tenant_id=1 AND username='testuser'"
        ).fetchone()
        user_id = user_row[0]

    return {
        "patient_uuid": patient_uuid,
        "patient_id": patient_id,
        "link_id": link_id,
        "user_id": user_id,
        "test_password": test_password,
    }


@pytest.fixture(scope="session")
def seed_clinical_data(seed_data):
    """
    Extend the base seed with:
      - A second patient in a DIFFERENT tenant (tenant 2) — for isolation tests.
      - Conditions (diabetes + hypertension) linked to tenant-1 patient.
      - patient_conditions entries (active diabetes, active hypertension).
      - patient_medications: 2 active + 1 inactive.
      - Additional vital_readings: 4 more rows (2 types × 2 timestamps).

    Returns the extended seed dict.
    """
    test_db_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' "
        f"dbname='{TEST_DB_NAME}'"
    )
    tenant2_patient_uuid = uuid.UUID("11111111-2222-3333-4444-555555555555")

    with psycopg.connect(test_db_conninfo, autocommit=True) as conn:
        # ── Tenant 2: insert a second tenant ─────────────────────────────────
        # platform.tenants real columns: id, name, is_active, created_at (no subdomain)
        conn.execute("""
            INSERT INTO platform.tenants (id, name, is_active)
            VALUES (2, 'درمانگاه تست ۲', TRUE)
            ON CONFLICT (id) DO NOTHING
        """)

        # ── Patient in tenant 2 ───────────────────────────────────────────────
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number,
                 birthdate, gender)
            VALUES (2, %s, 'سارا', 'محمدی', '9876543210', '09130000002',
                    '1985-03-20', 'female')
            ON CONFLICT (uuid) DO NOTHING
        """, (tenant2_patient_uuid,))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s",
            (tenant2_patient_uuid,)
        ).fetchone()
        tenant2_patient_id = row[0]

        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (2, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (tenant2_patient_id,))

        # ── Conditions (diabetes id=1, hypertension id=2 from slice2 seed) ───
        # We rely on the seeded rows in clinical.conditions from schema slice2.
        # Fetch them to get real IDs.
        diabetes_row = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=1 AND code='diabetes'"
        ).fetchone()
        htn_row = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=1 AND code='hypertension'"
        ).fetchone()

        diabetes_id = diabetes_row[0] if diabetes_row else None
        htn_id = htn_row[0] if htn_row else None

        link_id = seed_data["link_id"]

        # ── patient_conditions ────────────────────────────────────────────────
        pc_ids = {}
        if diabetes_id:
            conn.execute("""
                INSERT INTO clinical.patient_conditions
                    (tenant_id, patient_link_id, condition_id, stage,
                     onset_date, notes, is_active, diagnosed_at)
                VALUES (1, %s, %s, 'T2DM', '2020-01-15',
                        'تشخیص اولیه دیابت نوع ۲', TRUE, now())
                ON CONFLICT DO NOTHING
                RETURNING id
            """, (link_id, diabetes_id))
            row = conn.execute(
                "SELECT id FROM clinical.patient_conditions "
                "WHERE patient_link_id=%s AND condition_id=%s AND tenant_id=1",
                (link_id, diabetes_id)
            ).fetchone()
            pc_ids["diabetes"] = row[0] if row else None

        if htn_id:
            conn.execute("""
                INSERT INTO clinical.patient_conditions
                    (tenant_id, patient_link_id, condition_id, stage,
                     onset_date, notes, is_active, diagnosed_at)
                VALUES (1, %s, %s, 'stage1', '2021-06-10',
                        'فشار خون مرحله ۱', TRUE, now())
                ON CONFLICT DO NOTHING
            """, (link_id, htn_id))
            row = conn.execute(
                "SELECT id FROM clinical.patient_conditions "
                "WHERE patient_link_id=%s AND condition_id=%s AND tenant_id=1",
                (link_id, htn_id)
            ).fetchone()
            pc_ids["hypertension"] = row[0] if row else None

        # ── patient_medications: 2 active + 1 inactive ────────────────────────
        conn.execute("""
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, dose, schedule,
                 start_date, drug_class, is_active, created_at)
            VALUES
                (1, %s, 'متفورمین', '500mg', 'روزی دو بار',
                 '2020-02-01', 'metformin', TRUE, now()),
                (1, %s, 'آملودیپین', '5mg', 'روزی یک بار',
                 '2021-07-01', 'ccb', TRUE, now()),
                (1, %s, 'گلیبنکلامید', '5mg', 'صبح',
                 '2020-03-01', 'su', FALSE, now() - interval '30 days')
        """, (link_id, link_id, link_id))

        # Fetch medication ids
        med_rows = conn.execute(
            "SELECT id, drug_name, is_active FROM clinical.patient_medications "
            "WHERE patient_link_id=%s AND tenant_id=1",
            (link_id,)
        ).fetchall()

        # ── More vitals (hba1c + bp_systolic 2 more rows) ────────────────────
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (1, %s, 'hba1c',        6.9, '%%',   now() - interval '3 months', 'clinic'),
                (1, %s, 'bp_systolic',  132, 'mmHg', now() - interval '7 days',  'clinic'),
                (1, %s, 'weight',        82, 'kg',   now() - interval '5 days',  'clinic'),
                (1, %s, 'ldl',           95, 'mg/dL',now() - interval '4 days',  'clinic')
        """, (link_id, link_id, link_id, link_id))

    return {
        **seed_data,
        "tenant2_patient_uuid": tenant2_patient_uuid,
        "tenant2_patient_id": tenant2_patient_id,
        "diabetes_condition_id": diabetes_id,
        "htn_condition_id": htn_id,
        "pc_ids": pc_ids,
    }


# ---------------------------------------------------------------------------
# seed_act_data — extends seed_clinical_data with followup_tasks
# (previously in test_act_slice.py; moved here so audit tests can use it too)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def seed_act_data(seed_clinical_data):
    """
    Extend the existing clinical seed with followup_tasks for worklist + audit tests:
      - Task A: status='open', due_date=today-1 (past-due → visible by default)
      - Task B: status='done', due_date=today-5 (should NOT show in default listing)
      - Task C: status='open', due_date=today+30 (future → excluded by default filter)
      - Tenant-2 task (isolation test)
    Returns dict with task IDs and UUIDs.
    """
    test_db_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'"
    )

    with psycopg.connect(test_db_conninfo, autocommit=True) as conn:
        link_id = seed_clinical_data["link_id"]

        # Task A — open, past-due (should appear in default worklist listing)
        row = conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason, detail,
                 status, fulfillment, created_at)
            VALUES
                (1, %s, CURRENT_DATE - 1, 'uncontrolled',
                 'HbA1c بالاست — پیگیری لازم است',
                 'open', 'in_person', now())
            RETURNING id
        """, (link_id,)).fetchone()
        task_a_id = row[0]

        # Task B — already done
        row = conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason,
                 status, fulfillment, created_at, resolved_at)
            VALUES
                (1, %s, CURRENT_DATE - 5, 'refill',
                 'done', 'remote', now() - interval '5 days', now() - interval '3 days')
            RETURNING id
        """, (link_id,)).fetchone()
        task_b_id = row[0]

        # Task C — open but FUTURE (should not appear in default due-filter)
        row = conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason,
                 status, fulfillment, created_at)
            VALUES
                (1, %s, CURRENT_DATE + 30, 'visit_due',
                 'open', 'in_person', now())
            RETURNING id
        """, (link_id,)).fetchone()
        task_c_id = row[0]

        # ── Tenant-2 task (isolation) ─────────────────────────────────────────
        t2_patient_id = seed_clinical_data["tenant2_patient_id"]
        t2_link_row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=2 AND patient_id=%s",
            (t2_patient_id,)
        ).fetchone()
        assert t2_link_row, "Tenant-2 patient link must exist from seed_clinical_data"
        t2_link_id = t2_link_row[0]

        row = conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason,
                 status, fulfillment, created_at)
            VALUES
                (2, %s, CURRENT_DATE - 1, 'lapsed',
                 'open', 'in_person', now())
            RETURNING id
        """, (t2_link_id,)).fetchone()
        task_t2_id = row[0]

    return {
        **seed_clinical_data,
        "task_a_id": task_a_id,        # open, past-due, tenant-1
        "task_b_id": task_b_id,        # done, tenant-1
        "task_c_id": task_c_id,        # open, future, tenant-1
        "task_t2_id": task_t2_id,      # open, tenant-2 (isolation)
        "t2_link_id": t2_link_id,
    }


# ---------------------------------------------------------------------------
# RLS compatibility fixture — Slice 5 (قدم ۱۹)
#
# پس از فعال‌سازیِ RLS در slice5، هر کوئریِ ORM/psycopg که با app-role اجرا
# می‌شود نیاز دارد GUCِ app.current_tenant ست شده باشد. در production این کار
# توسطِ JWTBearer.authenticate() انجام می‌شود. برای تست‌هایی که مستقیماً
# service/ORM را فراخوانی می‌کنند (نه از طریقِ endpoint)، این fixture
# GUC را قبل از هر تست به tenant_id=1 (مستأجرِ پیش‌فرضِ تست) ست می‌کند
# و بعد از تست آن را به '' reset می‌کند (yield fixture).
#
# این fixture:
#   - autouse=True: همهٔ تست‌های django_db به‌صورتِ خودکار از آن بهره می‌برند.
#   - policy را تضعیف نمی‌کند: fail-closed با GUC='' در production کار می‌کند.
#     این fixture فقط برای تست‌هایی است که از endpoint نمی‌گذرند.
#   - شبیه‌سازیِ JWTBearer: همان الگوی set_tenant_guc(1) که در production
#     auth_bearer.py انجام می‌شود.
#   - yield: پس از تست GUC را به '' برمی‌گرداند — از تداخل بین تست‌ها جلوگیری می‌کند.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def set_default_tenant_guc(db, request):
    """
    برای همهٔ تست‌های django_db، GUCِ app.current_tenant را به '1' ست می‌کند
    و پس از تست آن را پاک می‌کند. این fixture از `db` استفاده می‌کند تا فقط
    وقتی DB connection واقعاً فعال است اجرا شود (نه برای unit testهای بدون DB).

    تست‌هایی که نیاز به GUCِ خاص دارند (مثلِ tenant_context و rls_isolation)
    می‌توانند GUC را بعداً override کنند — این fixture فقط default می‌زند.
    """
    from platform_core.tenant_context import set_tenant_guc, clear_tenant_guc

    set_tenant_guc(1)
    yield
    # reset بعد از تست: از آلودگیِ connection بین تست‌ها جلوگیری می‌کند
    try:
        clear_tenant_guc()
    except Exception:
        pass
