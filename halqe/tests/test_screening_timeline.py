"""
tests/test_screening_timeline.py — Step 37 (Cluster I): screening timeline tests.

Tests cover:
  1. Unit-level: screening_timeline() status logic (never_done, overdue, due_soon, ok).
  2. Unit-level: items with months==0 or months==None excluded.
  3. Unit-level: items from inactive conditions excluded.
  4. API-level: GET /patients/{uuid}/screening-timeline → all DTO fields present
     (guard against the field-serialization regression seen in steps 34/36).
  5. API-level: only periodic items appear (no every-visit / vaccine items).
  6. API-level: suggestion_only always True, framing correct.
  7. Read-only: no followup_tasks created after calling the endpoint.

Strategy: plan B (catalog-driven) — ITEM_CONDITIONS maps items to condition codes;
the patient's active conditions determine which items appear.
Uses condition codes as stored in DB: diabetes / hypertension / hyperlipidemia / ckd / thyroid.
"""
import json
import uuid
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api

# ── Connection helpers ────────────────────────────────────────────────────────
_SU_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)


# ── Session fixture: seed screening-specific patients ────────────────────────

@pytest.fixture(scope="session")
def seed_screening_data(seed_clinical_data):
    """
    Extend seed_clinical_data with patients for screening timeline tests.

    Patients created:
      - scr_dm_ok_uuid    : DM patient, HbA1c 1 month ago → a1c=ok
      - scr_dm_over_uuid  : DM patient, HbA1c 8 months ago → a1c=overdue
      - scr_dm_soon_uuid  : DM patient, HbA1c 5m15d ago → a1c=due_soon
      - scr_dm_never_uuid : DM patient, no HbA1c ever → a1c=never_done
      - scr_htn_uuid      : HTN-only patient (no DM) → renal appears, eye/foot absent

    All in tenant-1.
    """
    def _seed_patient(conn, u, nid, phone, family_name, birthdate="1975-01-01"):
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'تست', %s, %s, %s, %s, 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (u, family_name, nid, phone, birthdate))
        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (u,)
        ).fetchone()
        pat_id = row[0]
        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (pat_id,))
        row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (pat_id,)
        ).fetchone()
        return pat_id, row[0]

    def _add_condition(conn, link_id, code):
        row = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=1 AND code=%s", (code,)
        ).fetchone()
        if not row:
            return
        cond_id = row[0]
        conn.execute("""
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES (1, %s, %s, TRUE, now())
            ON CONFLICT DO NOTHING
        """, (link_id, cond_id))

    def _add_hba1c(conn, link_id, interval_expr):
        """Insert a hba1c vital_reading `interval_expr` ago (e.g. '1 month')."""
        conn.execute(f"""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 7.5, '%%', now() - interval '{interval_expr}', 'clinic')
            ON CONFLICT DO NOTHING
        """, (link_id,))

    scr_dm_ok_uuid    = uuid.UUID("b0000001-0000-0000-0000-000000000001")
    scr_dm_over_uuid  = uuid.UUID("b0000001-0000-0000-0000-000000000002")
    scr_dm_soon_uuid  = uuid.UUID("b0000001-0000-0000-0000-000000000003")
    scr_dm_never_uuid = uuid.UUID("b0000001-0000-0000-0000-000000000004")
    scr_htn_uuid      = uuid.UUID("b0000001-0000-0000-0000-000000000005")

    with psycopg.connect(_SU_CONNINFO, autocommit=True) as conn:
        # DM + ok: HbA1c 1 month ago (interval=6) → ok
        _, ok_link  = _seed_patient(conn, scr_dm_ok_uuid,    "SCR0001", "09011111001", "اُکی")
        _add_condition(conn, ok_link, "diabetes")
        _add_hba1c(conn, ok_link, "1 month")

        # DM + overdue: HbA1c 8 months ago (interval=6) → overdue
        _, over_link = _seed_patient(conn, scr_dm_over_uuid, "SCR0002", "09011111002", "دیر")
        _add_condition(conn, over_link, "diabetes")
        _add_hba1c(conn, over_link, "8 months")

        # DM + due_soon: HbA1c 5 months 15 days ago → due_soon (30 days window)
        _, soon_link = _seed_patient(conn, scr_dm_soon_uuid, "SCR0003", "09011111003", "نزدیک")
        _add_condition(conn, soon_link, "diabetes")
        _add_hba1c(conn, soon_link, "5 months 15 days")

        # DM + never: no HbA1c → never_done
        _, never_link = _seed_patient(conn, scr_dm_never_uuid, "SCR0004", "09011111004", "هرگز")
        _add_condition(conn, never_link, "diabetes")

        # HTN-only: renal should appear, eye/foot should NOT
        _, htn_link  = _seed_patient(conn, scr_htn_uuid,    "SCR0005", "09011111005", "فشاری")
        _add_condition(conn, htn_link, "hypertension")

    return {
        **seed_clinical_data,
        "scr_dm_ok_uuid":    scr_dm_ok_uuid,
        "scr_dm_over_uuid":  scr_dm_over_uuid,
        "scr_dm_soon_uuid":  scr_dm_soon_uuid,
        "scr_dm_never_uuid": scr_dm_never_uuid,
        "scr_htn_uuid":      scr_htn_uuid,
        "ok_link":    ok_link,
        "over_link":  over_link,
        "soon_link":  soon_link,
        "never_link": never_link,
        "htn_link":   htn_link,
    }


# ── TestClient helper ─────────────────────────────────────────────────────────

def _ninja_client() -> TestClient:
    return TestClient(api)


def _get_token(seed):
    """Get JWT for testuser via ninja TestClient."""
    resp = _ninja_client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


# ═══════════════════════════════════════════════════════════════════════════════
# Unit-level: screening_timeline() function
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_ok_status(seed_screening_data):
    """HbA1c done 1 month ago (interval=6) → a1c item status='ok'."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["ok_link"]
    items = screening_timeline(pid, tenant_id=1)
    a1c = next((i for i in items if i["item_key"] == "a1c"), None)
    assert a1c is not None, "a1c must appear for DM patient"
    assert a1c["status"] == "ok", (
        f"Expected ok (HbA1c 1m ago, interval 6m), got {a1c['status']}"
    )
    # next_due_at must be set and in the future
    assert a1c["next_due_at"] is not None
    assert a1c["last_done_at"] is not None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_overdue_status(seed_screening_data):
    """HbA1c done 8 months ago (interval=6) → a1c item status='overdue'."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["over_link"]
    items = screening_timeline(pid, tenant_id=1)
    a1c = next((i for i in items if i["item_key"] == "a1c"), None)
    assert a1c is not None, "a1c must appear for DM patient"
    assert a1c["status"] == "overdue", (
        f"Expected overdue (HbA1c 8m ago, interval 6m), got {a1c['status']}"
    )
    assert a1c["next_due_at"] is not None
    assert a1c["last_done_at"] is not None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_due_soon_status(seed_screening_data):
    """HbA1c done ~5m15d ago (interval=6) → a1c item status='due_soon'."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["soon_link"]
    items = screening_timeline(pid, tenant_id=1)
    a1c = next((i for i in items if i["item_key"] == "a1c"), None)
    assert a1c is not None, "a1c must appear for DM patient"
    assert a1c["status"] == "due_soon", (
        f"Expected due_soon (HbA1c ~5m15d ago, interval 6m, 30-day window), "
        f"got {a1c['status']}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_never_done(seed_screening_data):
    """DM patient with no HbA1c → a1c item status='never_done', next_due_at=None."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["never_link"]
    items = screening_timeline(pid, tenant_id=1)
    a1c = next((i for i in items if i["item_key"] == "a1c"), None)
    assert a1c is not None, "a1c must appear for DM patient with no readings"
    assert a1c["status"] == "never_done", (
        f"Expected never_done (no HbA1c recorded), got {a1c['status']}"
    )
    assert a1c["last_done_at"] is None
    assert a1c["next_due_at"] is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_no_every_visit_items(seed_screening_data):
    """Items with interval_months==0 (every-visit) must not appear."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["never_link"]
    items = screening_timeline(pid, tenant_id=1)
    zero_interval = [i for i in items if i.get("interval_months") == 0]
    assert zero_interval == [], (
        f"Every-visit items (interval=0) must be excluded from timeline: {zero_interval}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_no_vaccine_items(seed_screening_data):
    """Items with interval_months==None (vaccine/one-time) must not appear."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["never_link"]
    items = screening_timeline(pid, tenant_id=1)
    none_interval = [i for i in items if i.get("interval_months") is None]
    assert none_interval == [], (
        f"One-time/vaccine items must be excluded: {none_interval}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_condition_filter(seed_screening_data):
    """HTN-only patient: renal should appear (DM∪HTN∪CKD), eye/foot should NOT (DM only)."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["htn_link"]
    items = screening_timeline(pid, tenant_id=1)
    item_keys = {i["item_key"] for i in items}
    assert "renal" in item_keys, (
        f"renal must appear for HTN patient (ITEM_CONDITIONS includes HTN). "
        f"Got: {item_keys}"
    )
    assert "eye" not in item_keys, (
        f"eye must NOT appear for HTN-only patient (DM-only condition). "
        f"Got: {item_keys}"
    )
    assert "foot" not in item_keys, (
        f"foot must NOT appear for HTN-only patient (DM-only condition). "
        f"Got: {item_keys}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_dedup_by_item_key(seed_screening_data):
    """Each item_key appears at most once."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["never_link"]
    items = screening_timeline(pid, tenant_id=1)
    keys = [i["item_key"] for i in items]
    assert len(keys) == len(set(keys)), (
        f"Duplicate item_key found: {keys}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_sort_order(seed_screening_data):
    """never_done items come before overdue before due_soon before ok."""
    from clinical.followup_engine import screening_timeline, _STATUS_RANK
    pid = seed_screening_data["never_link"]  # DM: has never_done + other statuses
    items = screening_timeline(pid, tenant_id=1)
    ranks = [_STATUS_RANK.get(i["status"], 99) for i in items]
    assert ranks == sorted(ranks), (
        f"Items must be sorted by status rank. Got statuses: "
        f"{[i['status'] for i in items]}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_all_fields_present(seed_screening_data):
    """Every item dict must contain all required fields."""
    from clinical.followup_engine import screening_timeline
    pid = seed_screening_data["never_link"]
    items = screening_timeline(pid, tenant_id=1)
    required = {"item_key", "label_fa", "last_done_at", "next_due_at",
                "status", "interval_months", "condition_code", "suggestion_only"}
    for item in items:
        missing = required - set(item.keys())
        assert not missing, (
            f"Missing fields {missing} in item: {item}"
        )
        assert item["suggestion_only"] is True, (
            f"suggestion_only must be True: {item}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# API-level: GET /patients/{uuid}/screening-timeline
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_screening_timeline_200(seed_screening_data):
    """GET /screening-timeline returns 200 with correct top-level structure."""
    token = _get_token(seed_screening_data)
    uuid_str = str(seed_screening_data["scr_dm_never_uuid"])
    resp = _ninja_client().get(
        f"/patients/{uuid_str}/screening-timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "patient_link_id" in data, "patient_link_id must be in response"
    assert "framing" in data, "framing must be in response"
    assert "items" in data, "items must be in response"
    assert data["framing"] == "یادآوریِ غربالگری — تأیید با پزشک"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_screening_timeline_all_dto_fields_serialized(seed_screening_data):
    """
    CRITICAL: every ScreeningItemDTO field must appear in the serialized response.

    Guards against the regression seen in steps 34/36 where DTO fields were
    declared but not serialized into the JSON output.
    """
    token = _get_token(seed_screening_data)
    uuid_str = str(seed_screening_data["scr_dm_never_uuid"])
    resp = _ninja_client().get(
        f"/patients/{uuid_str}/screening-timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"], "DM patient must have at least one item"

    required_fields = {
        "item_key", "label_fa", "last_done_at", "next_due_at",
        "status", "interval_months", "condition_code", "suggestion_only",
    }
    for item in data["items"]:
        missing = required_fields - set(item.keys())
        assert not missing, (
            f"Serialized item missing fields {missing}: {item}"
        )
        # suggestion_only is safety-critical — must always be True
        assert item["suggestion_only"] is True, (
            f"suggestion_only must serialize as True, not {item['suggestion_only']}: {item}"
        )
        # status must be one of the valid values
        assert item["status"] in ("never_done", "overdue", "due_soon", "ok"), (
            f"Invalid status {item['status']!r}: {item}"
        )
        # interval_months must be a positive int
        assert isinstance(item["interval_months"], int) and item["interval_months"] > 0, (
            f"interval_months must be a positive int: {item}"
        )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_screening_timeline_a1c_overdue(seed_screening_data):
    """Overdue DM patient: a1c item in response with status=overdue and next_due_at set."""
    token = _get_token(seed_screening_data)
    uuid_str = str(seed_screening_data["scr_dm_over_uuid"])
    resp = _ninja_client().get(
        f"/patients/{uuid_str}/screening-timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    a1c = next((i for i in items if i["item_key"] == "a1c"), None)
    assert a1c is not None, f"a1c not found in items: {items}"
    assert a1c["status"] == "overdue", f"Expected overdue, got {a1c['status']}"
    assert a1c["next_due_at"] is not None, "next_due_at must be set for overdue item"
    assert a1c["last_done_at"] is not None, "last_done_at must be set"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_screening_timeline_never_done_no_next_due(seed_screening_data):
    """DM patient with no HbA1c: a1c item has status=never_done, next_due_at=null."""
    token = _get_token(seed_screening_data)
    uuid_str = str(seed_screening_data["scr_dm_never_uuid"])
    resp = _ninja_client().get(
        f"/patients/{uuid_str}/screening-timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    a1c = next((i for i in items if i["item_key"] == "a1c"), None)
    assert a1c is not None
    assert a1c["status"] == "never_done"
    assert a1c["last_done_at"] is None
    assert a1c["next_due_at"] is None


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_screening_timeline_no_followup_tasks_created(seed_screening_data):
    """Calling the endpoint must not create any followup_tasks (read-only guard)."""
    from clinical.models import FollowupTask
    token = _get_token(seed_screening_data)
    uuid_str = str(seed_screening_data["scr_dm_never_uuid"])
    pid = seed_screening_data["never_link"]

    before_count = FollowupTask.objects.filter(
        tenant_id=1, patient_link_id=pid
    ).count()

    resp = _ninja_client().get(
        f"/patients/{uuid_str}/screening-timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    after_count = FollowupTask.objects.filter(
        tenant_id=1, patient_link_id=pid
    ).count()
    assert after_count == before_count, (
        f"screening-timeline must be read-only: followup_tasks grew from "
        f"{before_count} to {after_count}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_screening_timeline_404_unknown_patient(seed_screening_data):
    """Unknown patient uuid → 404."""
    token = _get_token(seed_screening_data)
    fake_uuid = "00000000-0000-0000-0000-000000000099"
    resp = _ninja_client().get(
        f"/patients/{fake_uuid}/screening-timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_screening_timeline_401_no_auth(seed_screening_data):
    """No JWT → 401."""
    uuid_str = str(seed_screening_data["scr_dm_never_uuid"])
    resp = _ninja_client().get(f"/patients/{uuid_str}/screening-timeline")
    assert resp.status_code == 401


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_api_screening_timeline_htn_condition_filter(seed_screening_data):
    """HTN-only patient: renal in items, eye/foot not in items."""
    token = _get_token(seed_screening_data)
    uuid_str = str(seed_screening_data["scr_htn_uuid"])
    resp = _ninja_client().get(
        f"/patients/{uuid_str}/screening-timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    item_keys = {i["item_key"] for i in resp.json()["items"]}
    assert "renal" in item_keys, f"renal must appear for HTN. Got: {item_keys}"
    assert "eye" not in item_keys, f"eye must not appear for HTN. Got: {item_keys}"
    assert "foot" not in item_keys, f"foot must not appear for HTN. Got: {item_keys}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_screening_timeline_no_duplicate_kidney_row(seed_screening_data):
    """
    `renal` (egfr+uacr) and `renal_function` (egfr) both resolve to the same
    eGFR label — the timeline must show ONE kidney item, not two identical rows
    (GP: no confusing duplicates). Guards the renal_function exclusion.
    """
    from clinical.followup_engine import screening_timeline

    pid = seed_screening_data["never_link"]  # diabetic → kidney screening applies
    items = screening_timeline(pid, tenant_id=1)

    item_keys = [i["item_key"] for i in items]
    assert "renal_function" not in item_keys, (
        f"renal_function is redundant with renal and must be excluded. Got: {item_keys}"
    )
    assert "renal" in item_keys, f"the kidney item (renal) must appear. Got: {item_keys}"

    # No two rows may share the same Persian label (would read as a duplicate).
    labels = [i["label_fa"] for i in items]
    assert len(labels) == len(set(labels)), (
        f"every timeline row must be a distinct screening (no duplicate labels). "
        f"Got: {labels}"
    )
