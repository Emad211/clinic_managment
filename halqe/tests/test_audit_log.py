"""
Audit-log tests — clinical.activity_logs (append-only).

Coverage:
  1. POST /auth/login success → row with action_type='login', action_category='auth',
     correct user_id, tenant_id set from JWT.
  2. POST /worklist/{task_id}/done → row action_type='followup_done',
     target_table='followup_tasks', target_id=task_id, patient_link_id correct.
  3. POST /patients/{uuid}/suggestions/{rule_code}/action (accept) →
     row action_type='suggestion_accepted', description contains rule_code,
     patient_link_id correct.
  4. POST /patients/{uuid}/suggestions/{rule_code}/action (dismiss) →
     row action_type='suggestion_dismissed'.
  5. Rows are tenant-scoped (tenant_id from the JWT claims).
  6. Append-only: direct UPDATE on clinical.activity_logs as platform_login_test
     raises psycopg.errors.InsufficientPrivilege.

All write tests use seed_act_data (which extends seed_clinical_data → seed_data).
The DB check is done via psycopg (superuser) to query clinical.activity_logs directly
without going through the ORM — confirms the row is really persisted.
"""
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api

# ── DB connection ─────────────────────────────────────────────────────────────

_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

_CONNINFO_PLATFORM_APP = (
    "host='localhost' port='55432' "
    "user='platform_login_test' password='test_pw' "
    "dbname='halqe_app_test'"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed):
    """Obtain JWT for testuser (tenant-1)."""
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


def _count_audit_rows(conn, action_type: str, tenant_id: int = 1) -> int:
    row = conn.execute(
        "SELECT count(*) FROM clinical.activity_logs "
        "WHERE action_type=%s AND tenant_id=%s",
        (action_type, tenant_id),
    ).fetchone()
    return row[0] if row else 0


# ── Test 1 — login success → audit row ────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_login_success_writes_audit_row(seed_act_data):
    """
    POST /auth/login success → clinical.activity_logs row:
      action_type='login', action_category='auth', tenant_id=1, user_id set.
    """
    # Count rows before this test's login so we're robust to prior test runs
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        before = _count_audit_rows(conn, "login")

    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed_act_data["test_password"]},
    )
    assert resp.status_code == 200, resp.text

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        after = _count_audit_rows(conn, "login")
        assert after > before, (
            "Expected at least one new 'login' row in clinical.activity_logs after successful login"
        )

        # Fetch the most recent login row for testuser
        row = conn.execute(
            "SELECT tenant_id, user_id, username, action_type, action_category "
            "FROM clinical.activity_logs "
            "WHERE action_type='login' AND tenant_id=1 "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    assert row is not None, "No audit row found for login"
    tenant_id, user_id, username, action_type, action_category = row
    assert tenant_id == 1
    assert action_type == "login"
    assert action_category == "auth"
    assert username == "testuser"
    # user_id must be populated (not NULL) — resolved from JWT claims
    assert user_id == seed_act_data["user_id"], (
        f"Expected user_id={seed_act_data['user_id']}, got {user_id}"
    )


# ── Test 2 — mark_task_done → audit row ───────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_mark_done_writes_audit_row(seed_act_data):
    """
    POST /worklist/{task_id}/done → clinical.activity_logs row:
      action_type='followup_done', action_category='clinical',
      target_table='followup_tasks', target_id=task_id, patient_link_id correct.
    """
    token = _get_token(seed_act_data)

    # Create a fresh task so this test is self-contained
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        row = conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason,
                 status, fulfillment, created_at)
            VALUES (1, %s, CURRENT_DATE - 1, 'audit_test', 'open', 'in_person', now())
            RETURNING id
        """, (seed_act_data["link_id"],)).fetchone()
        audit_task_id = row[0]

    resp = _client().post(
        f"/worklist/{audit_task_id}/done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    # Check audit row
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        row = conn.execute(
            "SELECT tenant_id, user_id, username, action_type, action_category, "
            "       target_table, target_id, patient_link_id "
            "FROM clinical.activity_logs "
            "WHERE action_type='followup_done' AND target_id=%s AND tenant_id=1 "
            "ORDER BY created_at DESC LIMIT 1",
            (audit_task_id,)
        ).fetchone()

    assert row is not None, (
        f"No audit row found for followup_done (task_id={audit_task_id})"
    )
    t_id, user_id, username, action_type, action_category, target_table, target_id, plid = row

    assert t_id == 1
    assert action_type == "followup_done"
    assert action_category == "clinical"
    assert target_table == "followup_tasks"
    assert target_id == audit_task_id
    assert plid == seed_act_data["link_id"], (
        f"Expected patient_link_id={seed_act_data['link_id']}, got {plid}"
    )
    assert user_id == seed_act_data["user_id"]
    assert username == "testuser"


# ── Test 3 — suggestion accept → audit row ────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_accept_writes_audit_row(seed_act_data):
    """
    POST /patients/{uuid}/suggestions/{rule_code}/action (accept) →
    action_type='suggestion_accepted', description contains rule_code,
    patient_link_id correct.
    """
    token = _get_token(seed_act_data)
    patient_uuid = seed_act_data["patient_uuid"]
    rule_code = "AUDIT-TEST-ACCEPT-01"

    resp = _client().post(
        f"/patients/{patient_uuid}/suggestions/{rule_code}/action",
        json={"action": "accept", "note": "تأیید شد"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200: {resp.text}"

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        row = conn.execute(
            "SELECT tenant_id, user_id, username, action_type, action_category, "
            "       description, patient_link_id "
            "FROM clinical.activity_logs "
            "WHERE action_type='suggestion_accepted' AND tenant_id=1 "
            "  AND description LIKE %s "
            "ORDER BY created_at DESC LIMIT 1",
            (f"%{rule_code}%",)
        ).fetchone()

    assert row is not None, (
        f"No audit row found for suggestion_accepted with rule_code={rule_code}"
    )
    t_id, user_id, username, action_type, action_category, description, plid = row

    assert action_type == "suggestion_accepted"
    assert action_category == "clinical"
    assert rule_code in description, (
        f"rule_code '{rule_code}' must be in description, got: '{description}'"
    )
    assert plid == seed_act_data["link_id"]
    assert user_id == seed_act_data["user_id"]
    assert t_id == 1


# ── Test 4 — suggestion dismiss → audit row ───────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_dismiss_writes_audit_row(seed_act_data):
    """
    POST .../action (dismiss) → action_type='suggestion_dismissed'.
    """
    token = _get_token(seed_act_data)
    patient_uuid = seed_act_data["patient_uuid"]
    rule_code = "AUDIT-TEST-DISMISS-01"

    resp = _client().post(
        f"/patients/{patient_uuid}/suggestions/{rule_code}/action",
        json={"action": "dismiss"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200: {resp.text}"

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        row = conn.execute(
            "SELECT action_type, description, patient_link_id "
            "FROM clinical.activity_logs "
            "WHERE action_type='suggestion_dismissed' AND tenant_id=1 "
            "  AND description LIKE %s "
            "ORDER BY created_at DESC LIMIT 1",
            (f"%{rule_code}%",)
        ).fetchone()

    assert row is not None, (
        f"No audit row found for suggestion_dismissed with rule_code={rule_code}"
    )
    action_type, description, plid = row
    assert action_type == "suggestion_dismissed"
    assert rule_code in description
    assert plid == seed_act_data["link_id"]


# ── Test 5 — tenant_id is scoped from the JWT ─────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_audit_rows_are_tenant_scoped(seed_act_data):
    """
    Audit rows carry tenant_id from the authenticated user's JWT (tenant=1).
    tenant_id=2 rows must NOT appear for tenant-1 logins.
    """
    token = _get_token(seed_act_data)

    # Perform a login (creates an audit row with tenant_id from JWT)
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed_act_data["test_password"]},
    )
    assert resp.status_code == 200, resp.text

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        # The most recent login row must have tenant_id=1
        row = conn.execute(
            "SELECT tenant_id FROM clinical.activity_logs "
            "WHERE action_type='login' AND username='testuser' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    assert row is not None
    assert row[0] == 1, f"Expected tenant_id=1, got {row[0]}"


# ── Test 6 — append-only: UPDATE/DELETE raises permission error ───────────────

def test_activity_logs_append_only_update_raises(seed_act_data):
    """
    As platform_login_test (role: platform_app), UPDATE on clinical.activity_logs
    must raise psycopg.errors.InsufficientPrivilege.

    The DB-level REVOKE UPDATE, DELETE ON clinical.activity_logs
    FROM platform_app (and clinical_app) is applied in schema_pg_slice2_clinical.sql.
    """
    # First ensure there is at least one row in activity_logs (from other tests
    # running in the same session, or we create one via superuser).
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        conn.execute("""
            INSERT INTO clinical.activity_logs
                (tenant_id, user_id, username, action_type, action_category)
            VALUES (1, NULL, 'append_only_test', 'login', 'auth')
        """)

    with psycopg.connect(_CONNINFO_PLATFORM_APP) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute(
                    "UPDATE clinical.activity_logs "
                    "SET action_type='tampered' WHERE action_type='login'"
                )


def test_activity_logs_append_only_delete_raises(seed_act_data):
    """
    DELETE on clinical.activity_logs as platform_login_test → InsufficientPrivilege.
    """
    with psycopg.connect(_CONNINFO_PLATFORM_APP) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute(
                    "DELETE FROM clinical.activity_logs WHERE action_type='login'"
                )
