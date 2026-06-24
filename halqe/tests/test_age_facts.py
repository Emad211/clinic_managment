"""
Step 6 — age fact stabilization tests.

GOAL: prove that age-gated rules fire ONLY when demographics (birthdate) are
supplied, and that grouped_for_patient / resolve_demographics always provide
them — so no non-HTTP caller can silently disable age-gated rules by forgetting
to pass demographics.

Rule under test: T2-LIPID-RX-01
  trigger_json: DM condition AND age between [40, 75]
  Source: ADA 10.18/10.20 — statins for diabetics aged 40–75.

Two patients seeded:
  AGE-ELIGIBLE patient:
    birthdate='1975-01-01'  → age ~51 (inside 40–75)
    condition: diabetes
    hba1c vital so other DM rules can also fire (not strictly needed, but
    keeps the seed realistic)
    EXPECTED: T2-LIPID-RX-01 FIRES via grouped_for_patient
    EXPECTED: T2-LIPID-RX-01 does NOT fire via raw engine with demographics=None

  AGE-INELIGIBLE patient (conftest base patient):
    birthdate='1990-05-15'  → age ~36 (below 40)
    condition: diabetes (added by seed_clinical_data)
    EXPECTED: T2-LIPID-RX-01 does NOT fire (age < 40)

Tests:
  1. resolve_demographics returns a DTO with correct birthdate for the
     age-eligible patient.
  2. grouped_for_patient fires T2-LIPID-RX-01 for the age-eligible patient
     (age=51, inside 40–75).
  3. Raw rule_engine.grouped with demographics=None does NOT fire T2-LIPID-RX-01
     (fail-closed: age=None → age-gated rules skip).
  4. grouped_for_patient does NOT fire T2-LIPID-RX-01 for the age-ineligible
     patient (age=36, below 40) — proves the rule is age-discriminating.
  5. evaluate_for_patient fires T2-LIPID-RX-01 for age-eligible patient
     (functional equivalence with grouped_for_patient).

All 100 existing tests remain green (session-scoped seed fixtures compose cleanly).

IMPLEMENTATION NOTE FOR STEP 12:
  Auto worklist generation (Step 12) MUST call grouped_for_patient() or
  evaluate_for_patient() from clinical.suggestion_service, NOT
  rule_engine.grouped(patient_link_id) directly.  Calling the raw engine
  without demographics means age=None and all age-gated rules silently
  never fire — this test file documents and guards that invariant.
"""
import json
import uuid
import psycopg
import pytest

from clinical.rule_engine import build_facts, grouped as _engine_grouped
from clinical.suggestion_service import (
    resolve_demographics,
    evaluate_for_patient,
    grouped_for_patient,
)

# ── DB connection (superuser for seeding) ─────────────────────────────────────
_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

# ── Age-gated rule to seed ────────────────────────────────────────────────────
# T2-LIPID-RX-01: DM + age between [40, 75] → suggest statin.
# Verbatim trigger_json from specialist_clinic/src/adapters/sqlite/clinical_rules_seed.py.
_AGE_RULE = {
    "rule_code": "T2-LIPID-RX-01",
    "title": "استاتین‌درمانی",
    "category": "lipid_rx",
    "condition_code": "diabetes",
    "trigger_json": {
        "all": [
            {"var": "condition", "op": "has", "value": "diabetes"},
            {"var": "age", "op": "between", "value": [40, 75]},
        ]
    },
    "human_if": "سن ۴۰–۷۵ + دیابت",
    "recommendation": "استاتینِ متوسط؛ اگر LDL در هدف نرسید ازتیمایب/PCSK9.",
    "action_type": "suggest_med",
    "action_params_json": {"classes": ["statin"]},
    "severity": "info",
    "priority": 61,
    "source_ref": "ADA 10.18/10.20/10.21",
}


@pytest.fixture(scope="session")
def seed_age_patient(seed_clinical_data):
    """
    Seed an age-eligible patient:
      - accounting.patients birthdate='1975-01-01' → age ~51 (inside 40–75)
      - clinical.patient_links enrollment (tenant=1)
      - condition: diabetes
      - vital: hba1c=8.0 (realistic; not needed for the age rule itself)
      - clinical_rules: T2-LIPID-RX-01 (age-gated statin rule)

    Depends on seed_clinical_data so the test DB + schema are ready.
    Returns a dict with patient_uuid, link_id.
    """
    age_eligible_uuid = uuid.UUID("eeeeeeee-aaaa-bbbb-cccc-ffffffffffff")

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        # ── accounting patient (age-eligible) ─────────────────────────────────
        conn.execute("""
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'حسن', 'مسن‌آزمایشی', '4444444441', '09160000041',
                    '1975-01-01', 'male')
            ON CONFLICT (uuid) DO NOTHING
        """, (age_eligible_uuid,))

        row = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s",
            (age_eligible_uuid,)
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

        # ── condition: diabetes ────────────────────────────────────────────────
        diabetes_row = conn.execute(
            "SELECT id FROM clinical.conditions WHERE tenant_id=1 AND code='diabetes'"
        ).fetchone()
        assert diabetes_row, "diabetes condition must be seeded by SQL slice"
        diabetes_id = diabetes_row[0]

        conn.execute("""
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES (1, %s, %s, TRUE, now())
            ON CONFLICT DO NOTHING
        """, (link_id, diabetes_id))

        # ── vital reading: hba1c=8.0 (realistic) ──────────────────────────────
        conn.execute("""
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES (1, %s, 'hba1c', 8.0, '%%', now() - interval '5 days', 'clinic')
        """, (link_id,))

        # ── seed age-gated clinical rule ──────────────────────────────────────
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
            **_AGE_RULE,
            "trigger_json": json.dumps(_AGE_RULE["trigger_json"], ensure_ascii=False),
            "action_params_json": json.dumps(
                _AGE_RULE["action_params_json"], ensure_ascii=False
            ),
        })

    return {
        **seed_clinical_data,
        "age_eligible_uuid": age_eligible_uuid,
        "age_eligible_patient_id": patient_id,
        "age_eligible_link_id": link_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — resolve_demographics returns a DTO with the correct birthdate
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_resolve_demographics_returns_dto_with_birthdate(seed_age_patient):
    """
    resolve_demographics(patient_link_id, tenant_id) must return a PatientDTO
    with a birthdate matching the accounting patient row ('1975-01-01').

    This proves the Port fetch path works end-to-end for the bridge helper.
    """
    from datetime import date

    link_id = seed_age_patient["age_eligible_link_id"]
    dto = resolve_demographics(link_id, tenant_id=1)

    assert dto is not None, (
        f"resolve_demographics must return a PatientDTO for link_id={link_id}. "
        f"Got None — check that accounting.patients row exists and the Port is reachable."
    )
    assert dto.birthdate == date(1975, 1, 1), (
        f"Expected birthdate=1975-01-01, got {dto.birthdate}"
    )
    assert dto.id == seed_age_patient["age_eligible_patient_id"], (
        f"PatientDTO.id must match accounting.patients.id. "
        f"Expected {seed_age_patient['age_eligible_patient_id']}, got {dto.id}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — grouped_for_patient fires T2-LIPID-RX-01 for age-eligible patient
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_grouped_for_patient_fires_age_gated_rule(seed_age_patient):
    """
    grouped_for_patient resolves demographics internally and passes them to
    the engine, so the age fact is populated.

    Patient: birthdate=1975-01-01 (age ~51), condition=diabetes.
    Rule T2-LIPID-RX-01: DM + age between [40, 75] → MUST fire.

    This is the primary proof that Step 6 works: the bridge helper always
    supplies age to the engine, so age-gated rules never silently skip.
    """
    link_id = seed_age_patient["age_eligible_link_id"]
    result = grouped_for_patient(link_id, tenant_id=1)

    fired_codes = {
        r["rule_code"]
        for sec in result["sections"]
        for r in sec["rules"]
    }

    assert "T2-LIPID-RX-01" in fired_codes, (
        f"T2-LIPID-RX-01 must fire for patient with diabetes + age ~51 "
        f"(birthdate=1975-01-01, age between [40, 75]). "
        f"Fired rules: {fired_codes}\n"
        f"If empty: check that T2-LIPID-RX-01 is seeded (ON CONFLICT DO NOTHING "
        f"may silently skip if the rule_code existed with different data)."
    )

    # Safety invariant: all fired rules must be suggestion-only
    for sec in result["sections"]:
        for r in sec["rules"]:
            assert r["suggestion_only"] is True, (
                f"Rule {r['rule_code']} missing suggestion_only=True"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — raw engine with demographics=None does NOT fire age-gated rule
#           (documents + guards the fail-closed safety behaviour)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_raw_engine_without_demographics_does_not_fire_age_gated_rule(seed_age_patient):
    """
    When rule_engine.grouped() is called with demographics=None, age=None
    and all age-gated rules are fail-closed (they don't fire).

    This documents the RISK that motivated Step 6: a non-HTTP caller
    (e.g. Step 12 auto worklist) that calls rule_engine.grouped() directly
    without demographics will silently miss all age-gated rules.

    This test GUARDS that safety property: age=None → T2-LIPID-RX-01 does
    NOT fire, even when the patient has diabetes and would normally qualify.
    """
    link_id = seed_age_patient["age_eligible_link_id"]
    result = _engine_grouped(
        patient_link_id=link_id,
        demographics=None,   # explicitly no demographics → age=None
        tenant_id=1,
    )

    fired_codes = {
        r["rule_code"]
        for sec in result["sections"]
        for r in sec["rules"]
    }

    assert "T2-LIPID-RX-01" not in fired_codes, (
        f"T2-LIPID-RX-01 must NOT fire when demographics=None (age=None). "
        f"The 'between' operator with None returns False in _leaf, so the rule "
        f"is fail-closed — age unknown = rule skips. "
        f"Fired rules: {fired_codes}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — age-ineligible patient (age ~36) does NOT fire T2-LIPID-RX-01
#           even when demographics are supplied
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_age_ineligible_patient_does_not_fire_age_gated_rule(seed_age_patient):
    """
    The base conftest patient has birthdate='1990-05-15' → age ~36.
    T2-LIPID-RX-01 requires age between [40, 75] → must NOT fire for age=36.

    The base patient has diabetes (from seed_clinical_data), so the DM
    condition is satisfied — only age discriminates.

    This proves the rule is actually age-discriminating (not just always-on
    or always-off).
    """
    # The base seed patient is enrolled and has diabetes from seed_clinical_data
    link_id = seed_age_patient["link_id"]

    result = grouped_for_patient(link_id, tenant_id=1)
    fired_codes = {
        r["rule_code"]
        for sec in result["sections"]
        for r in sec["rules"]
    }

    assert "T2-LIPID-RX-01" not in fired_codes, (
        f"T2-LIPID-RX-01 must NOT fire for patient with age ~36 "
        f"(birthdate=1990-05-15, below the [40, 75] age gate). "
        f"Fired rules: {fired_codes}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — evaluate_for_patient is functionally equivalent to grouped_for_patient
#           for the age-eligible patient
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_evaluate_for_patient_fires_age_gated_rule(seed_age_patient):
    """
    evaluate_for_patient() (the flat-list variant) must also fire
    T2-LIPID-RX-01 for the age-eligible patient.

    Proves both public entry points of suggestion_service work correctly.
    """
    link_id = seed_age_patient["age_eligible_link_id"]
    fired = evaluate_for_patient(link_id, tenant_id=1)
    fired_codes = {r["rule_code"] for r in fired}

    assert "T2-LIPID-RX-01" in fired_codes, (
        f"evaluate_for_patient must fire T2-LIPID-RX-01 for age ~51 + diabetes. "
        f"Fired: {fired_codes}"
    )

    # suggestion_only=True on every fired rule (safety invariant)
    for r in fired:
        assert r["suggestion_only"] is True, (
            f"Rule {r['rule_code']} missing suggestion_only=True"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — resolve_demographics returns None gracefully for unknown link
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_resolve_demographics_returns_none_for_unknown_link(seed_age_patient):
    """
    resolve_demographics(99999999, tenant_id=1) must return None gracefully
    when the patient_link_id does not exist — app must keep working standalone.

    This guards the graceful-failure contract documented in suggestion_service.
    """
    dto = resolve_demographics(99_999_999, tenant_id=1)
    assert dto is None, (
        f"resolve_demographics must return None for a non-existent patient_link_id. "
        f"Got: {dto}"
    )
