"""
Step 14 — Doctor visit queue tests.

Coverage:
  Service layer (direct calls, no HTTP):
    1.  get_queue: open invoice with visit → status 'waiting', enrolled=True, correct patient_link_id.
    2.  get_queue: closed invoice MUST NOT appear in the queue.
    3.  start_visit: status → in_progress, started_at set.
    4.  end_visit: status → done, done_at set, done_by set. Entry moves to 'done' list.
    5.  Idempotent-ish: start then done in sequence (happy path).
    6.  start_visit on already-in_progress → InvoiceNotOpen raised.
    7.  end_visit on already-done → VisitAlreadyDone raised.
    8.  Tenant isolation: invoice in tenant-1 does not appear in tenant-2 queue.

  Endpoint layer (HTTP via TestClient):
    9.  GET /doctor-queue?work_date=... → 200 with correct shape.
    10. GET /doctor-queue → 401 without JWT.
    11. POST /doctor-queue/{invoice_id}/start → 200, status in_progress + started_at.
    12. POST /doctor-queue/{invoice_id}/done → 200, status done + done_at + done_by.
        After done: queue GET shows it in done list.
    13. POST /doctor-queue/{invoice_id}/start on already in_progress → 409 conflict.

  Boundary:
    14. Assert NO write to accounting.invoices or accounting.patients occurs.
        (The DB-level GRANTs already enforce this for the app role; the test
        verifies that the fetch_open_visit_invoices cursor and start/end_visit
        paths do NOT touch any accounting table in DML — we check row counts.)

All tests use @pytest.mark.django_db(transaction=True) and the session-scoped
seed fixture (seed_act_data extends seed_data → seed_clinical_data).

Seed strategy:
  - Seed an OPEN invoice WITH a visit (open_inv_id) for today (tenant 1).
  - Seed a CLOSED invoice (closed_inv_id) — must not appear.
  - seed_data already provides a patient_links row for the same patient.
  - tenant_isolation: tenant-2 patient and invoice also seeded.

All seeds done as superuser psycopg (accounting.patients/invoices/visits
are write-forbidden for the app role — same pattern as conftest.seed_data).
"""
import uuid
import pytest
import psycopg
from datetime import date

from ninja.testing import TestClient
from config.api import api

# ---------------------------------------------------------------------------
# Helpers (copied pattern from test_encounter_api.py)
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed: dict) -> str:
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_error_contract(body: dict, expected_code: str) -> None:
    assert "detail" in body, f"Missing 'detail' in error body: {body}"
    assert isinstance(body["detail"], str) and body["detail"]
    assert "code" in body, f"Missing 'code' in error body: {body}"
    assert body["code"] == expected_code, (
        f"Expected code={expected_code!r}, got {body['code']!r}"
    )


# ---------------------------------------------------------------------------
# Session-scoped seed fixture — seeds accounting invoices/visits as superuser
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def seed_queue_data(seed_act_data):
    """
    Extend the existing session seed with:
      - An OPEN accounting invoice WITH a visit for today (tenant 1).
      - A CLOSED accounting invoice (must NOT appear in queue).
      - An OPEN invoice for tenant 2 (isolation test).
    Returns dict with invoice ids and today's date string.
    """
    from tests.conftest import (
        PG_HOST, PG_PORT, PG_SU_USER, PG_SU_PASSWORD, TEST_DB_NAME
    )

    today = date.today().isoformat()  # YYYY-MM-DD
    patient_id = seed_act_data["patient_id"]          # tenant-1 accounting patient

    su_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'"
    )

    with psycopg.connect(su_conninfo, autocommit=True) as conn:
        # ── Open invoice + visit for tenant-1 ────────────────────────────────
        row = conn.execute("""
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, status, work_date, opened_at)
            VALUES (1, %s, 'open', %s::date, now())
            RETURNING id
        """, (patient_id, today)).fetchone()
        open_inv_id = row[0]

        # Insert a visit row so EXISTS(...) is satisfied
        conn.execute("""
            INSERT INTO accounting.visits
                (tenant_id, patient_id, invoice_id, price, work_date)
            VALUES (1, %s, %s, 50000, %s::date)
        """, (patient_id, open_inv_id, today))

        # ── Closed invoice (must NOT appear in queue) ─────────────────────────
        row = conn.execute("""
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, status, work_date, opened_at)
            VALUES (1, %s, 'closed', %s::date, now() - interval '1 hour')
            RETURNING id
        """, (patient_id, today)).fetchone()
        closed_inv_id = row[0]

        # Visit under closed invoice
        conn.execute("""
            INSERT INTO accounting.visits
                (tenant_id, patient_id, invoice_id, price, work_date)
            VALUES (1, %s, %s, 30000, %s::date)
        """, (patient_id, closed_inv_id, today))

        # ── Tenant-2: open invoice + visit ────────────────────────────────────
        t2_patient_id = seed_act_data["tenant2_patient_id"]
        row = conn.execute("""
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, status, work_date, opened_at)
            VALUES (2, %s, 'open', %s::date, now())
            RETURNING id
        """, (t2_patient_id, today)).fetchone()
        t2_open_inv_id = row[0]

        conn.execute("""
            INSERT INTO accounting.visits
                (tenant_id, patient_id, invoice_id, price, work_date)
            VALUES (2, %s, %s, 20000, %s::date)
        """, (t2_patient_id, t2_open_inv_id, today))

    return {
        **seed_act_data,
        "open_inv_id": open_inv_id,
        "closed_inv_id": closed_inv_id,
        "t2_open_inv_id": t2_open_inv_id,
        "today": today,
    }


# ===========================================================================
# Service-layer tests
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_queue_shows_open_invoice_waiting_and_enrolled(seed_queue_data):
    """Open invoice for today → appears in 'waiting' list, enrolled=True."""
    from clinical.doctor_queue_service import get_queue

    queue = get_queue(work_date=seed_queue_data["today"], tenant_id=1)

    invoice_ids = [e["invoice_id"] for e in queue["waiting"]]
    assert seed_queue_data["open_inv_id"] in invoice_ids, (
        f"Open invoice {seed_queue_data['open_inv_id']} not in waiting list: {invoice_ids}"
    )

    entry = next(e for e in queue["waiting"] if e["invoice_id"] == seed_queue_data["open_inv_id"])
    assert entry["status"] == "waiting"
    assert entry["enrolled"] is True
    assert entry["patient_link_id"] == seed_queue_data["link_id"]
    assert entry["done_by"] is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_queue_does_not_show_closed_invoice(seed_queue_data):
    """Closed invoice for today → does NOT appear in any queue list."""
    from clinical.doctor_queue_service import get_queue

    queue = get_queue(work_date=seed_queue_data["today"], tenant_id=1)

    all_ids = [e["invoice_id"] for e in queue["waiting"] + queue["done"]]
    assert seed_queue_data["closed_inv_id"] not in all_ids, (
        f"Closed invoice {seed_queue_data['closed_inv_id']} must not appear in queue: {all_ids}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_start_visit_transitions_to_in_progress(seed_queue_data):
    """start_visit → status in_progress, started_at set."""
    from clinical.doctor_queue_service import get_queue, start_visit
    from clinical.models import DoctorVisitLog

    inv_id = seed_queue_data["open_inv_id"]
    today = seed_queue_data["today"]

    # Ensure no existing log row for this invoice (clean per-test via transaction rollback)
    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=inv_id).delete()

    # Build snapshot (same as the endpoint does)
    from accounting_port.port import fetch_open_visit_invoices
    invoices = fetch_open_visit_invoices(work_date=today, tenant_id=1)
    inv = next((i for i in invoices if i.invoice_id == inv_id), None)
    assert inv is not None, "Open invoice not found via port"

    snapshot = {
        "full_name": inv.full_name,
        "work_date": inv.work_date,
        "patient_uuid": inv.patient_uuid,
        "patient_link_id": seed_queue_data["link_id"],
    }

    row = start_visit(accounting_invoice_id=inv_id, tenant_id=1, snapshot=snapshot)
    assert row.status == DoctorVisitLog.STATUS_IN_PROGRESS
    assert row.started_at is not None
    assert row.done_at is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_end_visit_transitions_to_done(seed_queue_data):
    """start then end_visit → status done, done_at + done_by set."""
    from clinical.doctor_queue_service import get_queue, start_visit, end_visit
    from clinical.models import DoctorVisitLog

    inv_id = seed_queue_data["open_inv_id"]
    today = seed_queue_data["today"]

    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=inv_id).delete()

    from accounting_port.port import fetch_open_visit_invoices
    invoices = fetch_open_visit_invoices(work_date=today, tenant_id=1)
    inv = next(i for i in invoices if i.invoice_id == inv_id)

    snapshot = {
        "full_name": inv.full_name,
        "work_date": inv.work_date,
        "patient_uuid": inv.patient_uuid,
        "patient_link_id": seed_queue_data["link_id"],
    }

    start_visit(accounting_invoice_id=inv_id, tenant_id=1, snapshot=snapshot)
    done_row = end_visit(
        accounting_invoice_id=inv_id,
        tenant_id=1,
        done_by="dr_test",
        notes="all good",
    )

    assert done_row.status == DoctorVisitLog.STATUS_DONE
    assert done_row.done_at is not None
    assert done_row.done_by == "dr_test"
    assert done_row.physician_notes == "all good"

    # Should appear in done list
    queue = get_queue(work_date=today, tenant_id=1)
    done_ids = [e["invoice_id"] for e in queue["done"]]
    assert inv_id in done_ids, f"Invoice {inv_id} should be in done list: {done_ids}"
    waiting_ids = [e["invoice_id"] for e in queue["waiting"]]
    assert inv_id not in waiting_ids


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_start_visit_on_in_progress_raises(seed_queue_data):
    """start_visit when already in_progress → InvoiceNotOpen."""
    from clinical.doctor_queue_service import start_visit, InvoiceNotOpen
    from clinical.models import DoctorVisitLog

    inv_id = seed_queue_data["open_inv_id"]
    today = seed_queue_data["today"]

    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=inv_id).delete()

    from accounting_port.port import fetch_open_visit_invoices
    invoices = fetch_open_visit_invoices(work_date=today, tenant_id=1)
    inv = next(i for i in invoices if i.invoice_id == inv_id)
    snapshot = {
        "full_name": inv.full_name,
        "work_date": inv.work_date,
        "patient_uuid": inv.patient_uuid,
        "patient_link_id": seed_queue_data["link_id"],
    }

    # First start — OK
    start_visit(accounting_invoice_id=inv_id, tenant_id=1, snapshot=snapshot)

    # Second start — must raise
    with pytest.raises(InvoiceNotOpen):
        start_visit(accounting_invoice_id=inv_id, tenant_id=1, snapshot=snapshot)


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_end_visit_on_done_raises(seed_queue_data):
    """end_visit when already done → VisitAlreadyDone."""
    from clinical.doctor_queue_service import start_visit, end_visit, VisitAlreadyDone
    from clinical.models import DoctorVisitLog

    inv_id = seed_queue_data["open_inv_id"]
    today = seed_queue_data["today"]

    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=inv_id).delete()

    from accounting_port.port import fetch_open_visit_invoices
    invoices = fetch_open_visit_invoices(work_date=today, tenant_id=1)
    inv = next(i for i in invoices if i.invoice_id == inv_id)
    snapshot = {
        "full_name": inv.full_name,
        "work_date": inv.work_date,
        "patient_uuid": inv.patient_uuid,
        "patient_link_id": seed_queue_data["link_id"],
    }

    start_visit(accounting_invoice_id=inv_id, tenant_id=1, snapshot=snapshot)
    end_visit(accounting_invoice_id=inv_id, tenant_id=1, done_by="dr_test")

    with pytest.raises(VisitAlreadyDone):
        end_visit(accounting_invoice_id=inv_id, tenant_id=1, done_by="dr_test")


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_tenant_isolation_queue(seed_queue_data):
    """Tenant-1 queue does not contain the tenant-2 open invoice."""
    from clinical.doctor_queue_service import get_queue

    queue_t1 = get_queue(work_date=seed_queue_data["today"], tenant_id=1)
    all_ids_t1 = [e["invoice_id"] for e in queue_t1["waiting"] + queue_t1["done"]]
    assert seed_queue_data["t2_open_inv_id"] not in all_ids_t1, (
        f"Tenant-2 invoice {seed_queue_data['t2_open_inv_id']} must not appear in tenant-1 queue"
    )


# ===========================================================================
# Endpoint tests (HTTP via TestClient)
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_queue_endpoint_200_shape(seed_queue_data):
    """GET /doctor-queue?work_date=... → 200, correct shape, open invoice present."""
    from clinical.models import DoctorVisitLog

    token = _get_token(seed_queue_data)
    today = seed_queue_data["today"]
    open_inv_id = seed_queue_data["open_inv_id"]

    # Clean any prior log state from service-layer tests (they commit with transaction=True)
    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=open_inv_id).delete()

    resp = _client().get(
        f"/doctor-queue?work_date={today}",
        headers=_auth(token),
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "waiting" in body
    assert "done" in body
    assert "work_date" in body
    assert body["work_date"] == today

    # Our open invoice must appear in waiting or done (any queue list)
    all_ids = [e["invoice_id"] for e in body["waiting"] + body["done"]]
    assert open_inv_id in all_ids, (
        f"Open invoice {open_inv_id} not in any queue list: waiting={[e['invoice_id'] for e in body['waiting']]} done={[e['invoice_id'] for e in body['done']]}"
    )

    # Entry shape — find it in whichever list it is
    entry = next(
        (e for e in body["waiting"] + body["done"] if e["invoice_id"] == open_inv_id),
        None,
    )
    assert entry is not None
    assert "status" in entry
    assert "enrolled" in entry
    assert "patient_link_id" in entry
    assert "full_name" in entry


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_get_queue_endpoint_401_without_jwt(seed_queue_data):
    """GET /doctor-queue without JWT → 401."""
    today = seed_queue_data["today"]
    resp = _client().get(f"/doctor-queue?work_date={today}")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_start_endpoint_transitions_in_progress(seed_queue_data):
    """POST /doctor-queue/{id}/start → 200, status in_progress, started_at set."""
    from clinical.models import DoctorVisitLog

    token = _get_token(seed_queue_data)
    inv_id = seed_queue_data["open_inv_id"]

    # Clean any prior log row
    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=inv_id).delete()

    resp = _client().post(
        f"/doctor-queue/{inv_id}/start",
        headers=_auth(token),
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["status"] == "in_progress", f"Expected in_progress, got {body['status']}"
    assert body["started_at"] is not None
    assert body["accounting_invoice_id"] == inv_id
    assert body["done_at"] is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_done_endpoint_transitions_done_and_queue_moves(seed_queue_data):
    """POST /doctor-queue/{id}/done → 200, status done + done_at + done_by; queue moves to done list."""
    from clinical.models import DoctorVisitLog

    token = _get_token(seed_queue_data)
    inv_id = seed_queue_data["open_inv_id"]
    today = seed_queue_data["today"]

    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=inv_id).delete()

    # Start first
    r = _client().post(f"/doctor-queue/{inv_id}/start", headers=_auth(token))
    assert r.status_code == 200

    # Done
    resp = _client().post(
        f"/doctor-queue/{inv_id}/done",
        json={"notes": "visit complete"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["status"] == "done"
    assert body["done_at"] is not None
    assert body["done_by"] == "testuser"   # JWT user from seed
    assert body["physician_notes"] == "visit complete"

    # Verify queue reflects the change
    q_resp = _client().get(f"/doctor-queue?work_date={today}", headers=_auth(token))
    assert q_resp.status_code == 200
    q = q_resp.json()
    done_ids = [e["invoice_id"] for e in q["done"]]
    waiting_ids = [e["invoice_id"] for e in q["waiting"]]
    assert inv_id in done_ids, f"Invoice {inv_id} should be in done list"
    assert inv_id not in waiting_ids, f"Invoice {inv_id} must not be in waiting list"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_start_endpoint_409_if_already_in_progress(seed_queue_data):
    """POST /doctor-queue/{id}/start when already in_progress → 409 conflict."""
    from clinical.models import DoctorVisitLog

    token = _get_token(seed_queue_data)
    inv_id = seed_queue_data["open_inv_id"]

    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=inv_id).delete()

    # First start
    r = _client().post(f"/doctor-queue/{inv_id}/start", headers=_auth(token))
    assert r.status_code == 200

    # Second start — 409
    resp = _client().post(f"/doctor-queue/{inv_id}/start", headers=_auth(token))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    _assert_error_contract(resp.json(), "conflict")


# ===========================================================================
# Boundary: no accounting write
# ===========================================================================

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_no_accounting_write_during_queue_operations(seed_queue_data):
    """
    Verify that start_visit + end_visit do not alter accounting row counts.

    We count accounting.invoices and accounting.patients BEFORE and AFTER
    the full start→done cycle.  If any write occurred, the counts would change
    or psycopg would have already raised InsufficientPrivilege at DB level
    (the app role has only SELECT on accounting.*).

    This test is belt-and-suspenders: the DB-level GRANTs already prevent
    accounting writes for the app role (proven in test_db_boundary.py).
    Here we assert the service-level intent is honoured — no DML is even
    attempted against accounting tables.
    """
    import os
    import psycopg

    PG_HOST = os.environ.get("PG_HOST", "localhost")
    PG_PORT = os.environ.get("PG_PORT", "55432")
    TEST_DB_NAME = os.environ.get("PG_TEST_DB", "halqe_app_test")
    PG_SU_USER = os.environ.get("PG_USER", "postgres")
    PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")

    su_conninfo = (
        f"host='{PG_HOST}' port='{PG_PORT}' "
        f"user='{PG_SU_USER}' password='{PG_SU_PASSWORD}' dbname='{TEST_DB_NAME}'"
    )

    from clinical.doctor_queue_service import start_visit, end_visit
    from clinical.models import DoctorVisitLog
    from accounting_port.port import fetch_open_visit_invoices

    inv_id = seed_queue_data["open_inv_id"]
    today = seed_queue_data["today"]

    DoctorVisitLog.objects.filter(tenant_id=1, accounting_invoice_id=inv_id).delete()

    # Count BEFORE
    with psycopg.connect(su_conninfo, autocommit=True) as conn:
        inv_count_before = conn.execute(
            "SELECT COUNT(*) FROM accounting.invoices"
        ).fetchone()[0]
        pat_count_before = conn.execute(
            "SELECT COUNT(*) FROM accounting.patients"
        ).fetchone()[0]

    # Run start + end
    invoices = fetch_open_visit_invoices(work_date=today, tenant_id=1)
    inv = next(i for i in invoices if i.invoice_id == inv_id)
    snapshot = {
        "full_name": inv.full_name,
        "work_date": inv.work_date,
        "patient_uuid": inv.patient_uuid,
        "patient_link_id": seed_queue_data["link_id"],
    }
    start_visit(accounting_invoice_id=inv_id, tenant_id=1, snapshot=snapshot)
    end_visit(accounting_invoice_id=inv_id, tenant_id=1, done_by="boundary_test")

    # Count AFTER — must be identical
    with psycopg.connect(su_conninfo, autocommit=True) as conn:
        inv_count_after = conn.execute(
            "SELECT COUNT(*) FROM accounting.invoices"
        ).fetchone()[0]
        pat_count_after = conn.execute(
            "SELECT COUNT(*) FROM accounting.patients"
        ).fetchone()[0]

    assert inv_count_before == inv_count_after, (
        f"accounting.invoices count changed: {inv_count_before} → {inv_count_after}"
    )
    assert pat_count_before == pat_count_after, (
        f"accounting.patients count changed: {pat_count_before} → {pat_count_after}"
    )
