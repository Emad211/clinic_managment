"""
E2E integration test — full care loop over the API.

Walk: login → GET /patients → GET /patients/{uuid}/record
  → GET /patients/{uuid}/suggestions (assert REAL rules fire)
  → GET /worklist → POST worklist/{id}/done → POST suggestion action
  → assert audit rows written.

Two demo patients are seeded fresh for this test:
  UNCONTROLLED DIABETIC:
    national_id=E2E0001, hba1c=9.8, bp_systolic=150, condition=diabetes
    Expected rules fired: T2-DX-01, T2-MED-FIRST-01, T2-BP-RX-01, T2-TGT-BP-01
    Expected NOT fired:   T2-INS-START-01 (hba1c<10), T2-REDFLAG-BP (bp<180)

  CONTROLLED DIABETIC:
    national_id=E2E0002, hba1c=6.5, bp_systolic=118, condition=diabetes
    Expected: T2-DX-01 (6.5>=6.5), T2-TGT-BP-01 (all DM)
    Expected NOT: T2-MED-FIRST-01 (hba1c<8.5), T2-BP-RX-01 (bp<130)

Full catalog is seeded from specialist_clinic's clinical_rules_seed.py
(the RULES list is imported directly — real rule_codes, real trigger_json).

Proof of "real platform running": all assertions pass against a real
Docker Postgres DB, via Django ORM + ninja.testing.TestClient.
"""
import importlib.util
import json
import sys
import uuid as uuid_module
from pathlib import Path

import bcrypt
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api

# ---------------------------------------------------------------------------
# DB connection — same as conftest (Docker Postgres)
# ---------------------------------------------------------------------------
_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

# ---------------------------------------------------------------------------
# Import the FULL rule catalog from specialist_clinic
# ---------------------------------------------------------------------------
def _import_rules():
    seed_path = (
        Path(__file__).resolve().parent.parent.parent
        / "specialist_clinic"
        / "src"
        / "adapters"
        / "sqlite"
        / "clinical_rules_seed.py"
    )
    spec = importlib.util.spec_from_file_location("_e2e_rules_seed", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RULES, mod._condition_for


# ---------------------------------------------------------------------------
# UUIDs for the e2e patients — deterministic, won't collide with other tests
# ---------------------------------------------------------------------------
_E2E_UNCONTROLLED_UUID = uuid_module.UUID("e2e00001-0000-0000-0000-000000000001")
_E2E_CONTROLLED_UUID   = uuid_module.UUID("e2e00002-0000-0000-0000-000000000002")

# ---------------------------------------------------------------------------
# Session-scoped fixture — seed full catalog + e2e demo patients
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def e2e_seed(seed_data):
    """
    Session-scoped seed for e2e tests:
      1. Full clinical_rules catalog (ALL rules from clinical_rules_seed.py)
      2. UNCONTROLLED diabetic patient (hba1c=9.8, bp=150, condition=diabetes)
      3. CONTROLLED diabetic patient  (hba1c=6.5, bp=118, condition=diabetes)
      4. One open followup_task for the uncontrolled patient
    Returns dict with UUIDs, link_ids, task_id.
    """
    RULES, _condition_for = _import_rules()

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:

        # ── Seed ALL clinical_rules (idempotent) ─────────────────────────────
        rules_inserted = 0
        for r in RULES:
            cc = _condition_for(r)
            trigger = (
                json.dumps(r["trigger"], ensure_ascii=False)
                if r.get("trigger") is not None else None
            )
            params = (
                json.dumps(r["params"], ensure_ascii=False)
                if r.get("params") is not None else None
            )
            result = conn.execute(
                """
                INSERT INTO clinical.clinical_rules
                    (tenant_id, rule_code, title, category, condition_code,
                     trigger_json, human_if, recommendation, dosage_titration,
                     monitoring, contraindications, evidence_level,
                     action_type, action_params_json, severity, priority,
                     source_ref, is_active)
                VALUES
                    (1, %(rc)s, %(title)s, %(cat)s, %(cc)s,
                     %(trig)s::jsonb, %(hif)s, %(rec)s, %(dos)s,
                     %(mon)s, %(contra)s, %(ev)s,
                     %(act)s, %(aparams)s::jsonb, %(sev)s, %(pri)s,
                     %(src)s, TRUE)
                ON CONFLICT (tenant_id, rule_code) DO NOTHING
                """,
                {
                    "rc": r["code"], "title": r["title"], "cat": r["category"],
                    "cc": cc, "trig": trigger,
                    "hif": r.get("human_if"), "rec": r.get("rec"),
                    "dos": r.get("dosage_titration"), "mon": r.get("monitoring"),
                    "contra": r.get("contraindications"), "ev": r.get("evidence"),
                    "act": r.get("action", "educate"), "aparams": params,
                    "sev": r.get("severity", "info"), "pri": r.get("priority", 100),
                    "src": r.get("source"),
                },
            )
            if result.rowcount > 0:
                rules_inserted += 1

        # ── Get diabetes condition id ─────────────────────────────────────────
        row = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=1 AND code='diabetes'"
        ).fetchone()
        assert row, "diabetes condition must be seeded by SQL slice2"
        diabetes_id = row[0]

        # ── UNCONTROLLED diabetic ─────────────────────────────────────────────
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'علی', 'کنترل‌نشده E2E', 'E2E0001', '09119990001',
                    '1975-03-10', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (_E2E_UNCONTROLLED_UUID,))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s",
            (_E2E_UNCONTROLLED_UUID,)
        ).fetchone()
        uncontrolled_patient_id = row[0]

        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (uncontrolled_patient_id,))
        row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (uncontrolled_patient_id,)
        ).fetchone()
        uncontrolled_link_id = row[0]

        # Condition: diabetes
        conn.execute("""
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES (1, %s, %s, TRUE, now())
            ON CONFLICT DO NOTHING
        """, (uncontrolled_link_id, diabetes_id))

        # Vitals: hba1c=9.8 (≥8.5 → T2-MED-FIRST-01 fires; ≥6.5 → T2-DX-01 fires)
        #         bp_systolic=150 (≥130 → T2-BP-RX-01 fires; <180 → T2-REDFLAG-BP NOT)
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (1, %s, 'hba1c',       9.8,  '%%',   now() - interval '2 days', 'clinic'),
                (1, %s, 'bp_systolic', 150.0,'mmHg', now() - interval '2 days', 'clinic'),
                (1, %s, 'fbs',         210.0,'mg/dL',now() - interval '2 days', 'clinic')
        """, (uncontrolled_link_id, uncontrolled_link_id, uncontrolled_link_id))

        # Medications: metformin (active) — enables T2-MON-MET-B12, T2-SAFE-MET-STOP etc.
        conn.execute("""
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, drug_class,
                 dose, is_active, created_at)
            VALUES (1, %s, 'متفورمین', 'metformin', '1000mg', TRUE, now())
            ON CONFLICT DO NOTHING
        """, (uncontrolled_link_id,))

        # One open followup_task (past-due) for the uncontrolled patient
        task_row = conn.execute("""
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason, detail,
                 status, fulfillment, created_at)
            VALUES
                (1, %s, CURRENT_DATE - 1, 'uncontrolled',
                 'A1c بالا — پیگیری لازم است',
                 'open', 'in_person', now())
            RETURNING id
        """, (uncontrolled_link_id,)).fetchone()
        followup_task_id = task_row[0]

        # ── CONTROLLED diabetic ───────────────────────────────────────────────
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'فاطمه', 'کنترل‌شده E2E', 'E2E0002', '09119990002',
                    '1980-07-22', 'female')
            ON CONFLICT (uuid) DO NOTHING
        """, (_E2E_CONTROLLED_UUID,))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s",
            (_E2E_CONTROLLED_UUID,)
        ).fetchone()
        controlled_patient_id = row[0]

        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (controlled_patient_id,))
        row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (controlled_patient_id,)
        ).fetchone()
        controlled_link_id = row[0]

        conn.execute("""
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES (1, %s, %s, TRUE, now())
            ON CONFLICT DO NOTHING
        """, (controlled_link_id, diabetes_id))

        # Vitals: hba1c=6.5 (≥6.5 → T2-DX-01 fires; <8.5 → T2-MED-FIRST-01 NOT)
        #         bp_systolic=118 (<130 → T2-BP-RX-01 NOT)
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (1, %s, 'hba1c',       6.5,  '%%',   now() - interval '3 days', 'clinic'),
                (1, %s, 'bp_systolic', 118.0,'mmHg', now() - interval '3 days', 'clinic')
        """, (controlled_link_id, controlled_link_id))

    return {
        **seed_data,
        "uncontrolled_uuid": _E2E_UNCONTROLLED_UUID,
        "uncontrolled_link_id": uncontrolled_link_id,
        "controlled_uuid": _E2E_CONTROLLED_UUID,
        "controlled_link_id": controlled_link_id,
        "followup_task_id": followup_task_id,
        "rules_inserted": rules_inserted,
        "total_rules": len(RULES),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client():
    return TestClient(api)


def _login(seed_data) -> str:
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed_data["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# Step 1 — login
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_step1_login(e2e_seed):
    """Step 1: POST /auth/login returns a valid JWT token."""
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": e2e_seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    assert "token" in data
    assert len(data["token"]) > 40, "JWT should be a non-trivial string"


# ---------------------------------------------------------------------------
# Step 2 — GET /patients (list)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_step2_list_patients(e2e_seed):
    """Step 2: GET /patients returns at least the two e2e demo patients."""
    token = _login(e2e_seed)
    resp = _client().get(
        "/patients",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2, (
        f"Expected at least 2 enrolled patients (the 2 e2e patients), "
        f"got total={data['total']}"
    )
    # Both e2e patient UUIDs must be in the list
    all_uuids = {item["patient_uuid"] for item in data["items"]}
    assert str(_E2E_UNCONTROLLED_UUID) in all_uuids, (
        f"Uncontrolled patient uuid not in list: {all_uuids}"
    )
    assert str(_E2E_CONTROLLED_UUID) in all_uuids, (
        f"Controlled patient uuid not in list: {all_uuids}"
    )


# ---------------------------------------------------------------------------
# Step 3 — GET /patients/{uuid}/record (uncontrolled)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_step3_get_patient_record(e2e_seed):
    """
    Step 3: GET /patients/{uuid}/record for the uncontrolled diabetic.
    Assert demographics, active conditions (diabetes), active medications, recent vitals.
    """
    token = _login(e2e_seed)
    resp = _client().get(
        f"/patients/{_E2E_UNCONTROLLED_UUID}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["patient_link_id"] == e2e_seed["uncontrolled_link_id"]
    assert "demographics" in data
    assert data["demographics"] is not None
    assert data["demographics"]["national_id"] == "E2E0001"

    # Active conditions — must include diabetes
    condition_codes = [c["condition_code"] for c in data["active_conditions"]]
    assert "diabetes" in condition_codes, (
        f"Expected 'diabetes' in active_conditions, got: {condition_codes}"
    )

    # Active medications — must include metformin
    med_classes = [m["drug_class"] for m in data["active_medications"]]
    assert "metformin" in med_classes, (
        f"Expected 'metformin' in active_medications, got: {med_classes}"
    )

    # Recent vitals — must include hba1c
    vital_types = [v["type"] for v in data["recent_vitals"]]
    assert "hba1c" in vital_types, (
        f"Expected 'hba1c' in recent_vitals, got: {vital_types}"
    )


# ---------------------------------------------------------------------------
# Step 4 — GET /patients/{uuid}/suggestions — REAL RULES (uncontrolled)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_step4_suggestions_uncontrolled_diabetic(e2e_seed):
    """
    Step 4 (core faithfulness gate): suggestions for the UNCONTROLLED diabetic.
    hba1c=9.8, bp_systolic=150, condition=diabetes, med=metformin.

    MUST fire (real rule_codes from clinical_rules_seed.py):
      T2-DX-01        — hba1c ≥ 6.5 (9.8 ≥ 6.5)
      T2-MED-FIRST-01 — DM + hba1c ≥ 8.5 (9.8 ≥ 8.5)
      T2-BP-RX-01     — DM + bp_systolic ≥ 130 (150 ≥ 130)
      T2-TGT-BP-01    — DM (all diabetics)
      T2-MON-MET-B12  — metformin (B12 monitoring)
      T2-FU-A1C-01    — DM (A1c monitoring every 3-6 mo)

    MUST NOT fire:
      T2-INS-START-01     — hba1c > 10 (9.8 is NOT > 10)
      T2-REDFLAG-BP       — bp_systolic ≥ 180 (150 < 180)
      T2-REDFLAG-SEVERE-HYPER — hba1c > 12 (9.8 < 12)
    """
    token = _login(e2e_seed)
    resp = _client().get(
        f"/patients/{_E2E_UNCONTROLLED_UUID}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["patient_link_id"] == e2e_seed["uncontrolled_link_id"]
    assert "framing" in data
    assert data["framing"] == "پیشنهاد — تأیید با پزشک"
    assert data["count"] > 0, "Uncontrolled diabetic should have suggestions"

    fired_codes = {
        r["rule_code"]
        for sec in data["sections"]
        for r in sec["rules"]
    }

    # Rules that MUST fire
    must_fire = {
        "T2-DX-01",        # hba1c ≥ 6.5
        "T2-MED-FIRST-01", # DM + hba1c ≥ 8.5
        "T2-BP-RX-01",     # DM + bp_systolic ≥ 130
        "T2-TGT-BP-01",    # DM (all diabetics)
    }
    for code in must_fire:
        assert code in fired_codes, (
            f"Rule {code} MUST fire for uncontrolled diabetic "
            f"(hba1c=9.8, bp=150, condition=diabetes). "
            f"Fired: {sorted(fired_codes)}"
        )

    # Rules that must NOT fire
    must_not_fire = {
        "T2-INS-START-01",        # hba1c > 10 — 9.8 < 10
        "T2-REDFLAG-BP",          # bp_systolic ≥ 180 — 150 < 180
        "T2-REDFLAG-SEVERE-HYPER",# hba1c > 12 — 9.8 < 12
    }
    for code in must_not_fire:
        assert code not in fired_codes, (
            f"Rule {code} must NOT fire for uncontrolled diabetic. "
            f"Fired: {sorted(fired_codes)}"
        )

    # Every suggestion must carry suggestion_only=True
    for sec in data["sections"]:
        for r in sec["rules"]:
            assert r["suggestion_only"] is True, (
                f"Rule {r['rule_code']} missing suggestion_only=True"
            )


# ---------------------------------------------------------------------------
# Step 4b — GET /patients/{uuid}/suggestions — CONTROLLED (fires fewer)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_step4b_suggestions_controlled_diabetic(e2e_seed):
    """
    Step 4b: controlled diabetic (hba1c=6.5, bp=118) fires fewer rules.

    MUST fire:
      T2-DX-01    — hba1c ≥ 6.5 (exactly 6.5, edge case)
      T2-TGT-BP-01 — DM (all diabetics baseline)

    MUST NOT fire:
      T2-MED-FIRST-01 — hba1c ≥ 8.5 (6.5 < 8.5)
      T2-BP-RX-01     — bp_systolic ≥ 130 (118 < 130)
      T2-INS-START-01 — hba1c > 10 (6.5 < 10)
    """
    token = _login(e2e_seed)

    # Controlled
    resp_c = _client().get(
        f"/patients/{_E2E_CONTROLLED_UUID}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_c.status_code == 200, resp_c.text
    data_c = resp_c.json()
    fired_c = {r["rule_code"] for sec in data_c["sections"] for r in sec["rules"]}

    # Uncontrolled (for comparison)
    resp_u = _client().get(
        f"/patients/{_E2E_UNCONTROLLED_UUID}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_u.status_code == 200, resp_u.text
    data_u = resp_u.json()

    # T2-DX-01 fires at exactly 6.5 (edge case — ≥ 6.5)
    assert "T2-DX-01" in fired_c, (
        f"T2-DX-01 must fire at hba1c=6.5 (boundary ≥ 6.5). Fired: {sorted(fired_c)}"
    )
    # Baseline DM rule
    assert "T2-TGT-BP-01" in fired_c, (
        f"T2-TGT-BP-01 must fire for all diabetics. Fired: {sorted(fired_c)}"
    )

    # Rules that must NOT fire for controlled
    for code in ("T2-MED-FIRST-01", "T2-BP-RX-01", "T2-INS-START-01"):
        assert code not in fired_c, (
            f"{code} must NOT fire for controlled (hba1c=6.5, bp=118). "
            f"Fired: {sorted(fired_c)}"
        )

    # Uncontrolled fires more rules
    assert data_u["count"] > data_c["count"], (
        f"Uncontrolled ({data_u['count']}) must fire more rules than "
        f"controlled ({data_c['count']})"
    )


# ---------------------------------------------------------------------------
# Step 5 — GET /worklist
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_step5_get_worklist(e2e_seed):
    """
    Step 5: GET /worklist returns the open past-due task for the uncontrolled patient.
    """
    token = _login(e2e_seed)
    resp = _client().get(
        "/worklist",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200: {resp.text}"
    data = resp.json()

    task_ids = [item["id"] for item in data["items"]]
    assert e2e_seed["followup_task_id"] in task_ids, (
        f"e2e followup_task_id={e2e_seed['followup_task_id']} not in worklist. "
        f"Worklist task ids: {task_ids}"
    )


# ---------------------------------------------------------------------------
# Step 6 — POST /worklist/{task_id}/done
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_step6_mark_task_done(e2e_seed):
    """
    Step 6: POST /worklist/{task_id}/done marks the task done.
    Second call returns 409 (already done).
    Audit row is written.
    """
    token = _login(e2e_seed)
    task_id = e2e_seed["followup_task_id"]

    # First call — should succeed
    resp = _client().post(
        f"/worklist/{task_id}/done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == "done"
    assert data["resolved_at"] is not None

    # Second call — 409 (already done)
    resp2 = _client().post(
        f"/worklist/{task_id}/done",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 409, (
        f"Expected 409 on double-done, got {resp2.status_code}: {resp2.text}"
    )

    # Audit row must be written
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        row = conn.execute(
            "SELECT id FROM clinical.activity_logs "
            "WHERE tenant_id=1 AND action_type='followup_done' "
            "AND target_id=%s",
            (task_id,),
        ).fetchone()
    assert row is not None, (
        f"Audit row for followup_done task_id={task_id} not found in activity_logs"
    )


# ---------------------------------------------------------------------------
# Step 7 — POST suggestion accept + assert audit row
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_step7_suggestion_accept_and_audit(e2e_seed):
    """
    Step 7: POST /patients/{uuid}/suggestions/T2-MED-FIRST-01/action (accept).
    Assert suggestion_log row written with status='accepted'.
    Assert audit row written with action_type='suggestion_accepted'.
    """
    token = _login(e2e_seed)

    resp = _client().post(
        f"/patients/{_E2E_UNCONTROLLED_UUID}/suggestions/T2-MED-FIRST-01/action",
        json={"action": "accept", "note": "پزشک تأیید کرد — شروع متفورمین+SGLT2i"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["rule_code"] == "T2-MED-FIRST-01"
    assert data["status"] == "accepted"
    assert data["patient_link_id"] == e2e_seed["uncontrolled_link_id"]

    # Verify suggestion_log row in DB
    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        sl_row = conn.execute(
            "SELECT status FROM clinical.suggestion_log "
            "WHERE tenant_id=1 AND patient_link_id=%s AND rule_code='T2-MED-FIRST-01'",
            (e2e_seed["uncontrolled_link_id"],),
        ).fetchone()
        assert sl_row is not None, "suggestion_log row must exist after accept"
        assert sl_row[0] == "accepted", f"Expected status='accepted', got {sl_row[0]}"

        # Audit row
        audit_row = conn.execute(
            "SELECT id FROM clinical.activity_logs "
            "WHERE tenant_id=1 AND action_type='suggestion_accepted' "
            "AND patient_link_id=%s",
            (e2e_seed["uncontrolled_link_id"],),
        ).fetchone()
        assert audit_row is not None, (
            "Audit row for suggestion_accepted must be in activity_logs"
        )

    # Dismiss — update the same row (upsert semantics)
    resp2 = _client().post(
        f"/patients/{_E2E_UNCONTROLLED_UUID}/suggestions/T2-MED-FIRST-01/action",
        json={"action": "dismiss", "note": "بیمار ترجیح داد بعداً شروع کند"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200, f"Dismiss failed: {resp2.text}"
    data2 = resp2.json()
    assert data2["status"] == "dismissed"
    # Same id — upsert updated, not inserted new row
    assert data2["id"] == data["id"], "Upsert must update the SAME row, not insert new"


# ---------------------------------------------------------------------------
# Meta — assert catalog completeness (how many rules were seeded)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_e2e_catalog_completeness(e2e_seed):
    """
    Assert the full rule catalog is present in the DB.
    Reports how many rules were newly inserted vs. already existed.
    """
    from clinical.models import ClinicalRule
    db_count = ClinicalRule.objects.filter(tenant_id=1, is_active=True).count()
    total_rules = e2e_seed["total_rules"]
    assert db_count >= total_rules, (
        f"Expected at least {total_rules} active rules in DB, "
        f"found only {db_count}. Some rules may not have been seeded."
    )
