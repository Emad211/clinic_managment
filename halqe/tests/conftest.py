"""
pytest-django conftest for halqe vertical slice tests.

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
