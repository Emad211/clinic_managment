"""
DB-level boundary tests — proving the read-only accounting boundary is enforced
by Postgres itself (NOT just by the ORM router), using the least-privilege app
role (platform_login_test / platform_app).

These tests open a DIRECT psycopg connection using the same credentials that
Django's 'default' and 'accounting_read' aliases use (PG_APP_USER/PG_APP_PASSWORD).
This is the only reliable way to test Postgres-level permission denial — Django's
transaction=True mode disables SAVEPOINTs, making it impossible to catch and
recover from permission errors inside the Django connection without tearing the
connection down.

Why direct psycopg is correct here:
  - The test credentials (PG_APP_USER/PG_APP_PASSWORD) are IDENTICAL to Django's
    connection credentials (set in conftest.django_db_setup + settings.py).
  - We are testing Postgres's GRANT enforcement, not Django's ORM.
  - The Django ORM layer is tested separately in test_orm_router_blocks_accounting_write.

Coverage:
  1. Raw INSERT into accounting.patients via app role connection → REFUSED
     (permission denied for table patients — InsufficientPrivilege / 42501)
  2. Raw UPDATE on accounting.patients via app role connection  → REFUSED
  3. Raw DELETE on accounting.patients via app role connection  → REFUSED
  4. Raw INSERT into accounting.patients via accounting_read alias credentials → REFUSED
  5. Raw SELECT from accounting.patients via accounting_read credentials → SUCCEEDS
     (the read boundary IS allowed)
  6. Raw SELECT from accounting.patients via default credentials → SUCCEEDS
  7. Raw INSERT into clinical.followup_tasks via default credentials → SUCCEEDS
     (the app can do its own clinical writes)
  8. Raw INSERT into platform.users via default credentials → SUCCEEDS
     (the app auth service needs to write platform.*)
  9. ORM router: Patient.objects.create() → raises PermissionError
     (the ORM layer also blocks — belt-and-suspenders)
"""
import os
import pytest
import psycopg

# ---------------------------------------------------------------------------
# Build app-role conninfo from env vars (same as Django settings uses)
# ---------------------------------------------------------------------------
_PG_HOST     = os.environ.get("PG_HOST", "localhost")
_PG_PORT     = os.environ.get("PG_PORT", "55432")
_PG_DB       = os.environ.get("PG_TEST_DB", "halqe_app_test")
_APP_USER    = os.environ.get("PG_APP_USER", "platform_login_test")
_APP_PW      = os.environ.get("PG_APP_PASSWORD", "test_pw")


def _app_conn(tenant_id: int = 1):
    """
    Open a psycopg connection as the least-privilege app role.

    RLS note (slice5): after enabling RLS on clinical.* and platform.*,
    INSERT/UPDATE/DELETE require app.current_tenant GUC to be set; otherwise
    the NULLIF fail-closed policy rejects all writes.  These boundary tests
    verify GRANT (can the role write at all?), not isolation — so we simulate
    JWTBearer by setting GUC=tenant_id here.  Isolation is tested separately
    in test_pg_schema.py::test_rls_isolation_*.
    """
    conninfo = (
        f"host='{_PG_HOST}' port='{_PG_PORT}' "
        f"user='{_APP_USER}' password='{_APP_PW}' dbname='{_PG_DB}'"
    )
    conn = psycopg.connect(conninfo, autocommit=True)
    conn.execute("SELECT set_config('app.current_tenant', %s, false)", [str(tenant_id)])
    return conn


def _try_sql(conn, sql, params=None):
    """
    Execute SQL; return (success: bool, error_msg: str | None).
    Uses a SAVEPOINT inside a non-autocommit sub-connection or catches the
    psycopg error directly.  With autocommit=True there's no wrapping
    transaction, so errors don't abort the connection.
    """
    try:
        conn.execute(sql, params or [])
        return True, None
    except psycopg.errors.InsufficientPrivilege as exc:
        return False, str(exc)
    except Exception as exc:
        # Catch other DB errors that might surface depending on PG version
        if "permission denied" in str(exc).lower() or "42501" in str(exc):
            return False, str(exc)
        # Re-raise unexpected errors
        raise


# ---------------------------------------------------------------------------
# Fixtures: ensure the app-role connection can be established
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_conn(django_db_setup):
    """A psycopg connection as the least-privilege app role (autocommit)."""
    conn = _app_conn()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# 1-3. Writes to accounting.* MUST be refused (via app role)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_insert_accounting_is_refused(seed_data):
    """
    Raw INSERT into accounting.patients by the app role → refused by Postgres.
    platform_app holds SELECT-only on accounting.* (no INSERT/UPDATE/DELETE).
    """
    with _app_conn() as conn:
        ok, err = _try_sql(
            conn,
            """
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id)
            VALUES (1, gen_random_uuid(), 'تست', 'مرز', '0000000000')
            """,
        )

    assert not ok, (
        "Expected INSERT into accounting.patients to FAIL with permission denied, "
        "but it SUCCEEDED — the app role has unexpected WRITE access to accounting!"
    )
    assert err is not None and (
        "permission denied" in err.lower() or "42501" in err
    ), f"Expected InsufficientPrivilege, got: {err}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_update_accounting_is_refused(seed_data):
    """
    Raw UPDATE on accounting.patients by the app role → refused.
    """
    patient_id = seed_data["patient_id"]
    with _app_conn() as conn:
        ok, err = _try_sql(
            conn,
            "UPDATE accounting.patients SET address = 'تهران' WHERE id = %s",
            [patient_id],
        )

    assert not ok, (
        "Expected UPDATE on accounting.patients to FAIL, but it SUCCEEDED!"
    )
    assert err is not None and (
        "permission denied" in err.lower() or "42501" in err
    ), f"Expected InsufficientPrivilege, got: {err}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_delete_accounting_is_refused(seed_data):
    """
    Raw DELETE on accounting.patients by the app role → refused.
    """
    with _app_conn() as conn:
        ok, err = _try_sql(
            conn,
            "DELETE FROM accounting.patients WHERE national_id = '0000000000_ghost'",
        )

    assert not ok, (
        "Expected DELETE on accounting.patients to FAIL, but it SUCCEEDED!"
    )
    assert err is not None and (
        "permission denied" in err.lower() or "42501" in err
    ), f"Expected InsufficientPrivilege, got: {err}"


# ---------------------------------------------------------------------------
# 4. accounting_read alias also uses the same app role → same restriction
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_insert_via_accounting_read_credentials_is_refused(seed_data):
    """
    INSERT into accounting.patients via accounting_read credentials → refused.
    Both Django aliases use the same least-privilege app role.
    """
    with _app_conn() as conn:  # accounting_read uses same PG_APP_USER
        ok, err = _try_sql(
            conn,
            """
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id)
            VALUES (1, gen_random_uuid(), 'تست۲', 'مرز', '1111111111')
            """,
        )

    assert not ok, (
        "Expected INSERT via accounting_read to FAIL, but it SUCCEEDED!"
    )
    assert err is not None and (
        "permission denied" in err.lower() or "42501" in err
    ), f"Expected InsufficientPrivilege, got: {err}"


# ---------------------------------------------------------------------------
# 5-6. Reads from accounting.* MUST succeed (SELECT boundary is allowed)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_select_accounting_succeeds(seed_data):
    """
    Raw SELECT from accounting.patients by the app role → succeeds.
    The read boundary is allowed; only writes are blocked.
    """
    patient_uuid = str(seed_data["patient_uuid"])
    with _app_conn() as conn:
        row = conn.execute(
            "SELECT id, name, family_name FROM accounting.patients WHERE uuid = %s",
            [patient_uuid],
        ).fetchone()

    assert row is not None, "Expected to read the seeded patient, got None"
    assert row[1] == "علی"
    assert row[2] == "رضایی"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_select_accounting_from_default_also_succeeds(seed_data):
    """
    SELECT from accounting.patients using default alias credentials → succeeds.
    platform_app has SELECT on all accounting.* tables.
    """
    from django.db import connections
    patient_uuid = str(seed_data["patient_uuid"])
    with connections["default"].cursor() as cur:
        cur.execute(
            "SELECT id FROM accounting.patients WHERE uuid = %s",
            [patient_uuid],
        )
        row = cur.fetchone()

    assert row is not None, (
        "Expected to SELECT from accounting.patients via default connection"
    )


# ---------------------------------------------------------------------------
# 7-8. Writes to clinical.* and platform.* MUST succeed
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_insert_clinical_followup_succeeds(seed_data):
    """
    Raw INSERT into clinical.followup_tasks by the app role → succeeds.
    platform_app has full WRITE on clinical.*.
    """
    link_id = seed_data["link_id"]
    with _app_conn() as conn:
        ok, err = _try_sql(
            conn,
            """
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason, status, fulfillment)
            VALUES (1, %s, CURRENT_DATE + 7, 'boundary_test', 'open', 'in_person')
            """,
            [link_id],
        )

    assert ok, (
        f"Expected INSERT into clinical.followup_tasks to SUCCEED, but got: {err}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_insert_platform_users_succeeds(seed_data):
    """
    Raw INSERT into platform.users by the app role → succeeds.
    platform_app has full WRITE on platform.*.
    """
    with _app_conn() as conn:
        ok, err = _try_sql(
            conn,
            """
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (1, 'boundary_test_user_delete_me',
                    '\\x6861736864756d6d79'::bytea,
                    'staff', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO NOTHING
            """,
        )

    assert ok, (
        f"Expected INSERT into platform.users to SUCCEED, but got: {err}"
    )


# ---------------------------------------------------------------------------
# 9. ORM router layer also blocks (belt-and-suspenders)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_orm_router_blocks_accounting_write(seed_data):
    """
    Patient.objects.create() via the ORM raises PermissionError from
    ClinicalRouter.db_for_write().  Belt-and-suspenders on top of tests 1-4.
    """
    from accounting.models import Patient
    import uuid

    with pytest.raises(PermissionError, match="read-only"):
        Patient.objects.create(
            tenant_id=1,
            uuid=uuid.uuid4(),
            name="تست",
            family_name="مرز",
            national_id="9999999999",
            gender="male",
        )
