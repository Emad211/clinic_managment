"""
pytest-django conftest for halqe vertical slice tests.

Session-scoped fixtures available to ALL test files:
  - django_db_setup   : create test DB, apply slices, create login role
  - seed_data         : one patient + link + vitals + testuser
  - seed_clinical_data: extends seed_data with conditions, meds, tenant-2 patient
  - seed_act_data     : extends seed_clinical_data with followup_tasks for worklist/audit tests

Strategy:
  - Use a throwaway Postgres DB 'halqe_app_test' on the Docker container.
  - Session-scoped fixture: create the DB, run apply_schema (all slices),
    seed one patient + link + vital rows as superuser.
  - Django settings override points both 'default' and 'accounting_read' at
    the test DB.
  - Tests run inside transactions (django_db) and see the seeded data via
    the session fixture which seeds BEFORE the transaction wraps.

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
# Settings override — point Django at the test DB
# ---------------------------------------------------------------------------
TEST_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")

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
    Session-scoped: create halqe_app_test, apply all slices, seed data.
    Override Django DATABASES to point at the test DB.
    """
    from django.conf import settings

    # Override DATABASES for the test session
    for alias in ("default", "accounting_read"):
        settings.DATABASES[alias]["NAME"] = TEST_DB_NAME

    # Create test DB (drop + recreate for clean state)
    superuser_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_USER}' password='{PG_PASSWORD}' dbname='postgres'"
    )
    with psycopg.connect(superuser_conninfo, autocommit=True) as conn:
        conn.execute(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")
        conn.execute(f"CREATE DATABASE {TEST_DB_NAME}")

    # Apply all slices
    test_db_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_USER}' password='{PG_PASSWORD}' dbname='{TEST_DB_NAME}'"
    )
    from pathlib import Path
    slice_dir = Path(SCHEMA_SLICE_DIR)
    slice_files = sorted(slice_dir.glob("schema_pg_slice*.sql"))
    assert slice_files, f"No slice files found in {slice_dir}"

    with psycopg.connect(test_db_conninfo, autocommit=True) as conn:
        for sf in slice_files:
            conn.execute(sf.read_text(encoding="utf-8"))

        # Ensure the platform_login_test role exists and is a member of platform_app.
        # رفعِ شکنندگی: رمز را هر بار با ALTER ROLE بازنشانی کن — رول کلاستر-level است
        # و ممکن است از اجرایِ قبلی با رمزِ متفاوت موجود باشد.
        conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_login_test') THEN
                    CREATE ROLE platform_login_test LOGIN PASSWORD 'test_pw'
                        IN ROLE platform_app;
                END IF;
            END$$;
        """)
        conn.execute("ALTER ROLE platform_login_test PASSWORD 'test_pw'")
        conn.execute("GRANT platform_app TO platform_login_test")

        # Grant the login role privileges on test DB objects
        conn.execute(
            f"GRANT CONNECT ON DATABASE {TEST_DB_NAME} TO platform_login_test"
        )

    # Allow Django to use the DB (blocker context)
    with django_db_blocker.unblock():
        yield

    # Teardown: drop test DB
    with psycopg.connect(superuser_conninfo, autocommit=True) as conn:
        conn.execute(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")


# ---------------------------------------------------------------------------
# Seed fixture — inserts ONE patient, link, and vitals as superuser
# (outside any transaction wrapping so all tests see it)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def seed_data(django_db_setup):
    """
    Insert seed data into halqe_app_test as postgres superuser.
    Returns a dict with the UUIDs/IDs tests need.
    """
    test_db_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_USER}' password='{PG_PASSWORD}' dbname='{TEST_DB_NAME}'"
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
        f"host='localhost' port='55432' "
        f"user='postgres' password='validate_only' "
        f"dbname='halqe_app_test'"
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
        f"user='{PG_USER}' password='{PG_PASSWORD}' dbname='{TEST_DB_NAME}'"
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
