"""
tests/test_record_summary.py — فاز ۱ کاکپیت: enrichment of GET /patients/{uuid}/record.

Covers the safety-cockpit summary fields that clinical.record_summary_service
(record_summary) adds to the record endpoint:
  - control        : {status, label}  (worst of latest VERIFIED vitals)
  - risk           : {level, dominant, score}
  - open_followups_count / refill_due_count
  - per_disease    : [{condition_code, condition_name, control, risk_level,
                        indicators:[{key,label,value,unit,target,direction,delta,level}]}]
  - demographics.age

WHY A DEDICATED SEED (not seed_clinical_data): the session seed accumulates
vitals across every test module and is ordered/valued in a way that makes the
worst-of-latest control status ambiguous. Here we build ONE isolated patient
with a fully-controlled input set so every asserted number is deterministic and
independent of what other modules seeded.

This module is also the schema-validation guard for record_summary_service: it
exercises the real ORM field names the service queries (VitalReading.verified/
type/measured_at, PatientMedication.refill_due_date/is_active,
FollowupTask.STATUS_OPEN, Condition.code, PatientCondition). A wrong field name
in the service surfaces here as an error / 500, not silently.

verified-gate (SACRED): a self-report row (verified=False) must NOT influence
control or risk. We seed a danger-range UNVERIFIED hba1c=11.0 alongside healthy
VERIFIED data; with the gate the patient stays controlled/stable. Without it the
patient would flip to uncontrolled — so this asserts the gate behaviourally.

Requires the Docker PG test DB (conftest django_db_setup) — same as the rest of
the record suite.
"""
import uuid as _uuid

import psycopg
import pytest
from ninja.testing import TestClient

from config.api import api

_CONNINFO = (
    "host='localhost' port='55432' "
    "user='postgres' password='validate_only' "
    "dbname='halqe_app_test'"
)

# A stable UUID unique to this module (no collision with other test patients).
_PATIENT_UUID = _uuid.UUID("d1000091-0000-0000-0000-000000000091")


def _client() -> TestClient:
    return TestClient(api)


def _get_token(seed_data) -> str:
    resp = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed_data["test_password"]},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


@pytest.fixture(scope="module")
def cockpit_patient(seed_clinical_data):
    """
    Seed one isolated diabetic patient (tenant 1) with a DETERMINISTIC input set:

      conditions : diabetes (active)  → uses the slice2-seeded condition id.
      vitals (VERIFIED — enter control/risk):
        hba1c        6.8  (older)   → ok (<7.0)
        hba1c        6.5  (newest)  → ok  → latest; delta = 6.5-6.8 = -0.3, improving
        bp_systolic  118            → ok (<130)
      vital (UNVERIFIED self-report — must be IGNORED by the gate):
        hba1c       11.0            → danger IF the gate were off (it is not)
      medication (active, refill in +3d → within the 7-day refill horizon):
        متفورمین  refill_due_date = today+3, is_active=TRUE  → refill_due_count = 1
      follow-up (open) → open_followups_count = 1

    Expected summary (gate ON):
      control.status  = 'controlled'   (worst of {hba1c ok, bp ok})
      risk.level      = 'stable'       (no danger/warn; no overdue refill/no-show)
      open_followups_count = 1
      refill_due_count     = 1
      per_disease[diabetes].control.status = 'controlled'
      per_disease[diabetes].risk_level     = 'stable'
      indicators include hba1c with value=6.5, level='ok', delta.improving=True

    Returns the extended seed dict.
    """
    diabetes_id = seed_clinical_data["diabetes_condition_id"]
    assert diabetes_id, "diabetes condition must be seeded (slice2) for tenant 1"

    with psycopg.connect(_CONNINFO, autocommit=True) as conn:
        # accounting patient (superuser write — the app role cannot).
        conn.execute(
            """
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id,
                 phone_number, birthdate, gender)
            VALUES (1, %s, 'کاکپیت', 'تست', 'REC0000091', '09100000091',
                    '1969-01-01', 'male')
            ON CONFLICT (uuid) DO NOTHING
            """,
            (_PATIENT_UUID,),
        )
        pat_id = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s", (_PATIENT_UUID,)
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
            """,
            (pat_id,),
        )
        link_id = conn.execute(
            "SELECT id FROM clinical.patient_links "
            "WHERE tenant_id=1 AND patient_id=%s",
            (pat_id,),
        ).fetchone()[0]

        # active diabetes diagnosis
        conn.execute(
            """
            INSERT INTO clinical.patient_conditions
                (tenant_id, patient_link_id, condition_id, is_active, diagnosed_at)
            VALUES (1, %s, %s, TRUE, now())
            ON CONFLICT DO NOTHING
            """,
            (link_id, diabetes_id),
        )

        # VERIFIED vitals (verified column DEFAULTs TRUE)
        conn.execute(
            """
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at, source)
            VALUES
                (1, %s, 'hba1c',       6.8, '%%',   now() - interval '40 days', 'clinic'),
                (1, %s, 'hba1c',       6.5, '%%',   now() - interval '2 days',  'clinic'),
                (1, %s, 'bp_systolic', 118, 'mmHg', now() - interval '2 days',  'clinic')
            """,
            (link_id, link_id, link_id),
        )

        # UNVERIFIED self-report danger reading — must be gated out.
        conn.execute(
            """
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at,
                 source, verified)
            VALUES (1, %s, 'hba1c', 11.0, '%%', now() - interval '1 days',
                    'patient_self', FALSE)
            """,
            (link_id,),
        )

        # active med, refill due within the 7-day horizon (today+3)
        conn.execute(
            """
            INSERT INTO clinical.patient_medications
                (tenant_id, patient_link_id, drug_name, dose, schedule,
                 start_date, refill_due_date, drug_class, is_active, created_at)
            VALUES (1, %s, 'متفورمین', '500mg', 'روزی دو بار',
                    '2020-01-01', CURRENT_DATE + 3, 'metformin', TRUE, now())
            """,
            (link_id,),
        )

        # one OPEN follow-up task
        conn.execute(
            """
            INSERT INTO clinical.followup_tasks
                (tenant_id, patient_link_id, due_date, reason, status,
                 fulfillment, created_at)
            VALUES (1, %s, CURRENT_DATE - 1, 'visit_due', 'open',
                    'in_person', now())
            """,
            (link_id,),
        )

    return {**seed_clinical_data, "cockpit_uuid": _PATIENT_UUID, "cockpit_link_id": link_id}


# ---------------------------------------------------------------------------
# 1. Top-level cockpit fields present + correct
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_summary_top_level_fields(cockpit_patient):
    """
    GET /record → the additive cockpit fields are present with the deterministic
    values computed from the seeded (verified) data.
    """
    token = _get_token(cockpit_patient)
    resp = _client().get(
        f"/patients/{cockpit_patient['cockpit_uuid']}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # control block — worst of latest VERIFIED vitals (all ok → controlled)
    assert "control" in data
    assert data["control"]["status"] == "controlled", data["control"]
    assert data["control"]["label"]  # non-empty Persian label

    # risk block — no danger/warn, no overdue refill / no-show → stable
    assert "risk" in data
    assert data["risk"]["level"] == "stable", data["risk"]
    assert data["risk"]["score"] == 0, data["risk"]
    assert "dominant" in data["risk"]

    # counts (operational — verified-independent)
    assert data["open_followups_count"] == 1, data
    assert data["refill_due_count"] == 1, data


# ---------------------------------------------------------------------------
# 2. per_disease block with indicators + delta
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_summary_per_disease(cockpit_patient):
    """
    per_disease carries one entry for diabetes with a controlled status, stable
    risk tier, and an indicators list. The hba1c indicator must reflect the
    latest VERIFIED value (6.5), an 'ok' level, and a direction-aware improving
    delta (6.5 - 6.8 = -0.3; hba1c is high-worse → decrease improves).
    """
    token = _get_token(cockpit_patient)
    resp = _client().get(
        f"/patients/{cockpit_patient['cockpit_uuid']}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    per_disease = resp.json()["per_disease"]

    assert isinstance(per_disease, list) and per_disease, "per_disease must be non-empty"
    dia = next((d for d in per_disease if d["condition_code"] == "diabetes"), None)
    assert dia is not None, f"diabetes block missing: {[d['condition_code'] for d in per_disease]}"

    assert dia["condition_name"], "condition_name must be populated"
    assert dia["control"]["status"] == "controlled", dia["control"]
    assert dia["risk_level"] == "stable", dia

    # indicators list — must include hba1c with the latest verified value + delta
    assert isinstance(dia["indicators"], list)
    hba1c = next((i for i in dia["indicators"] if i["key"] == "hba1c"), None)
    assert hba1c is not None, f"hba1c indicator missing: {[i['key'] for i in dia['indicators']]}"
    assert hba1c["value"] == 6.5, hba1c
    assert hba1c["level"] == "ok", hba1c
    assert hba1c["unit"] is not None
    assert hba1c["target"] == 7.0, hba1c   # slice2 seed target
    assert hba1c["direction"] == "high", hba1c
    # delta: 6.5 - 6.8 = -0.3, dir=down, improving (high-worse → lower better)
    assert hba1c["delta"] is not None, hba1c
    assert hba1c["delta"]["value"] == -0.3, hba1c["delta"]
    assert hba1c["delta"]["dir"] == "down", hba1c["delta"]
    assert hba1c["delta"]["improving"] is True, hba1c["delta"]


# ---------------------------------------------------------------------------
# 3. demographics.age
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_summary_demographics_age(cockpit_patient):
    """
    demographics gains a derived `age` (from birthdate 1969-01-01) while keeping
    every existing PatientDTO field (additive subclass — no removals).
    """
    token = _get_token(cockpit_patient)
    resp = _client().get(
        f"/patients/{cockpit_patient['cockpit_uuid']}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    demo = resp.json()["demographics"]

    # existing fields preserved
    assert demo["national_id"] == "REC0000091"
    assert demo["full_name"]  # generated column still present
    # derived age present + sane (birthdate 1969 → ~57 in 2026)
    assert "age" in demo, demo
    assert isinstance(demo["age"], int)
    assert 50 <= demo["age"] <= 65, demo["age"]


# ---------------------------------------------------------------------------
# 4. verified-gate — unverified danger self-report does NOT move control/risk
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_summary_verified_gate_on_control_and_risk(cockpit_patient):
    """
    SACRED verified-gate regression on the cockpit summary.

    The seeded patient has a danger-range UNVERIFIED self-report (hba1c=11.0)
    that is NEWER than every verified reading. If the gate leaked, worst-of-latest
    control would become 'uncontrolled' and risk would gain danger points.

    Because record_summary filters verified=True for control + risk, the patient
    stays controlled/stable — proving the unverified row is excluded from
    decision-support derivations (while it is still shown raw in recent_vitals
    for the physician verify inbox).
    """
    token = _get_token(cockpit_patient)
    resp = _client().get(
        f"/patients/{cockpit_patient['cockpit_uuid']}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Gate ON → healthy verified data wins; danger self-report ignored.
    assert data["control"]["status"] == "controlled", (
        "verified-gate breach: unverified danger self-report leaked into control"
    )
    assert data["risk"]["level"] == "stable", (
        "verified-gate breach: unverified danger self-report leaked into risk"
    )
    assert data["risk"]["score"] == 0, data["risk"]

    # Sanity: the raw unverified row IS still present in recent_vitals (verify
    # inbox needs it) but carries NO clinical level (that gate is the record
    # endpoint's own; asserted in depth in test_patient_record.py).
    unverified = [
        v for v in data["recent_vitals"]
        if v["type"] == "hba1c" and v["verified"] is False
    ]
    assert unverified, "the unverified self-report row must still be serialised"
    assert all(v["value"] == 11.0 for v in unverified)
    assert all(v["level"] is None for v in unverified)


# ---------------------------------------------------------------------------
# 5. tenant isolation — cockpit fields still 404 across tenants (no leakage)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_summary_tenant_isolation_404(cockpit_patient):
    """
    The enriched endpoint keeps the existing tenant guard: a tenant-2 patient
    is still 404 for a tenant-1 token (the summary code path must not weaken it).
    """
    token = _get_token(cockpit_patient)
    tenant2_uuid = cockpit_patient["tenant2_patient_uuid"]
    resp = _client().get(
        f"/patients/{tenant2_uuid}/record",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text
