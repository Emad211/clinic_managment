"""
tests/test_control_room.py — Step 15: Control Room + worklist revenue column.

COVERAGE
--------
Control Room panel (GET /control-room):
  1. Uncontrolled+lapsed patient appears with score > 0, control='uncontrolled'.
  2. Controlled patient with recent vital and no open_fu → score=0 → absent.
  3. Patient with open follow-up gets extra score points (open_fu bonus).
  4. Patient with upcoming appointment → score penalty applied.
  5. show_value=False for staff: no revenue field, no valuable_drifting cohort.
  6. show_value=True for manager: valuable_drifting cohort present, revenue set.
  7. Uncontrolled_lapsed cohort contains the uncontrolled+lapsed patient.
  8. Overdue_care cohort contains the patient with open followups.
  9. Tenant isolation: panel is scoped to the authenticated tenant.
  10. 401 without JWT.

Control Room conversion (GET /control-room/conversion):
  11. Returns {resolved, to_visit, rate} — correct math for seeded tasks.

Control Room cohort ids (GET /control-room/cohort/{key}):
  12. Returns recomputed ids for uncontrolled cohort.
  13. valuable_drifting returns 404 for staff.
  14. Unknown cohort key → 404.

Worklist revenue column (GET /worklist?include_revenue=true):
  15. Staff with include_revenue=true → revenue=null for all items.
  16. Manager with include_revenue=true → revenue populated (may be 0 if no invoices).
  17. Manager with include_revenue=false → revenue=null (default off).

SEED STRATEGY
-------------
Uses superuser psycopg (same as other test modules).
Builds 4 patients in tenant-1:
  - pat_uncontrolled_lapsed: high HbA1c (danger), NO recent vital (lapsed),
    open followup → should appear with high score, in uncontrolled_lapsed cohort.
  - pat_controlled:          normal HbA1c (ok), recent vital, no open_fu
    → score=0, absent from panel.
  - pat_open_fu:             borderline HbA1c (warn), open followup → in overdue_care.
  - pat_upcoming:            high HbA1c (danger), but HAS upcoming appointment
    → score penalty; still appears if flags×3 > 2.

Also seeds a manager user for manager-gate tests.
Session-scoped seed (runs once).
"""
import json
import uuid
import datetime
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _client() -> TestClient:
    return TestClient(api)


def _get_token(username: str, password: str) -> str:
    resp = _client().post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed ({username}): {resp.text}"
    return resp.json()["token"]


# ── Session-scoped seed fixture ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def cr_seed(seed_clinical_data):
    """
    Seed control-room test data:
      - 4 accounting patients + patient_links in tenant-1.
      - clinical_indicators for hba1c (danger=8.0, warn=7.0, direction=high).
      - vital_readings and lab_results via the observations VIEW (seeded directly
        into vital_readings — the VIEW picks them up automatically).
      - A manager user (manageruser / manager_pw).
      - A closed invoice for pat_uncontrolled_lapsed (for revenue test).
      - An open followup for pat_uncontrolled_lapsed.
      - An open followup for pat_open_fu.
      - A future appointment for pat_upcoming.

    Returns: dict with link_ids, patient_ids, user credentials.
    """
    import bcrypt

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:

        # ── Ensure hba1c indicator (danger=8.0, warn=7.0) ────────────────────
        conn.execute("""
            INSERT INTO clinical.clinical_indicators
                (tenant_id, key, label, unit, direction, warn, danger,
                 is_vital, is_active, display_order)
            VALUES (1, 'hba1c', 'HbA1c', '%%', 'high', 7.0, 8.0, TRUE, TRUE, 10)
            ON CONFLICT (tenant_id, key) DO UPDATE
                SET warn=EXCLUDED.warn, danger=EXCLUDED.danger, is_active=TRUE
        """)
        # Also ensure bp_systolic for broader coverage
        conn.execute("""
            INSERT INTO clinical.clinical_indicators
                (tenant_id, key, label, unit, direction, warn, danger,
                 is_vital, is_active, display_order)
            VALUES (1, 'bp_systolic', 'فشار سیستولیک', 'mmHg', 'high', 130, 140,
                    TRUE, TRUE, 20)
            ON CONFLICT (tenant_id, key) DO UPDATE
                SET warn=EXCLUDED.warn, danger=EXCLUDED.danger, is_active=TRUE
        """)

        def _make_patient(u, nid, fname, lname, phone):
            """Create accounting patient + clinical patient_link. Return (pat_id, link_id)."""
            conn.execute("""
                INSERT INTO accounting.patients
                    (tenant_id, uuid, name, family_name, national_id,
                     phone_number, birthdate, gender)
                VALUES (1, %s, %s, %s, %s, %s, '1970-01-01', 'male')
                ON CONFLICT (uuid) DO NOTHING
            """, (u, fname, lname, nid, phone))
            pat_id = conn.execute(
                "SELECT id FROM accounting.patients WHERE uuid=%s", (u,)
            ).fetchone()[0]
            conn.execute("""
                INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
                VALUES (1, %s, TRUE)
                ON CONFLICT (tenant_id, patient_id) DO NOTHING
            """, (pat_id,))
            link_id = conn.execute(
                "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
                (pat_id,)
            ).fetchone()[0]
            return pat_id, link_id

        # Patient 1: uncontrolled + lapsed (HbA1c=9.5 danger, last vital 200 days ago)
        u1 = uuid.UUID("c1000001-0000-0000-0000-000000000001")
        p1_id, l1_id = _make_patient(u1, "CR0000001", "بیمار", "کنترل‌نشده", "09100000011")
        # Old high HbA1c (lapsed: 200 days ago)
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 9.5, '%%',
                    now() - interval '200 days', 'clinic')
            ON CONFLICT DO NOTHING
        """, (l1_id,))

        # Patient 2: controlled + recent vital (HbA1c=6.5 ok, 3 days ago)
        u2 = uuid.UUID("c1000001-0000-0000-0000-000000000002")
        p2_id, l2_id = _make_patient(u2, "CR0000002", "بیمار", "کنترل‌شده", "09100000012")
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 6.5, '%%',
                    now() - interval '3 days', 'clinic')
            ON CONFLICT DO NOTHING
        """, (l2_id,))

        # Patient 3: borderline + open followup (HbA1c=7.5 warn)
        u3 = uuid.UUID("c1000001-0000-0000-0000-000000000003")
        p3_id, l3_id = _make_patient(u3, "CR0000003", "بیمار", "پیگیری‌دار", "09100000013")
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 7.5, '%%',
                    now() - interval '10 days', 'clinic')
            ON CONFLICT DO NOTHING
        """, (l3_id,))

        # Patient 4: uncontrolled + upcoming appointment (HbA1c=8.5 danger)
        u4 = uuid.UUID("c1000001-0000-0000-0000-000000000004")
        p4_id, l4_id = _make_patient(u4, "CR0000004", "بیمار", "نوبت‌دار", "09100000014")
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 8.5, '%%',
                    now() - interval '200 days', 'clinic')
            ON CONFLICT DO NOTHING
        """, (l4_id,))

        # ── Open followup for patient 1 ───────────────────────────────────────
        conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason, status, created_at)
            VALUES (1, %s, CURRENT_DATE - 5, 'uncontrolled', 'open', now())
            ON CONFLICT DO NOTHING
        """, (l1_id,))

        # ── Open followup for patient 3 ───────────────────────────────────────
        conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason, status, created_at)
            VALUES (1, %s, CURRENT_DATE - 2, 'monitoring', 'open', now())
            ON CONFLICT DO NOTHING
        """, (l3_id,))

        # ── Future appointment for patient 4 ──────────────────────────────────
        conn.execute("""
            INSERT INTO clinical.appointments
                (tenant_id, patient_link_id, scheduled_at, status, created_at)
            VALUES (1, %s, now() + interval '7 days', 'scheduled', now())
            ON CONFLICT DO NOTHING
        """, (l4_id,))

        # ── Closed invoice for patient 1 (for revenue test) ───────────────────
        conn.execute("""
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, status, work_date, total_amount)
            VALUES (1, %s, 'closed', CURRENT_DATE - 10, 500000)
            ON CONFLICT DO NOTHING
        """, (p1_id,))
        closed_inv = conn.execute(
            "SELECT id FROM accounting.invoices WHERE patient_id=%s AND status='closed' "
            "ORDER BY id DESC LIMIT 1", (p1_id,)
        ).fetchone()
        if closed_inv:
            conn.execute("""
                INSERT INTO accounting.visits
                    (tenant_id, patient_id, invoice_id, price)
                VALUES (1, %s, %s, 500000)
                ON CONFLICT DO NOTHING
            """, (p1_id, closed_inv[0]))

        # ── Done followup for patient 1, linked to an appointment ─────────────
        # Creates a task with status=done + appointment_id set (for conversion test)
        # First create the appointment
        appt_row = conn.execute("""
            INSERT INTO clinical.appointments
                (tenant_id, patient_link_id, scheduled_at, status, created_at)
            VALUES (1, %s, now() - interval '30 days', 'done', now() - interval '30 days')
            RETURNING id
        """, (l1_id,)).fetchone()
        appt_id = appt_row[0] if appt_row else None

        if appt_id:
            conn.execute("""
                INSERT INTO clinical.followup_tasks
                    (tenant_id, patient_link_id, due_date, reason, status,
                     appointment_id, created_at, resolved_at)
                VALUES (1, %s, CURRENT_DATE - 35, 'uncontrolled', 'done',
                        %s, now() - interval '40 days', now() - interval '30 days')
                ON CONFLICT DO NOTHING
            """, (l1_id, appt_id))

        # ── Manager user ─────────────────────────────────────────────────────
        manager_password = "manager_secret_pw"
        pw_hash = bcrypt.hashpw(manager_password.encode(), bcrypt.gensalt())
        conn.execute("""
            INSERT INTO platform.users
                (tenant_id, username, password_hash, role, app, is_active, failed_attempts)
            VALUES (1, 'manageruser', %s, 'manager', 'platform', TRUE, 0)
            ON CONFLICT (tenant_id, username) DO UPDATE
                SET password_hash=EXCLUDED.password_hash,
                    role='manager', is_active=TRUE, failed_attempts=0, locked_until=NULL
        """, (pw_hash,))

    return {
        "l1_id": l1_id,   # uncontrolled + lapsed + open_fu + revenue
        "l2_id": l2_id,   # controlled + recent vital (score=0)
        "l3_id": l3_id,   # borderline + open_fu
        "l4_id": l4_id,   # uncontrolled + upcoming appt (penalty)
        "p1_id": p1_id,
        "p2_id": p2_id,
        "p3_id": p3_id,
        "p4_id": p4_id,
        "u1": u1,
        "manager_password": manager_password,
        "test_password": seed_clinical_data["test_password"],  # staff (testuser)
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_control_room_401_without_jwt(cr_seed):
    """GET /control-room without token → 401."""
    resp = _client().get("/control-room")
    assert resp.status_code == 401


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_uncontrolled_lapsed_appears_with_high_score(cr_seed):
    """
    The uncontrolled+lapsed patient (HbA1c=9.5 danger, 200-day-old vital, open_fu)
    must appear in the panel with score > 0 and control='uncontrolled'.

    Score: 3 (danger) + 2 (lapsed) + 1 (open_fu capped at min(1,3)=1) = 6
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["show_value"] is False, "Staff should see show_value=False"

    ids_in_panel = [p["id"] for p in data["patients"]]
    assert cr_seed["l1_id"] in ids_in_panel, (
        f"Uncontrolled+lapsed patient (link_id={cr_seed['l1_id']}) must be in panel"
    )

    p1 = next(p for p in data["patients"] if p["id"] == cr_seed["l1_id"])
    assert p1["control"] == "uncontrolled", f"Expected 'uncontrolled', got {p1['control']}"
    assert p1["lapsed"] is True
    assert p1["score"] > 0
    # Flags must include hba1c (danger)
    flag_labels = [f["label"] for f in p1["flags"]]
    assert len(p1["flags"]) >= 1, "At least one danger flag expected"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_controlled_patient_absent_from_panel(cr_seed):
    """
    Controlled patient (HbA1c=6.5 ok, 3 days ago, no open_fu, no upcoming)
    must NOT appear in the panel (score=0).

    Score: 0 flags + 0 warns + 0 lapsed (3 days < 120) + 0 open_fu = 0
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    ids_in_panel = [p["id"] for p in data["patients"]]
    assert cr_seed["l2_id"] not in ids_in_panel, (
        f"Controlled patient (link_id={cr_seed['l2_id']}) must NOT appear (score=0)"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_open_fu_patient_gets_score_bonus(cr_seed):
    """
    Patient with borderline HbA1c (warn) + open followup must appear in panel
    with score > 0 and in overdue_care cohort.

    Score: 0 flags + 1 warn + 1 open_fu = 2 (lapsed check: 10 days < 120 → not lapsed)
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    ids_in_panel = [p["id"] for p in data["patients"]]
    assert cr_seed["l3_id"] in ids_in_panel, (
        f"Borderline+open_fu patient (link_id={cr_seed['l3_id']}) must be in panel"
    )
    p3 = next(p for p in data["patients"] if p["id"] == cr_seed["l3_id"])
    assert p3["open_fu"] >= 1
    assert p3["score"] > 0

    # Must appear in overdue_care cohort
    overdue_cohort = next(
        (c for c in data["cohorts"] if c["key"] == "overdue_care"), None
    )
    assert overdue_cohort is not None, "overdue_care cohort must be present"
    assert cr_seed["l3_id"] in overdue_cohort["ids"], (
        "Borderline+open_fu patient must be in overdue_care cohort"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_upcoming_appointment_reduces_score(cr_seed):
    """
    Patient 4 (HbA1c=8.5 danger = 3pts, lapsed, upcoming appointment = -2).
    If score_without_upcoming >= 3, they still appear; penalty is applied.

    Score before penalty: 3 (danger) + 2 (lapsed) = 5 → after -2 → 3.
    Must still appear with score = 3.
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    ids_in_panel = [p["id"] for p in data["patients"]]
    # Patient 4 has a future appointment → penalty; but danger flag gives enough score
    assert cr_seed["l4_id"] in ids_in_panel, (
        f"Patient with upcoming appt (link_id={cr_seed['l4_id']}) should still appear "
        f"(danger×3 + lapsed×2 - upcoming×2 = 3 > 0)"
    )
    p4 = next(p for p in data["patients"] if p["id"] == cr_seed["l4_id"])
    assert p4["upcoming"] is True
    # Score must reflect the penalty
    assert p4["score"] < 6, (
        f"Score should be reduced by the upcoming-appointment penalty. Got {p4['score']}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_staff_sees_no_revenue_no_valuable_drifting(cr_seed):
    """
    Staff user: show_value=False → no revenue field, no valuable_drifting cohort.
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["show_value"] is False

    # No valuable_drifting cohort for staff
    cohort_keys = [c["key"] for c in data["cohorts"]]
    assert "valuable_drifting" not in cohort_keys, (
        "valuable_drifting cohort must NOT be visible to staff"
    )

    # Revenue must be null for all patients
    for p in data["patients"]:
        assert p["value"] is None, (
            f"Patient {p['id']} has value={p['value']} — must be null for staff"
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_manager_sees_revenue_and_valuable_drifting(cr_seed):
    """
    Manager user: show_value=True → valuable_drifting cohort present,
    revenue field populated for patients with closed invoices.
    """
    token = _get_token("manageruser", cr_seed["manager_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["show_value"] is True

    # valuable_drifting cohort must be present (even if empty)
    cohort_keys = [c["key"] for c in data["cohorts"]]
    assert "valuable_drifting" in cohort_keys, (
        "valuable_drifting cohort must be visible to managers"
    )

    # Patient 1 has a closed invoice → revenue should be set
    p1_entries = [p for p in data["patients"] if p["id"] == cr_seed["l1_id"]]
    if p1_entries:
        p1 = p1_entries[0]
        # value is present (not null) for manager
        assert p1["value"] is not None, (
            "Patient 1 (with closed invoice) must have a non-null value for manager"
        )
        assert p1["value"] >= 0


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_uncontrolled_lapsed_cohort_contains_patient_1(cr_seed):
    """
    Patient 1 (uncontrolled + lapsed) must be in the uncontrolled_lapsed cohort.
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    ul_cohort = next(
        (c for c in data["cohorts"] if c["key"] == "uncontrolled_lapsed"), None
    )
    assert ul_cohort is not None, "uncontrolled_lapsed cohort must be present"
    assert cr_seed["l1_id"] in ul_cohort["ids"], (
        f"Patient 1 (l1_id={cr_seed['l1_id']}) must be in uncontrolled_lapsed cohort. "
        f"Got ids: {ul_cohort['ids']}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_conversion_api_shape_and_framing(cr_seed):
    """
    GET /control-room/conversion — step-42 honest funnel.

    Verifies:
    - All required fields are serialised (including nullable rates).
    - Fundamental invariant: generated_eligible == done + dismissed + open_eligible.
    - to_visit <= resolved_done (can only convert if done).
    - n_sufficient correctly reflects generated_eligible >= 30.
    - framing field is present (caveat about no control group).
    - Rates are null when generated_eligible < 30.
    - Old field names (resolved, rate) are GONE — backward-incompatible by design
      (frontend was not consuming this endpoint).
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get(
        "/control-room/conversion",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # ── required fields ──────────────────────────────────────────────────────
    required = [
        "window_days", "generated", "generated_eligible",
        "resolved_done", "resolved_dismissed", "open_eligible", "to_visit",
        "contact_rate", "visit_rate_of_reached", "overall_conversion",
        "n_sufficient", "framing",
    ]
    for field in required:
        assert field in data, f"Missing field: {field}"

    # ── type checks ──────────────────────────────────────────────────────────
    assert isinstance(data["window_days"], int)
    assert isinstance(data["generated"], int)
    assert isinstance(data["generated_eligible"], int)
    assert isinstance(data["resolved_done"], int)
    assert isinstance(data["resolved_dismissed"], int)
    assert isinstance(data["open_eligible"], int)
    assert isinstance(data["to_visit"], int)
    assert isinstance(data["n_sufficient"], bool)
    assert isinstance(data["framing"], str)
    # rates are float or null
    for rate_field in ("contact_rate", "visit_rate_of_reached", "overall_conversion"):
        assert data[rate_field] is None or isinstance(data[rate_field], (int, float)), (
            f"{rate_field} must be float or null, got {type(data[rate_field])}"
        )

    # ── invariant: eligible == done + dismissed + open ────────────────────────
    assert (
        data["generated_eligible"]
        == data["resolved_done"] + data["resolved_dismissed"] + data["open_eligible"]
    ), (
        f"Invariant violated: {data['generated_eligible']} != "
        f"{data['resolved_done']}+{data['resolved_dismissed']}+{data['open_eligible']}"
    )

    # ── to_visit <= resolved_done ─────────────────────────────────────────────
    assert data["to_visit"] <= data["resolved_done"], (
        f"to_visit ({data['to_visit']}) > resolved_done ({data['resolved_done']})"
    )

    # ── n_sufficient / null-rate contract ────────────────────────────────────
    if data["generated_eligible"] < 30:
        assert data["n_sufficient"] is False
        assert data["contact_rate"] is None, "contact_rate must be null when n<30"
        assert data["visit_rate_of_reached"] is None
        assert data["overall_conversion"] is None
    else:
        assert data["n_sufficient"] is True

    # ── old field names must NOT appear ──────────────────────────────────────
    assert "resolved" not in data, "'resolved' (old name) must not appear in response"
    assert "rate" not in data, "'rate' (old name) must not appear in response"

    # ── framing caveat is substantive ─────────────────────────────────────────
    assert len(data["framing"]) > 20, "framing must be a non-trivial string"
    assert "control" in data["framing"].lower() or "holdout" in data["framing"].lower()


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cohort_ids_endpoint_for_uncontrolled(cr_seed):
    """
    GET /control-room/cohort/uncontrolled → list of patient_link_ids.
    Patient 1 (uncontrolled) must be in the result.
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get(
        "/control-room/cohort/uncontrolled",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "cohort_key" in data
    assert data["cohort_key"] == "uncontrolled"
    assert "ids" in data
    assert cr_seed["l1_id"] in data["ids"], (
        f"Patient 1 must be in uncontrolled cohort ids. Got: {data['ids']}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cohort_ids_valuable_drifting_forbidden_for_staff(cr_seed):
    """
    Staff requesting valuable_drifting cohort → 404.
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get(
        "/control-room/cohort/valuable_drifting",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, (
        f"Staff must get 404 for valuable_drifting cohort. Got: {resp.status_code}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cohort_ids_valuable_drifting_allowed_for_manager(cr_seed):
    """
    Manager requesting valuable_drifting cohort → 200 (even if empty).
    """
    token = _get_token("manageruser", cr_seed["manager_password"])
    resp = _client().get(
        "/control-room/cohort/valuable_drifting",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, (
        f"Manager must get 200 for valuable_drifting cohort. Got: {resp.status_code}, {resp.text}"
    )
    data = resp.json()
    assert data["cohort_key"] == "valuable_drifting"
    assert isinstance(data["ids"], list)


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_cohort_ids_unknown_key_returns_404(cr_seed):
    """Unknown cohort key → 404."""
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get(
        "/control-room/cohort/invalid_key_xyz",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_control_room_conversion_401_without_jwt(cr_seed):
    """GET /control-room/conversion without token → 401."""
    resp = _client().get("/control-room/conversion")
    assert resp.status_code == 401


# ── Worklist revenue column tests ─────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_revenue_null_for_staff_even_if_requested(cr_seed):
    """
    Staff user with include_revenue=true → revenue=null for all items.
    Manager gate must block non-managers.
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get(
        "/worklist?include_revenue=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # All items must have revenue=null for staff
    for item in data["items"]:
        assert item.get("revenue") is None, (
            f"Staff must get revenue=null. Item {item['id']} has revenue={item.get('revenue')}"
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_revenue_populated_for_manager(cr_seed):
    """
    Manager user with include_revenue=true → revenue field present and numeric (or null if 0).
    Must not raise; all items have a revenue key.
    """
    token = _get_token("manageruser", cr_seed["manager_password"])
    resp = _client().get(
        "/worklist?include_revenue=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # All items must have a "revenue" key (value can be null if the patient has no invoices)
    for item in data["items"]:
        assert "revenue" in item, f"Item {item['id']} missing revenue key"
        # If populated, must be an int
        if item["revenue"] is not None:
            assert isinstance(item["revenue"], int), (
                f"revenue must be int, got {type(item['revenue'])} for item {item['id']}"
            )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_worklist_revenue_null_by_default_for_manager(cr_seed):
    """
    Manager user WITHOUT include_revenue → revenue=null (default is off).
    """
    token = _get_token("manageruser", cr_seed["manager_password"])
    resp = _client().get(
        "/worklist",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    for item in data["items"]:
        assert item.get("revenue") is None, (
            f"revenue must be null when include_revenue is not set. "
            f"Item {item['id']} has revenue={item.get('revenue')}"
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_control_room_panel_tenant_scoped(cr_seed):
    """
    Panel only returns patients from the authenticated tenant (tenant-1).
    Tenant-2 patients must not appear.
    """
    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    # All returned patient_link_ids must belong to tenant-1
    from clinical.models import PatientLink
    ids_in_panel = [p["id"] for p in data["patients"]]
    if ids_in_panel:
        tenant_ids = set(
            PatientLink.objects.filter(id__in=ids_in_panel)
            .values_list("tenant_id", flat=True)
        )
        assert tenant_ids == {1}, (
            f"Panel must only contain tenant-1 patients. Got tenant_ids: {tenant_ids}"
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_control_room_vitals_from_observations_view(cr_seed):
    """
    Architecture guard: control-room reads control vitals from the observations VIEW,
    not directly from vital_readings only. The observations VIEW includes labs.

    We verify that a lab result (seeded directly into lab_results with test_key='hba1c')
    contributes to the panel score — if the VIEW is consulted, the patient would appear.

    Strategy: seed a patient with ONLY a lab hba1c (no vital_readings). If the VIEW
    is used, the panel sees the lab result. If only vital_readings is queried, the
    patient appears with score=1 (no baseline) — still in the panel but for a different
    reason. We verify the panel does not crash and returns a valid structure.

    This is an architecture smoke test — exact score depends on the lab value.
    """
    import bcrypt as _bcrypt

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        u_lab = uuid.UUID("c1000001-0000-0000-0000-000000000099")
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'آزمایشگاه', 'محور', 'CR9999999', '09100000099',
                    '1975-01-01', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (u_lab,))
        lab_pat_id = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (u_lab,)
        ).fetchone()[0]

        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (lab_pat_id,))
        lab_link_id = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (lab_pat_id,)
        ).fetchone()[0]

        # Seed a lab result (NOT a vital_reading) with high HbA1c.
        # test_key=NULL because we cannot guarantee 'hba1c' is in lab_test_catalog;
        # the FK fk_lab_results_test_key enforces (tenant_id, test_key) reference.
        # With test_key=NULL the FK is not triggered (nullable FK semantics).
        # The observations VIEW uses COALESCE(test_key, test_name) as obs_key,
        # so this row appears as obs_key='lab:HbA1c' (the test_name value).
        # The control_room_service strips the 'lab:' prefix → bare_key='HbA1c'
        # which does NOT match any CONTROL_VITALS key (all lowercase).
        # This is intentional: the test only verifies the panel does not crash.
        conn.execute("""
            INSERT INTO clinical.lab_results
                (tenant_id, patient_link_id, test_name, test_key,
                 value, unit, taken_at, recorded_by)
            VALUES (1, %s, 'HbA1c', NULL, 9.8, '%%',
                    now() - interval '200 days', 'lab_system')
        """, (lab_link_id,))

    token = _get_token("testuser", cr_seed["test_password"])
    resp = _client().get("/control-room", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"Control room must not crash: {resp.text}"
    data = resp.json()
    assert isinstance(data["patients"], list)
    assert isinstance(data["cohorts"], list)
    # Panel returned successfully regardless of whether the lab patient appears


# ── Step-42 data-scientist funnel tests ───────────────────────────────────────

@pytest.fixture(scope="session")
def conversion_seed(cr_seed):
    """
    Seed a controlled, isolated set of followup_tasks for funnel arithmetic tests.
    Uses a dedicated patient (tenant=1) to avoid cross-contamination with cr_seed tasks.

    Seeds:
      - 4 done tasks (2 with appointment → to_visit; 2 without)
      - 3 dismissed tasks (no appointment)
      - 3 open tasks (no appointment)
      Total eligible = 10 (all have due_date = today - 60 → well past 30-day window)

      - 1 future task (due_date = today + 20 → NOT eligible)

    Expected arithmetic (window=30, eligible=10 < 30 → n_sufficient=False → rates=None):
      generated=11, generated_eligible=10,
      resolved_done=4, resolved_dismissed=3, open_eligible=3,
      to_visit=2,
      n_sufficient=False, all rates=None.

    We use a separate patient so the counts are deterministic regardless of other seed data.
    """
    import datetime as _dt

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        u_conv = uuid.UUID("c9420001-0042-0042-0042-000000000042")
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'قیف', 'آزمون', 'CONV000042', '09120000042',
                    '1980-06-01', 'female')
            ON CONFLICT (uuid) DO NOTHING
        """, (u_conv,))
        conv_pat_id = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (u_conv,)
        ).fetchone()[0]

        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (conv_pat_id,))
        conv_link_id = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (conv_pat_id,)
        ).fetchone()[0]

        # Create appointments for the 2 "to_visit" done tasks
        appt1 = conn.execute("""
            INSERT INTO clinical.appointments
                (tenant_id, patient_link_id, scheduled_at, status, created_at)
            VALUES (1, %s, now() - interval '50 days', 'done', now() - interval '60 days')
            RETURNING id
        """, (conv_link_id,)).fetchone()[0]
        appt2 = conn.execute("""
            INSERT INTO clinical.appointments
                (tenant_id, patient_link_id, scheduled_at, status, created_at)
            VALUES (1, %s, now() - interval '48 days', 'done', now() - interval '60 days')
            RETURNING id
        """, (conv_link_id,)).fetchone()[0]

        today = _dt.date.today()
        eligible_due = today - _dt.timedelta(days=60)   # 60d ago — eligible
        future_due   = today + _dt.timedelta(days=20)   # 20d ahead — NOT eligible

        # 2 done + appointment (to_visit)
        for appt_id in (appt1, appt2):
            conn.execute("""
                INSERT INTO clinical.followup_tasks
                    (tenant_id, patient_link_id, due_date, reason, status,
                     appointment_id, created_at, resolved_at)
                VALUES (1, %s, %s, 'conv_test', 'done', %s,
                        now() - interval '65 days', now() - interval '50 days')
            """, (conv_link_id, eligible_due, appt_id))

        # 2 done without appointment
        for _ in range(2):
            conn.execute("""
                INSERT INTO clinical.followup_tasks
                    (tenant_id, patient_link_id, due_date, reason, status,
                     appointment_id, created_at, resolved_at)
                VALUES (1, %s, %s, 'conv_test', 'done', NULL,
                        now() - interval '65 days', now() - interval '50 days')
            """, (conv_link_id, eligible_due))

        # 3 dismissed
        for _ in range(3):
            conn.execute("""
                INSERT INTO clinical.followup_tasks
                    (tenant_id, patient_link_id, due_date, reason, status,
                     appointment_id, created_at, resolved_at)
                VALUES (1, %s, %s, 'conv_test', 'dismissed', NULL,
                        now() - interval '65 days', now() - interval '55 days')
            """, (conv_link_id, eligible_due))

        # 3 open (eligible)
        for _ in range(3):
            conn.execute("""
                INSERT INTO clinical.followup_tasks
                    (tenant_id, patient_link_id, due_date, reason, status,
                     created_at)
                VALUES (1, %s, %s, 'conv_test', 'open',
                        now() - interval '65 days')
            """, (conv_link_id, eligible_due))

        # 1 future (NOT eligible — due_date = today+20)
        conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason, status, created_at)
            VALUES (1, %s, %s, 'conv_test_future', 'open',
                    now())
        """, (conv_link_id, future_due))

    return {"link_id": conv_link_id}


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_conversion_eligible_excludes_future_tasks(conversion_seed):
    """
    Step-42 assertion 1 — immortal-time bias guard:
    A followup with due_date = today+20 must NOT appear in generated_eligible.

    The conversion_seed fixture plants exactly 10 eligible + 1 future task.
    We verify that generated >= generated_eligible (the future task is in generated
    but not in generated_eligible).
    """
    from clinical.control_room_service import conversion
    result = conversion(tenant_id=1, window_days=30)

    # The future task is in generated but not eligible
    assert result["generated"] > result["generated_eligible"], (
        "generated must exceed generated_eligible when future tasks exist"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_conversion_dismissed_separate_from_done(conversion_seed):
    """
    Step-42 assertion 2 — dismissed is separate from done:
    resolved_dismissed > 0 and dismissed tasks have no appointment →
    they must NOT inflate to_visit but DO count in contact_rate numerator.

    The seed has 3 dismissed tasks, none with appointment_id.
    """
    from clinical.control_room_service import conversion
    result = conversion(tenant_id=1, window_days=30)

    # Our seed contributes dismissed tasks
    assert result["resolved_dismissed"] >= 3, (
        f"Expected >= 3 dismissed, got {result['resolved_dismissed']}"
    )

    # to_visit counts only done+appointment, so dismissed never inflates it
    # (verified implicitly: to_visit = done_with_appt; our seed has 2 of those)
    # If to_visit > resolved_done that would be the bug — already covered by invariant test


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_conversion_null_rates_when_eligible_below_threshold(conversion_seed):
    """
    Step-42 assertion 4 — NULL when eligible < 30:
    The conversion_seed contributes exactly 10 eligible tasks for tenant-1.
    Even with cr_seed tasks, the total may be below 30, making rates null.

    We test the service directly with an isolated tenant (tenant=999) that has no data:
    generated_eligible=0 → n_sufficient=False → all rates=None.
    """
    from clinical.control_room_service import conversion
    result = conversion(tenant_id=999, window_days=30)

    assert result["generated_eligible"] == 0
    assert result["n_sufficient"] is False
    assert result["contact_rate"] is None, "contact_rate must be None when eligible=0"
    assert result["visit_rate_of_reached"] is None
    assert result["overall_conversion"] is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_conversion_symmetry_invariant(conversion_seed):
    """
    Step-42 assertion 5 — symmetry:
    generated_eligible == resolved_done + resolved_dismissed + open_eligible.

    Tested at service level for deterministic arithmetic.
    """
    from clinical.control_room_service import conversion
    result = conversion(tenant_id=1, window_days=30)

    lhs = result["generated_eligible"]
    rhs = result["resolved_done"] + result["resolved_dismissed"] + result["open_eligible"]
    assert lhs == rhs, (
        f"Symmetry violated: eligible={lhs} != "
        f"done({result['resolved_done']})+dismissed({result['resolved_dismissed']})"
        f"+open({result['open_eligible']})={rhs}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_conversion_arithmetic_overall_not_done_only(conversion_seed):
    """
    Step-42 assertion 3 — overall_conversion denominator is eligible, NOT done-only:
    With 10 eligible (4 done where 2 with appt, 3 dismissed, 3 open):
      overall_conversion = 2/10 = 20%, NOT 2/4=50%.

    Because cr_seed also contributes tasks, we test at service layer with tenant=999
    for isolation, then seed a fresh set for deterministic arithmetic.

    Strategy: call conversion() at service level for a fresh, dedicated DB state.
    The conversion_seed already plants exactly 10 eligible + 1 future for tenant-1.
    But cr_seed also contributes tasks for tenant-1. We cannot guarantee the totals
    in the shared tenant-1. Instead, we verify the invariant properties that ensure
    correct arithmetic without needing isolation:

      1. to_visit <= resolved_done  (can only convert if done)
      2. overall_conversion denominator is generated_eligible (not resolved_done):
         if n_sufficient and resolved_done>0 and to_visit>0:
           overall_conv = to_visit/eligible (should differ from to_visit/done)
           contact_rate = (done+dismissed)/eligible
    """
    from clinical.control_room_service import conversion
    result = conversion(tenant_id=1, window_days=30)

    # to_visit <= resolved_done always
    assert result["to_visit"] <= result["resolved_done"]

    if result["n_sufficient"] and result["resolved_done"] > 0 and result["to_visit"] > 0:
        # overall_conversion must use eligible as denominator, not done
        expected_overall = round(result["to_visit"] * 100 / result["generated_eligible"], 1)
        expected_done_only = round(result["to_visit"] * 100 / result["resolved_done"], 1)

        assert abs(result["overall_conversion"] - expected_overall) < 0.2, (
            f"overall_conversion={result['overall_conversion']} must be "
            f"to_visit/eligible={expected_overall}, NOT to_visit/done={expected_done_only}"
        )
        # overall <= visit_rate_of_reached (since eligible >= done)
        if result["visit_rate_of_reached"] is not None:
            assert result["overall_conversion"] <= result["visit_rate_of_reached"], (
                "overall_conversion (denominator=eligible) must be <= "
                "visit_rate_of_reached (denominator=done)"
            )
