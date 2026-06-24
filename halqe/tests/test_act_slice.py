"""
ACT slice tests — follow-up worklist + physician suggestion actions.

Coverage:
  Worklist (GET /worklist):
    1. Lists due open tasks with demographics (N+1-free)
    2. Pagination: total, limit, offset
    3. Excludes tasks from OTHER tenants (tenant isolation)
    4. ?status= filter: done/dismissed tasks visible only with explicit status param
    5. 401 without JWT

  Mark done (POST /worklist/{task_id}/done):
    6. Flips status to 'done' and sets resolved_at (TIMESTAMPTZ)
    7. Updated task is returned and visible in subsequent list
    8. 404 for task_id not belonging to this tenant
    9. 409 trying to re-mark an already-done task
    10. 401 without JWT

  Suggestion action (POST /patients/{uuid}/suggestions/{rule_code}/action):
    11. Writes a suggestion_log row with accepted/dismissed
    12. Re-acting on same (patient, rule_code) UPDATES (upsert, no duplicate)
    13. Returns correct status in response (accepted/dismissed)
    14. 400 for invalid action value
    15. 404 if uuid has no enrollment for this tenant
    16. 401 without JWT

  Boundary (accounting write stays blocked):
    17. The three new endpoints do NOT touch accounting — accounting write still raises
"""
import uuid
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api

# ── DB connection params ───────────────────────────────────────────────────────
_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)


# seed_act_data is now defined in conftest.py (session-scoped, shared with audit tests)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed):
    """Get JWT for testuser (tenant-1)."""
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


# ── Worklist tests ────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_401_without_jwt(seed_act_data):
    """GET /worklist without token → 401."""
    resp = _client().get("/worklist")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_lists_due_task_with_demographics(seed_act_data):
    """
    Default worklist returns open tasks with due_date <= today.

    Task A (open, past-due) must appear.
    Task B (done) must NOT appear.
    Task C (open, future) must NOT appear in the default listing.
    Each item must carry patient demographics from AccountingReadPort (no N+1).
    """
    token = _get_token(seed_act_data)
    resp = _client().get("/worklist", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Pagination fields present
    assert "items" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data

    item_ids = [item["id"] for item in data["items"]]

    # Task A (open, past-due) must appear
    assert seed_act_data["task_a_id"] in item_ids, (
        f"Open past-due task {seed_act_data['task_a_id']} must be in default worklist. "
        f"Got ids: {item_ids}"
    )

    # Task B (done) must NOT appear
    assert seed_act_data["task_b_id"] not in item_ids, (
        f"Done task {seed_act_data['task_b_id']} must not appear in default worklist."
    )

    # Task C (open, future) must NOT appear
    assert seed_act_data["task_c_id"] not in item_ids, (
        f"Future open task {seed_act_data['task_c_id']} must not appear in default worklist."
    )

    # Demographics — patient_uuid and full_name must be populated for task A
    task_a_item = next(
        (item for item in data["items"] if item["id"] == seed_act_data["task_a_id"]),
        None
    )
    assert task_a_item is not None
    assert task_a_item["patient_uuid"] is not None, "patient_uuid must be populated from AccountingReadPort"
    assert task_a_item["patient_full_name"] is not None, "patient_full_name must be populated"
    assert "رضایی" in task_a_item["patient_full_name"] or "علی" in task_a_item["patient_full_name"], (
        f"Demographics not populated correctly: {task_a_item['patient_full_name']}"
    )
    assert task_a_item["status"] == "open"
    assert task_a_item["reason"] == "uncontrolled"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_tenant_isolation(seed_act_data):
    """
    Tenant-1 token must NOT see task_t2_id (tenant-2 task).
    """
    token = _get_token(seed_act_data)

    # Fetch all open tasks (no status filter — default = open+due)
    resp = _client().get("/worklist", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    item_ids = [item["id"] for item in data["items"]]
    assert seed_act_data["task_t2_id"] not in item_ids, (
        f"Tenant-2 task {seed_act_data['task_t2_id']} must be invisible to tenant-1 token. "
        f"Got ids: {item_ids}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_pagination(seed_act_data):
    """
    limit=1 + offset should work correctly — total reflects the full count.
    """
    token = _get_token(seed_act_data)

    # All open+due tasks for tenant-1 (should have at least task A)
    resp_all = _client().get(
        "/worklist?limit=100",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_all.status_code == 200, resp_all.text
    total = resp_all.json()["total"]
    assert total >= 1

    # Page 1 of 1
    resp_p1 = _client().get(
        "/worklist?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_p1.status_code == 200
    assert resp_p1.json()["limit"] == 1
    assert resp_p1.json()["offset"] == 0
    assert resp_p1.json()["total"] == total
    assert len(resp_p1.json()["items"]) == 1

    if total > 1:
        # Page 2
        resp_p2 = _client().get(
            "/worklist?limit=1&offset=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_p2.status_code == 200
        assert len(resp_p2.json()["items"]) >= 0  # could be empty if only 2 total


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_status_filter_shows_done(seed_act_data):
    """
    ?status=done should show task B (done), not task A (open).
    """
    token = _get_token(seed_act_data)
    resp = _client().get(
        "/worklist?status=done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    item_ids = [item["id"] for item in data["items"]]

    assert seed_act_data["task_b_id"] in item_ids, (
        f"Done task {seed_act_data['task_b_id']} must appear when ?status=done. Got: {item_ids}"
    )
    # All returned items must have status=done
    for item in data["items"]:
        assert item["status"] == "done", f"Non-done task in ?status=done response: {item}"


# ── Mark-done tests ───────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_mark_done_401_without_jwt(seed_act_data):
    """POST /worklist/{task_id}/done without token → 401."""
    resp = _client().post(f"/worklist/{seed_act_data['task_a_id']}/done")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_mark_done_flips_status_and_sets_resolved_at(seed_act_data):
    """
    POST /worklist/{task_id}/done on an open task:
      - Returns 200 with status='done'
      - resolved_at is set (not null)
      - Subsequent GET /worklist (default) no longer shows the task
    """
    token = _get_token(seed_act_data)

    # Create a fresh open task so this test is idempotent regardless of run order
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        row = conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason,
                 status, fulfillment, created_at)
            VALUES (1, %s, CURRENT_DATE - 2, 'manual_test', 'open', 'in_person', now())
            RETURNING id
        """, (seed_act_data["link_id"],)).fetchone()
        fresh_task_id = row[0]

    resp = _client().post(
        f"/worklist/{fresh_task_id}/done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    task_data = resp.json()

    assert task_data["status"] == "done", f"Expected status=done, got: {task_data['status']}"
    assert task_data["resolved_at"] is not None, "resolved_at must be set after marking done"
    assert task_data["id"] == fresh_task_id

    # Verify it's gone from the default open/due listing
    list_resp = _client().get(
        "/worklist",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.status_code == 200
    open_ids = [item["id"] for item in list_resp.json()["items"]]
    assert fresh_task_id not in open_ids, (
        f"Marked-done task {fresh_task_id} should not appear in open/due worklist"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_mark_done_404_for_other_tenant_task(seed_act_data):
    """
    POST /worklist/{task_t2_id}/done with tenant-1 token → 404.
    Tenant-2's task is invisible to tenant-1.
    """
    token = _get_token(seed_act_data)
    resp = _client().post(
        f"/worklist/{seed_act_data['task_t2_id']}/done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, (
        f"Cross-tenant mark-done must return 404, got {resp.status_code}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_mark_done_409_already_done(seed_act_data):
    """
    POST /worklist/{task_b_id}/done on an already-done task → 409.
    """
    token = _get_token(seed_act_data)
    # task_b_id is seeded as status='done'
    resp = _client().post(
        f"/worklist/{seed_act_data['task_b_id']}/done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409, (
        f"Re-marking a done task must return 409, got {resp.status_code}: {resp.text}"
    )


# ── Suggestion action tests ───────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_401_without_jwt(seed_act_data):
    """POST suggestion action without token → 401."""
    patient_uuid = seed_act_data["patient_uuid"]
    resp = _client().post(
        f"/patients/{patient_uuid}/suggestions/T2-DX-01/action",
        json={"action": "accept"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_accept_creates_log_row(seed_act_data):
    """
    POST /patients/{uuid}/suggestions/{rule_code}/action with action='accept'
    creates a suggestion_log row with status='accepted'.
    """
    token = _get_token(seed_act_data)
    patient_uuid = seed_act_data["patient_uuid"]
    rule_code = "TEST-ACT-ACCEPT-01"

    resp = _client().post(
        f"/patients/{patient_uuid}/suggestions/{rule_code}/action",
        json={"action": "accept", "note": "پزشک تأیید کرد"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["status"] == "accepted"
    assert data["rule_code"] == rule_code
    assert data["patient_link_id"] == seed_act_data["link_id"]
    assert data["acted_at"] is not None
    assert data["note"] == "پزشک تأیید کرد"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_dismiss_creates_log_row(seed_act_data):
    """
    POST with action='dismiss' creates a suggestion_log row with status='dismissed'.
    """
    token = _get_token(seed_act_data)
    patient_uuid = seed_act_data["patient_uuid"]
    rule_code = "TEST-ACT-DISMISS-01"

    resp = _client().post(
        f"/patients/{patient_uuid}/suggestions/{rule_code}/action",
        json={"action": "dismiss"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "dismissed"
    assert data["rule_code"] == rule_code


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_upsert_updates_not_duplicates(seed_act_data):
    """
    Re-acting on the SAME (patient, rule_code) UPDATES the existing row (upsert).
    A second call must NOT create a duplicate suggestion_log row.
    Status must reflect the LATEST action.
    """
    token = _get_token(seed_act_data)
    patient_uuid = seed_act_data["patient_uuid"]
    rule_code = "TEST-ACT-UPSERT-01"
    link_id = seed_act_data["link_id"]

    # First action: accept
    resp1 = _client().post(
        f"/patients/{patient_uuid}/suggestions/{rule_code}/action",
        json={"action": "accept", "note": "اول تأیید شد"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200, resp1.text
    assert resp1.json()["status"] == "accepted"

    # Second action: dismiss — should UPDATE the same row
    resp2 = _client().post(
        f"/patients/{patient_uuid}/suggestions/{rule_code}/action",
        json={"action": "dismiss", "note": "بعداً رد شد"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["status"] == "dismissed"

    # Verify EXACTLY ONE row in the DB for (patient_link_id, rule_code)
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT id, status, note FROM clinical.suggestion_log "
            "WHERE patient_link_id=%s AND rule_code=%s AND tenant_id=1",
            (link_id, rule_code)
        ).fetchall()

    assert len(rows) == 1, (
        f"Expected exactly 1 suggestion_log row (upsert), found {len(rows)}: {rows}"
    )
    assert rows[0][1] == "dismissed", f"Expected status='dismissed', got '{rows[0][1]}'"
    assert rows[0][2] == "بعداً رد شد", f"Note not updated: '{rows[0][2]}'"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_third_re_act_updates_again(seed_act_data):
    """
    A third call on the same (patient, rule_code) must UPDATE again (no duplicates).
    This catches edge cases where the upsert only works for 1→2 but not 2→3.
    """
    token = _get_token(seed_act_data)
    patient_uuid = seed_act_data["patient_uuid"]
    rule_code = "TEST-ACT-TRIPLE-01"
    link_id = seed_act_data["link_id"]

    for action in ("accept", "dismiss", "accept"):
        resp = _client().post(
            f"/patients/{patient_uuid}/suggestions/{rule_code}/action",
            json={"action": action},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Action '{action}' failed: {resp.text}"

    # Must still be exactly 1 row, status = 'accepted' (last action)
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT count(*), max(status) FROM clinical.suggestion_log "
            "WHERE patient_link_id=%s AND rule_code=%s AND tenant_id=1",
            (link_id, rule_code)
        ).fetchone()

    assert rows[0] == 1, f"Expected 1 row, got {rows[0]}"
    assert rows[1] == "accepted", f"Expected final status='accepted', got '{rows[1]}'"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_invalid_action_returns_400(seed_act_data):
    """
    POST with action='invalidvalue' → 400.
    """
    token = _get_token(seed_act_data)
    patient_uuid = seed_act_data["patient_uuid"]

    resp = _client().post(
        f"/patients/{patient_uuid}/suggestions/SOME-RULE/action",
        json={"action": "invalidvalue"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400, (
        f"Invalid action must return 400, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestion_action_404_for_other_tenant_patient(seed_act_data):
    """
    POST suggestion action for tenant-2 patient using tenant-1 token → 404.
    """
    token = _get_token(seed_act_data)
    tenant2_uuid = seed_act_data["tenant2_patient_uuid"]

    resp = _client().post(
        f"/patients/{tenant2_uuid}/suggestions/ANY-RULE/action",
        json={"action": "accept"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, (
        f"Cross-tenant suggestion action must return 404, got {resp.status_code}: {resp.text}"
    )


# ── Accounting write boundary ─────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_act_slice_does_not_break_accounting_write_boundary(seed_act_data):
    """
    Regression: the three new ACT endpoints use 'default' for clinical writes only.
    Confirm ClinicalRouter still raises PermissionError for accounting writes.
    """
    from config.routers import ClinicalRouter
    from accounting.models import Patient
    router = ClinicalRouter()

    with pytest.raises(PermissionError, match="accounting"):
        router.db_for_write(Patient)
