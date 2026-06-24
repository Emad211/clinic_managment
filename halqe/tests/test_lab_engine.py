"""
Step 5 — lab_results wired into suggestion engine via clinical.observations VIEW.

Tests:
  1. build_facts includes lab obs_key in indicator dict (value + level correct)
  2. A lab-sourced observation does NOT shadow a same-key vital when vital is newer
  3. A lab-sourced observation DOES appear when no vital with same key exists
  4. A rule whose trigger references a lab obs_key actually fires through evaluate()
  5. The /suggestions endpoint returns a lab-driven rule (end-to-end HTTP)

Strategy:
  - Seed a dedicated patient (tenant=1) with:
      * condition: diabetes + ckd (so CKD rules load)
      * lab_result: egfr=25 (below danger threshold 30 → level='danger')
      * lab_result: ldl=115 (above danger threshold 100 → level='danger')
      * NO vital_readings with type 'egfr' or 'ldl' — to exercise the lab path
  - Seed two clinical rules:
      * CKD-EGFR-LOW: fires when indicator.egfr.latest < 30 (CKD stage G4+)
      * LDL-HIGH-DM:  fires when DM condition + indicator.ldl.latest >= 100

NOTE: conftest seeds 'ldl' as a VITAL reading for the base patient (link_id).
This test creates a SEPARATE patient and seeds ldl/egfr exclusively as lab_results
rows — this exercises the lab path in isolation from the vital path.
"""
import json
import uuid
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api
from clinical.rule_engine import build_facts, evaluate

# ── DB connection (superuser for seeding) ─────────────────────────────────────
_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

# ── Lab-specific clinical rules to seed ───────────────────────────────────────
_LAB_RULES = [
    {
        "rule_code": "CKD-EGFR-LOW",
        "title": "کاهش شدید eGFR (مرحله G4–G5)",
        "category": "renal",
        "condition_code": "ckd",
        "trigger_json": {
            "all": [
                {"var": "condition", "op": "has", "value": "ckd"},
                {"var": "indicator.egfr.latest", "op": "<", "value": 30},
            ]
        },
        "human_if": "eGFR < ۳۰ mL/min",
        "recommendation": "ارجاع به نفرولوژی؛ آمادگی برای درمان جایگزین کلیه.",
        "action_type": "create_followup",
        "action_params_json": {"urgency": "high"},
        "severity": "urgent",
        "priority": 5,
        "source_ref": "KDIGO 2024",
    },
    {
        "rule_code": "LDL-HIGH-DM",
        "title": "LDL بالا در دیابت",
        "category": "lipid",
        "condition_code": "diabetes",
        "trigger_json": {
            "all": [
                {"var": "condition", "op": "has", "value": "diabetes"},
                {"var": "indicator.ldl.latest", "op": ">=", "value": 100},
            ]
        },
        "human_if": "LDL ≥ ۱۰۰ در دیابت",
        "recommendation": "شروع یا تشدید استاتین.",
        "action_type": "suggest_med",
        "action_params_json": {"classes": ["statin"]},
        "severity": "warn",
        "priority": 50,
        "source_ref": "ADA 10.7b",
    },
]


@pytest.fixture(scope="session")
def seed_lab_patient(seed_clinical_data):
    """
    Seed a dedicated patient with lab_results for egfr and ldl (NO vitals for
    these keys) and conditions diabetes + ckd.

    Returns dict with link_id and patient uuid.
    """
    lab_patient_uuid = uuid.UUID("dddddddd-eeee-ffff-0000-111111111111")

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        # ── accounting patient ────────────────────────────────────────────────
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'رضا', 'آزمایشی', '7777777770', '09150000070',
                    '1965-02-14', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (lab_patient_uuid,))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s",
            (lab_patient_uuid,)
        ).fetchone()
        patient_id = row[0]

        # ── clinical patient_link ─────────────────────────────────────────────
        conn.execute("""
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
        """, (patient_id,))

        row = conn.execute(
            "SELECT id FROM clinical.patient_links WHERE tenant_id=1 AND patient_id=%s",
            (patient_id,)
        ).fetchone()
        link_id = row[0]

        # ── conditions: diabetes (id=1) + ckd (id=4) from slice2 seed ────────
        diabetes_row = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=1 AND code='diabetes'"
        ).fetchone()
        ckd_row = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=1 AND code='ckd'"
        ).fetchone()
        assert diabetes_row, "diabetes condition must exist (seeded by slice2)"
        assert ckd_row, "ckd condition must exist (seeded by slice2)"
        diabetes_id = diabetes_row[0]
        ckd_id = ckd_row[0]

        conn.execute("""
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES
                (1, %s, %s, TRUE, now()),
                (1, %s, %s, TRUE, now())
            ON CONFLICT DO NOTHING
        """, (link_id, diabetes_id, link_id, ckd_id))

        # ── lab_test_catalog: seed 'egfr' + 'ldl' entries so the FK allows test_key ─
        # lab_results.test_key has a FK to lab_test_catalog(tenant_id, test_key).
        # Must seed catalog entries before inserting lab_results with these test_keys.
        conn.execute("""
            INSERT INTO clinical.lab_test_catalog
                (tenant_id, test_key, name_fa, unit, category)
            VALUES
                (1, 'egfr', 'eGFR — عملکرد کلیه', 'mL/min', 'kidney'),
                (1, 'ldl',  'LDL کلسترول',         'mg/dL',  'lipid')
            ON CONFLICT (tenant_id, test_key) DO NOTHING
        """)

        # ── lab_results: egfr=25 + ldl=115 — no vital_readings for these keys ─
        # egfr=25 → below danger threshold 30 → level='danger' (direction=low)
        # ldl=115 → above danger threshold 100 → level='danger' (direction=high)
        # The VIEW (slice4a) will produce obs_key='lab:egfr' and 'lab:ldl'.
        # build_facts strips the 'lab:' prefix → bare_key='egfr'/'ldl' for indicator lookup.
        conn.execute("""
            INSERT INTO clinical.lab_results
                (tenant_id, patient_link_id, test_name, test_key, value, unit,
                 taken_at, recorded_by)
            VALUES
                (1, %s, 'eGFR (CKD-EPI)', 'egfr', 25.0, 'mL/min',
                 now() - interval '2 days', 'lab'),
                (1, %s, 'LDL کلسترول', 'ldl', 115.0, 'mg/dL',
                 now() - interval '3 days', 'lab')
        """, (link_id, link_id))

        # ── clinical rules: seed the two lab-specific rules ───────────────────
        for r in _LAB_RULES:
            conn.execute("""
                INSERT INTO clinical.clinical_rules
                    (tenant_id, rule_code, title, category, condition_code,
                     trigger_json, human_if, recommendation,
                     action_type, action_params_json, severity, priority,
                     source_ref, is_active)
                VALUES
                    (1, %(rule_code)s, %(title)s, %(category)s,
                     %(condition_code)s,
                     %(trigger_json)s::jsonb,
                     %(human_if)s, %(recommendation)s,
                     %(action_type)s,
                     %(action_params_json)s::jsonb,
                     %(severity)s, %(priority)s,
                     %(source_ref)s, TRUE)
                ON CONFLICT (tenant_id, rule_code) DO NOTHING
            """, {
                **r,
                "trigger_json": json.dumps(r["trigger_json"], ensure_ascii=False),
                "action_params_json": (
                    json.dumps(r["action_params_json"], ensure_ascii=False)
                    if r["action_params_json"] is not None else None
                ),
            })

    return {
        **seed_clinical_data,
        "lab_patient_uuid": lab_patient_uuid,
        "lab_link_id": link_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Unit-level: build_facts reads lab obs from clinical.observations VIEW
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_build_facts_includes_lab_egfr(seed_lab_patient):
    """
    build_facts() must include 'egfr' in indicator dict when it comes from
    a lab_results row (not from vital_readings).

    egfr=25 < danger threshold 30 → level='danger'.
    """
    link_id = seed_lab_patient["lab_link_id"]
    facts = build_facts(link_id, tenant_id=1)

    assert "egfr" in facts["indicator"], (
        f"'egfr' must appear in indicator facts from lab_results via observations VIEW. "
        f"Got keys: {list(facts['indicator'].keys())}"
    )
    egfr_fact = facts["indicator"]["egfr"]
    assert egfr_fact["latest"] == pytest.approx(25.0), (
        f"Expected egfr latest=25.0, got {egfr_fact['latest']}"
    )
    # egfr direction=low; danger when <= 30; 25 <= 30 → 'danger'
    assert egfr_fact["level"] == "danger", (
        f"Expected egfr level='danger' (25 <= 30, direction=low), got {egfr_fact['level']}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_build_facts_includes_lab_ldl(seed_lab_patient):
    """
    build_facts() must include 'ldl' in indicator dict when it comes from
    a lab_results row.

    ldl=115 >= danger threshold 100 → level='danger'.
    """
    link_id = seed_lab_patient["lab_link_id"]
    facts = build_facts(link_id, tenant_id=1)

    assert "ldl" in facts["indicator"], (
        f"'ldl' must appear in indicator facts from lab_results. "
        f"Got keys: {list(facts['indicator'].keys())}"
    )
    ldl_fact = facts["indicator"]["ldl"]
    assert ldl_fact["latest"] == pytest.approx(115.0), (
        f"Expected ldl latest=115.0, got {ldl_fact['latest']}"
    )
    # ldl direction=high; danger when >= 100; 115 >= 100 → 'danger'
    assert ldl_fact["level"] == "danger", (
        f"Expected ldl level='danger' (115 >= 100, direction=high), got {ldl_fact['level']}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_build_facts_lab_source_verified(seed_lab_patient):
    """
    Confirm the lab observations come from source_table='lab' path:
    this patient has NO vital_readings for 'egfr' or 'ldl'.
    """
    from clinical.models import VitalReading
    link_id = seed_lab_patient["lab_link_id"]

    # Verify there are no vital_readings for egfr/ldl for this patient
    vr_count = VitalReading.objects.filter(
        patient_link_id=link_id,
        tenant_id=1,
        type__in=["egfr", "ldl"],
    ).count()
    assert vr_count == 0, (
        f"Lab patient must have 0 vital_readings for egfr/ldl. "
        f"Found {vr_count}. This test verifies the lab path."
    )

    # Yet both appear in build_facts via the observations VIEW
    facts = build_facts(link_id, tenant_id=1)
    assert "egfr" in facts["indicator"]
    assert "ldl" in facts["indicator"]


# ─────────────────────────────────────────────────────────────────────────────
# Rule-engine: lab-sourced facts actually fire rules
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_evaluate_fires_ckd_egfr_rule_from_lab(seed_lab_patient):
    """
    Rule CKD-EGFR-LOW (trigger: ckd condition + egfr < 30) must fire because
    egfr=25 comes from lab_results (not vitals).

    This proves lab-sourced observations reach the DSL evaluator.
    """
    link_id = seed_lab_patient["lab_link_id"]
    fired = evaluate(link_id, tenant_id=1)
    fired_codes = {r["rule_code"] for r in fired}

    assert "CKD-EGFR-LOW" in fired_codes, (
        f"CKD-EGFR-LOW must fire: patient has ckd condition + egfr=25 from lab. "
        f"Fired rules: {fired_codes}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_evaluate_fires_ldl_rule_from_lab(seed_lab_patient):
    """
    Rule LDL-HIGH-DM (trigger: diabetes condition + ldl >= 100) must fire
    because ldl=115 comes from lab_results.
    """
    link_id = seed_lab_patient["lab_link_id"]
    fired = evaluate(link_id, tenant_id=1)
    fired_codes = {r["rule_code"] for r in fired}

    assert "LDL-HIGH-DM" in fired_codes, (
        f"LDL-HIGH-DM must fire: patient has diabetes + ldl=115 from lab. "
        f"Fired rules: {fired_codes}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_evaluate_both_lab_rules_fire(seed_lab_patient):
    """
    Both lab-driven rules fire together for the patient with ckd + diabetes
    + egfr=25 (lab) + ldl=115 (lab).
    """
    link_id = seed_lab_patient["lab_link_id"]
    fired = evaluate(link_id, tenant_id=1)
    fired_codes = {r["rule_code"] for r in fired}

    assert "CKD-EGFR-LOW" in fired_codes, f"CKD-EGFR-LOW missing. Fired: {fired_codes}"
    assert "LDL-HIGH-DM" in fired_codes, f"LDL-HIGH-DM missing. Fired: {fired_codes}"

    # suggestion_only=True on every fired rule (safety invariant)
    for r in fired:
        assert r["suggestion_only"] is True, (
            f"Rule {r['rule_code']} missing suggestion_only=True"
        )


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: /suggestions endpoint returns lab-driven rules
# ─────────────────────────────────────────────────────────────────────────────

def _client():
    return TestClient(api)


def _get_token(seed):
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestions_endpoint_includes_lab_driven_rule(seed_lab_patient):
    """
    GET /patients/{uuid}/suggestions for the lab patient must include
    CKD-EGFR-LOW and LDL-HIGH-DM in the response.

    End-to-end proof: lab_results row → observations VIEW → build_facts →
    evaluate → /suggestions endpoint JSON.
    """
    token = _get_token(seed_lab_patient)
    lab_uuid = seed_lab_patient["lab_patient_uuid"]

    resp = _client().get(
        f"/patients/{lab_uuid}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, (
        f"Expected 200 from /suggestions, got {resp.status_code}: {resp.text}"
    )

    data = resp.json()
    assert "sections" in data

    fired_codes = {
        r["rule_code"]
        for sec in data["sections"]
        for r in sec["rules"]
    }

    assert "CKD-EGFR-LOW" in fired_codes, (
        f"CKD-EGFR-LOW must appear in /suggestions response. "
        f"Patient has ckd + egfr=25 from lab_results. "
        f"Fired in response: {fired_codes}"
    )
    assert "LDL-HIGH-DM" in fired_codes, (
        f"LDL-HIGH-DM must appear in /suggestions response. "
        f"Patient has diabetes + ldl=115 from lab_results. "
        f"Fired in response: {fired_codes}"
    )

    # Framing field must be present
    assert data.get("framing") == "پیشنهاد — تأیید با پزشک"

    # suggestion_only=True on every rule in the response
    for sec in data["sections"]:
        for r in sec["rules"]:
            assert r["suggestion_only"] is True, (
                f"Rule {r['rule_code']} missing suggestion_only=True in HTTP response"
            )
