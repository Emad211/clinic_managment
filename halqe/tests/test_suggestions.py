"""
Golden test for the clinical suggestion engine port.

FAITHFULNESS GATE: verifies the DSL evaluator fires/does-not-fire the expected
rule_codes for a seeded patient against the real clinical_rules catalog.

Two patients are seeded (both enrolled under tenant-1):

  UNCONTROLLED DIABETIC
    condition: diabetes
    hba1c = 9.0 %   (above target 7.0 and above 8.5 threshold)
    bp_systolic = 145 mmHg  (above 130 and above 140 thresholds)
    No flags set; no medications.
    Expected to fire:
      T2-DX-01       hba1c ≥ 6.5 → classify diabetes (trigger: indicator.hba1c.latest ≥ 6.5)
      T2-MED-FIRST-01 DM + hba1c ≥ 8.5 → start dual therapy (trigger: DM AND hba1c ≥ 8.5)
      T2-BP-RX-01    DM + bp_systolic ≥ 130 → start/intensify BP Rx (trigger: DM AND bp_systolic ≥ 130)
      T2-TGT-BP-01   DM → BP target (trigger: DM — fires for all diabetics)
    Expected NOT to fire:
      T2-INS-START-01  hba1c > 10 → NOT fire (9.0 < 10)
      T2-REDFLAG-BP    bp_systolic ≥ 180 → NOT fire (145 < 180)
      T2-REDFLAG-SEVERE-HYPER  hba1c > 12 → NOT fire

  CONTROLLED DIABETIC
    condition: diabetes
    hba1c = 6.4 %   (prediabetes range, below the 8.5/7.0 drug initiation thresholds)
    bp_systolic = 120 mmHg  (below 130)
    No flags set; no medications.
    Expected NOT to fire (compared to uncontrolled):
      T2-DX-01         hba1c ≥ 6.5 → NOT fire (6.4 < 6.5)
      T2-MED-FIRST-01  hba1c ≥ 8.5 → NOT fire (6.4 < 8.5)
      T2-BP-RX-01      bp_systolic ≥ 130 → NOT fire (120 < 130)
    Expected to fire (still diabetic, baseline rules):
      T2-DX-02         hba1c between [5.7, 6.4] → fires (prediabetes label)
      T2-TGT-BP-01     DM → always fires for diabetics

Additional tests:
  - Endpoint requires JWT (401 without token)
  - Tenant-scoped (404 for patient enrolled in another tenant)
  - Every suggestion carries suggestion_only=True
  - framing field is present in response

NOTE ON RULE CATALOG SEEDING:
  clinical_rules is NOT in the SQL slices (intentional — seeded from Python bootstrap
  in specialist_clinic). The conftest below seeds a REPRESENTATIVE SUBSET of the real
  rules directly into clinical.clinical_rules via psycopg (same column layout).
  The subset includes the exact rules asserted in this test, all with their real
  trigger_json from clinical_rules_seed.py. This is faithful: we do NOT invent
  trigger_json — we copy it verbatim from the source.
"""
import json
import uuid
import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api

# ── DB connection params (same as conftest) ───────────────────────────────────
_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

# ── Subset of real rules to seed (trigger_json verbatim from clinical_rules_seed.py) ──
# Only rules needed for the golden test assertions. Each dict matches the INSERT columns.
_RULE_SUBSET = [
    # T2-DX-01: hba1c ≥ 6.5 OR fbs ≥ 126
    {
        "rule_code": "T2-DX-01",
        "title": "تشخیص دیابت",
        "category": "diagnosis",
        "condition_code": "diabetes",
        "trigger_json": {"any": [
            {"var": "indicator.hba1c.latest", "op": ">=", "value": 6.5},
            {"var": "indicator.fbs.latest",   "op": ">=", "value": 126},
        ]},
        "human_if": "A1c ≥۶.۵٪ یا قند ناشتا ≥۱۲۶",
        "recommendation": "معیار تشخیص دیابت مثبت است.",
        "action_type": "classify",
        "action_params_json": {"label": "diabetes"},
        "severity": "warn",
        "priority": 10,
        "source_ref": "ADA 2.1a/2.1b",
    },
    # T2-DX-02: hba1c between 5.7–6.4 OR fbs between 100–125 (prediabetes)
    {
        "rule_code": "T2-DX-02",
        "title": "پیش‌دیابت",
        "category": "diagnosis",
        "condition_code": "diabetes",
        "trigger_json": {"any": [
            {"var": "indicator.hba1c.latest", "op": "between", "value": [5.7, 6.4]},
            {"var": "indicator.fbs.latest",   "op": "between", "value": [100, 125]},
        ]},
        "human_if": "A1c ۵.۷–۶.۴٪ یا قند ناشتا ۱۰۰–۱۲۵",
        "recommendation": "برچسب پیش‌دیابت؛ آموزش سبک‌زندگی و تستِ سالانه.",
        "action_type": "classify",
        "action_params_json": {"label": "prediabetes"},
        "severity": "info",
        "priority": 20,
        "source_ref": "ADA Table 2.2",
    },
    # T2-TGT-BP-01: DM only (all diabetics)
    {
        "rule_code": "T2-TGT-BP-01",
        "title": "هدف فشار خون",
        "category": "target",
        "condition_code": "diabetes",
        "trigger_json": {"all": [
            {"var": "condition", "op": "has", "value": "diabetes"},
        ]},
        "human_if": "دیابت نوع ۲ بزرگسال",
        "recommendation": "هدفِ فشار <۱۳۰/۸۰ mmHg.",
        "action_type": "set_target",
        "action_params_json": {"indicator": "bp_systolic", "target": 130},
        "severity": "info",
        "priority": 32,
        "source_ref": "ADA 10.4/11.5",
    },
    # T2-MED-FIRST-01: DM + hba1c ≥ 8.5
    {
        "rule_code": "T2-MED-FIRST-01",
        "title": "شروع درمان دارویی",
        "category": "medication",
        "condition_code": "diabetes",
        "trigger_json": {"all": [
            {"var": "condition", "op": "has", "value": "diabetes"},
            {"var": "indicator.hba1c.latest", "op": ">=", "value": 8.5},
        ]},
        "human_if": "A1c حدود ۱.۵–۲٪ بالاتر از هدف",
        "recommendation": "شروع بدون تأخیر؛ درمانِ ترکیبیِ اولیه را در نظر بگیرید.",
        "action_type": "suggest_med",
        "action_params_json": None,
        "severity": "warn",
        "priority": 40,
        "source_ref": "ADA 9.6",
    },
    # T2-BP-RX-01: DM + bp_systolic ≥ 130
    {
        "rule_code": "T2-BP-RX-01",
        "title": "درمان فشار خون",
        "category": "bp_rx",
        "condition_code": "diabetes",
        "trigger_json": {"all": [
            {"var": "condition", "op": "has", "value": "diabetes"},
            {"var": "indicator.bp_systolic.latest", "op": ">=", "value": 130},
        ]},
        "human_if": "فشار سیستول ≥۱۳۰",
        "recommendation": "شروع/تشدید ضدفشار.",
        "action_type": "suggest_med",
        "action_params_json": {"classes": ["acei", "arb"]},
        "severity": "warn",
        "priority": 60,
        "source_ref": "ADA 10.6",
    },
    # T2-INS-START-01: DM + hba1c > 10 (should NOT fire for hba1c=9.0)
    {
        "rule_code": "T2-INS-START-01",
        "title": "شروع انسولین",
        "category": "insulin",
        "condition_code": "diabetes",
        "trigger_json": {"all": [
            {"var": "condition", "op": "has", "value": "diabetes"},
            {"var": "indicator.hba1c.latest", "op": ">", "value": 10},
        ]},
        "human_if": "A1c >۱۰٪",
        "recommendation": "شروع انسولین را در نظر بگیرید.",
        "action_type": "suggest_med",
        "action_params_json": {"classes": ["insulin_basal"]},
        "severity": "warn",
        "priority": 80,
        "source_ref": "ADA 9.20",
    },
    # T2-REDFLAG-BP: bp_systolic ≥ 180 OR bp_diastolic ≥ 110 (cross-disease)
    {
        "rule_code": "T2-REDFLAG-BP",
        "title": "بحران فشار خون",
        "category": "redflag",
        "condition_code": "all",
        "trigger_json": {"any": [
            {"var": "indicator.bp_systolic.latest",  "op": ">=", "value": 180},
            {"var": "indicator.bp_diastolic.latest", "op": ">=", "value": 110},
        ]},
        "human_if": "فشار ≥۱۸۰/۱۱۰",
        "recommendation": "نیاز به اقدام سریع.",
        "action_type": "redflag",
        "action_params_json": None,
        "severity": "urgent",
        "priority": 1,
        "source_ref": "ADA 10",
    },
    # T2-REDFLAG-SEVERE-HYPER: fbs ≥ 300 OR hba1c > 12
    {
        "rule_code": "T2-REDFLAG-SEVERE-HYPER",
        "title": "هایپرگلیسمی شدید",
        "category": "redflag",
        "condition_code": "diabetes",
        "trigger_json": {"any": [
            {"var": "indicator.fbs.latest",   "op": ">=", "value": 300},
            {"var": "indicator.hba1c.latest", "op": ">",  "value": 12},
        ]},
        "human_if": "گلوکز ≥۳۰۰ یا A1c >۱۲٪",
        "recommendation": "ارزیابی برای DKA.",
        "action_type": "redflag",
        "action_params_json": None,
        "severity": "urgent",
        "priority": 2,
        "source_ref": "ADA 9.20",
    },
]


# ── Session-scoped seed fixture ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def seed_suggestions_data(seed_clinical_data):
    """
    Seed:
      1. clinical_rules subset (the representative rules needed for assertions)
      2. UNCONTROLLED diabetic patient (patient link + condition + vitals)
      3. CONTROLLED diabetic patient (patient link + condition + vitals)
    Returns dict with link_ids and patient uuids.

    Depends on seed_clinical_data (not just seed_data) so that tenant-2
    patient data (tenant2_patient_uuid) is available for isolation tests.
    """
    seed_data = seed_clinical_data
    uncontrolled_uuid = uuid.UUID("cccccccc-dddd-eeee-ffff-000000000001")
    controlled_uuid   = uuid.UUID("cccccccc-dddd-eeee-ffff-000000000002")

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:

        # ── Seed clinical_rules ──────────────────────────────────────────────
        for r in _RULE_SUBSET:
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

        # ── Get diabetes condition id ────────────────────────────────────────
        row = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=1 AND code='diabetes'"
        ).fetchone()
        assert row, "diabetes condition must be seeded by SQL slice"
        diabetes_id = row[0]

        # ── UNCONTROLLED patient ─────────────────────────────────────────────
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'محمد', 'کنترل‌نشده', '5555555551', '09110000051',
                    '1975-03-10', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (uncontrolled_uuid,))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s",
            (uncontrolled_uuid,)
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

        # Vitals: hba1c=9.0, bp_systolic=145
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (1, %s, 'hba1c',       9.0,  '%%',   now() - interval '1 day',  'clinic'),
                (1, %s, 'bp_systolic', 145.0,'mmHg', now() - interval '1 day',  'clinic')
        """, (uncontrolled_link_id, uncontrolled_link_id))

        # ── CONTROLLED patient ───────────────────────────────────────────────
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'فاطمه', 'کنترل‌شده', '5555555552', '09110000052',
                    '1980-07-22', 'female')
            ON CONFLICT (uuid) DO NOTHING
        """, (controlled_uuid,))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s",
            (controlled_uuid,)
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

        # Condition: diabetes
        conn.execute("""
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES (1, %s, %s, TRUE, now())
            ON CONFLICT DO NOTHING
        """, (controlled_link_id, diabetes_id))

        # Vitals: hba1c=6.4, bp_systolic=120
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (1, %s, 'hba1c',       6.4,  '%%',   now() - interval '1 day',  'clinic'),
                (1, %s, 'bp_systolic', 120.0,'mmHg', now() - interval '1 day',  'clinic')
        """, (controlled_link_id, controlled_link_id))

    return {
        **seed_data,
        "uncontrolled_uuid": uncontrolled_uuid,
        "uncontrolled_link_id": uncontrolled_link_id,
        "controlled_uuid": controlled_uuid,
        "controlled_link_id": controlled_link_id,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _client():
    return TestClient(api)


def _get_token(seed_data):
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed_data["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestions_requires_jwt(seed_suggestions_data):
    """GET /patients/{uuid}/suggestions without token → 401."""
    resp = _client().get(
        f"/patients/{seed_suggestions_data['uncontrolled_uuid']}/suggestions"
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestions_uncontrolled_diabetic_fires_expected_rules(seed_suggestions_data):
    """
    GOLDEN TEST — UNCONTROLLED DIABETIC.

    hba1c=9.0, bp_systolic=145, condition=diabetes.

    Expected FIRED rules:
      T2-DX-01       — hba1c ≥ 6.5 (trigger: indicator.hba1c.latest ≥ 6.5)
      T2-MED-FIRST-01 — DM + hba1c ≥ 8.5 (9.0 ≥ 8.5)
      T2-BP-RX-01    — DM + bp_systolic ≥ 130 (145 ≥ 130)
      T2-TGT-BP-01   — DM (baseline, fires for all diabetics)

    Expected NOT FIRED:
      T2-INS-START-01      — hba1c > 10 (9.0 is NOT > 10)
      T2-REDFLAG-BP        — bp_systolic ≥ 180 (145 < 180)
      T2-REDFLAG-SEVERE-HYPER — hba1c > 12 (9.0 < 12)
    """
    token = _get_token(seed_suggestions_data)
    uncontrolled_uuid = seed_suggestions_data["uncontrolled_uuid"]

    resp = _client().get(
        f"/patients/{uncontrolled_uuid}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    data = resp.json()

    # Collect all fired rule_codes (flattened from sections)
    fired_codes = {
        r["rule_code"]
        for sec in data["sections"]
        for r in sec["rules"]
    }

    # Rules that MUST fire
    must_fire = {"T2-DX-01", "T2-MED-FIRST-01", "T2-BP-RX-01", "T2-TGT-BP-01"}
    for code in must_fire:
        assert code in fired_codes, (
            f"Expected {code} to fire for uncontrolled diabetic "
            f"(hba1c=9.0, bp_sys=145, condition=diabetes). "
            f"Fired rules: {fired_codes}"
        )

    # Rules that must NOT fire
    must_not_fire = {"T2-INS-START-01", "T2-REDFLAG-BP", "T2-REDFLAG-SEVERE-HYPER"}
    for code in must_not_fire:
        assert code not in fired_codes, (
            f"Expected {code} NOT to fire for uncontrolled diabetic "
            f"(hba1c=9.0 is not >10; bp_sys=145 is not ≥180). "
            f"Fired rules: {fired_codes}"
        )

    # Structural assertions
    assert data["count"] > 0
    assert "framing" in data
    assert data["framing"] == "پیشنهاد — تأیید با پزشک"

    # All suggestions must be suggestion_only=True
    for sec in data["sections"]:
        for r in sec["rules"]:
            assert r["suggestion_only"] is True, (
                f"Rule {r['rule_code']} missing suggestion_only=True"
            )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestions_controlled_diabetic_fires_fewer_rules(seed_suggestions_data):
    """
    GOLDEN TEST — CONTROLLED DIABETIC.

    hba1c=6.4, bp_systolic=120, condition=diabetes.

    Expected FIRED:
      T2-DX-02       — hba1c between [5.7, 6.4] (prediabetes classification)
      T2-TGT-BP-01   — DM (baseline, fires for all diabetics)

    Expected NOT FIRED (because values are in range):
      T2-DX-01         — hba1c ≥ 6.5 (6.4 < 6.5 → NOT fire)
      T2-MED-FIRST-01  — hba1c ≥ 8.5 (6.4 < 8.5 → NOT fire)
      T2-BP-RX-01      — bp_systolic ≥ 130 (120 < 130 → NOT fire)
      T2-INS-START-01  — hba1c > 10 (6.4 < 10 → NOT fire)

    Also: uncontrolled patient fires MORE rules than controlled patient.
    """
    token = _get_token(seed_suggestions_data)

    # Controlled
    controlled_resp = _client().get(
        f"/patients/{seed_suggestions_data['controlled_uuid']}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert controlled_resp.status_code == 200, controlled_resp.text
    controlled_data = controlled_resp.json()
    controlled_codes = {
        r["rule_code"]
        for sec in controlled_data["sections"]
        for r in sec["rules"]
    }

    # Uncontrolled (for comparison)
    uncontrolled_resp = _client().get(
        f"/patients/{seed_suggestions_data['uncontrolled_uuid']}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert uncontrolled_resp.status_code == 200, uncontrolled_resp.text
    uncontrolled_data = uncontrolled_resp.json()

    # T2-DX-02 must fire for controlled (prediabetes range 5.7–6.4)
    assert "T2-DX-02" in controlled_codes, (
        f"T2-DX-02 must fire for hba1c=6.4 (between [5.7, 6.4]). "
        f"Controlled fired: {controlled_codes}"
    )

    # T2-TGT-BP-01 fires for all diabetics
    assert "T2-TGT-BP-01" in controlled_codes, (
        f"T2-TGT-BP-01 must fire for any diabetic. Controlled: {controlled_codes}"
    )

    # Rules that must NOT fire for controlled
    must_not_fire = {
        "T2-DX-01",         # hba1c < 6.5
        "T2-MED-FIRST-01",  # hba1c < 8.5
        "T2-BP-RX-01",      # bp_systolic < 130
        "T2-INS-START-01",  # hba1c < 10
    }
    for code in must_not_fire:
        assert code not in controlled_codes, (
            f"{code} must NOT fire for controlled diabetic "
            f"(hba1c=6.4, bp_sys=120). Fired: {controlled_codes}"
        )

    # Uncontrolled fires more rules than controlled
    assert uncontrolled_data["count"] > controlled_data["count"], (
        f"Uncontrolled ({uncontrolled_data['count']}) must fire more rules "
        f"than controlled ({controlled_data['count']})"
    )

    # suggestion_only=True on all controlled suggestions
    for sec in controlled_data["sections"]:
        for r in sec["rules"]:
            assert r["suggestion_only"] is True


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestions_tenant_scoped_404_for_other_tenant(seed_suggestions_data):
    """
    GET /patients/{uuid}/suggestions for a patient enrolled in tenant-2
    with a tenant-1 token → 404.
    """
    token = _get_token(seed_suggestions_data)
    tenant2_uuid = seed_suggestions_data["tenant2_patient_uuid"]
    resp = _client().get(
        f"/patients/{tenant2_uuid}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, (
        f"Expected 404 for cross-tenant suggestions access, "
        f"got {resp.status_code}: {resp.text}"
    )


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_suggestions_response_structure(seed_suggestions_data):
    """
    Response structure: patient_link_id, count, has_redflag, framing, sections.
    Each section has key, label, rules[]. Each rule has suggestion_only=True.
    """
    token = _get_token(seed_suggestions_data)
    resp = _client().get(
        f"/patients/{seed_suggestions_data['uncontrolled_uuid']}/suggestions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Top-level fields
    assert "patient_link_id" in data
    assert "count" in data
    assert "has_redflag" in data
    assert "framing" in data, "framing field must be present"
    assert data["framing"] == "پیشنهاد — تأیید با پزشک"
    assert "sections" in data
    assert isinstance(data["sections"], list)

    # Section structure
    for sec in data["sections"]:
        assert "key" in sec
        assert "label" in sec
        assert "rules" in sec
        for r in sec["rules"]:
            assert "rule_code" in r
            assert "suggestion_only" in r
            assert r["suggestion_only"] is True
            assert "severity" in r
            assert "section" in r
