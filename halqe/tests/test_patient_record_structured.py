"""Integration tests for the specialist-clinic patient-record migration.

The suite uses the real PostgreSQL schema, app role, RLS GUC and JWT API.  It
pins ownership checks, medication/event atomicity, partial-safe flags, structured
history CRUD, lab-catalog autofill and canonical Observation visibility.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from ninja.testing import TestClient
from psycopg.types.json import Jsonb

from config.api import api


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_SU_USER = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")


def _conninfo() -> str:
    return (
        f"host='{PG_HOST}' port='{PG_PORT}' user='{PG_SU_USER}' "
        f"password='{PG_SU_PASSWORD}' dbname='{TEST_DB}'"
    )


def _client() -> TestClient:
    return TestClient(api)


def _login(seed_data) -> str:
    response = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed_data["test_password"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def structured_record_ready(seed_clinical_data):
    second_uuid = uuid.UUID("22222222-3333-4444-5555-666666666666")
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        # A second enrolled patient in the SAME tenant proves ownership filters,
        # not merely tenant filtering.
        conn.execute(
            """
            INSERT INTO accounting.patients
                (tenant_id, uuid, name, family_name, national_id, phone_number)
            VALUES (1, %s, 'بیمار', 'دوم', '0013546759', '09120000009')
            ON CONFLICT (uuid) DO NOTHING
            """,
            (second_uuid,),
        )
        second_patient_id = conn.execute(
            "SELECT id FROM accounting.patients WHERE uuid=%s",
            (second_uuid,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO clinical.patient_links (tenant_id, patient_id, is_active)
            VALUES (1, %s, TRUE)
            ON CONFLICT (tenant_id, patient_id) DO NOTHING
            """,
            (second_patient_id,),
        )
        second_link_id = conn.execute(
            """
            SELECT id FROM clinical.patient_links
            WHERE tenant_id=1 AND patient_id=%s
            """,
            (second_patient_id,),
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO clinical.conditions
                (tenant_id, name, code, is_active, is_chronic, display_order)
            VALUES (1, 'آسم رکورد تست', 'record_asthma', TRUE, TRUE, 900)
            ON CONFLICT (tenant_id, name) DO UPDATE SET
                code=EXCLUDED.code, is_active=TRUE
            """
        )
        custom_condition_id = conn.execute(
            """
            SELECT id FROM clinical.conditions
            WHERE tenant_id=1 AND name='آسم رکورد تست'
            """
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO clinical.flag_catalog
                (tenant_id, flag_key, label, flag_type, options, category,
                 record_section, display_order, is_active)
            VALUES
                (1, 'record_bool', 'فلگ بولی تست', 'bool', NULL,
                 'risk', 'risk', 1, TRUE),
                (1, 'record_enum', 'فلگ انتخابی تست', 'enum',
                 'low|کم,high|زیاد', 'risk', 'risk', 2, TRUE),
                (1, 'record_date', 'تاریخ تست', 'date', NULL,
                 'history', 'history', 3, TRUE),
                (1, 'record_text', 'متن تست', 'text', NULL,
                 'general', 'general', 4, TRUE)
            ON CONFLICT (tenant_id, flag_key) DO UPDATE SET
                label=EXCLUDED.label,
                flag_type=EXCLUDED.flag_type,
                options=EXCLUDED.options,
                category=EXCLUDED.category,
                record_section=EXCLUDED.record_section,
                display_order=EXCLUDED.display_order,
                is_active=TRUE
            """
        )
        conn.execute(
            """
            INSERT INTO clinical.patient_flags
                (tenant_id, patient_link_id, flag_key, value, recorded_by)
            VALUES (1, %s, 'record_date', '2025-01-02', 'seed')
            ON CONFLICT (tenant_id, patient_link_id, flag_key) DO UPDATE SET
                value=EXCLUDED.value, recorded_by=EXCLUDED.recorded_by
            """,
            (seed_clinical_data["link_id"],),
        )

        conn.execute(
            """
            INSERT INTO clinical.drug_classes
                (tenant_id, class_key, label, glucose_lowering,
                 display_order, is_active)
            VALUES (1, 'record_class', 'کلاس دارویی تست', FALSE, 900, TRUE)
            ON CONFLICT (tenant_id, class_key) DO UPDATE SET
                label=EXCLUDED.label, is_active=TRUE
            """
        )
        conn.execute(
            """
            INSERT INTO clinical.drug_catalog
                (tenant_id, generic_fa, drug_class_key, standard_doses, is_active)
            VALUES (1, 'داروی کاتالوگ تست', 'record_class',
                    '5 mg,10 mg', TRUE)
            """
        )

        conn.execute(
            """
            INSERT INTO clinical.lab_test_catalog
                (tenant_id, test_key, name_fa, unit, ref_low, ref_high,
                 category, display_order, is_active)
            VALUES (1, 'record_lab', 'آزمایش رکورد تست', 'mg/dL',
                    10, 20, 'other', 900, TRUE)
            ON CONFLICT (tenant_id, test_key) DO UPDATE SET
                name_fa=EXCLUDED.name_fa,
                unit=EXCLUDED.unit,
                ref_low=EXCLUDED.ref_low,
                ref_high=EXCLUDED.ref_high,
                category=EXCLUDED.category,
                is_active=TRUE
            """
        )
        conn.execute(
            """
            INSERT INTO clinical.condition_lab_tests
                (tenant_id, condition_code, lab_test_key, display_order)
            VALUES (1, 'diabetes', 'record_lab', 900)
            ON CONFLICT (tenant_id, condition_code, lab_test_key)
            DO UPDATE SET display_order=EXCLUDED.display_order
            """
        )

        # One structured prescription and one legacy JSON snapshot.
        prescription_id = conn.execute(
            """
            INSERT INTO clinical.prescriptions
                (tenant_id, patient_link_id, kind, mode, issued_at)
            VALUES (1, %s, 'record_structured', 'free', now())
            RETURNING id
            """,
            (seed_clinical_data["link_id"],),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO clinical.prescription_items
                (tenant_id, prescription_id, drug_name, drug_class,
                 dose_value, dose_unit, frequency, route, quantity,
                 duration_days, instructions)
            VALUES (1, %s, 'داروی نسخه ساختاریافته', 'record_class',
                    5, 'mg', 'od', 'oral', 30, 30, 'بعد از غذا')
            """,
            (prescription_id,),
        )
        conn.execute(
            """
            INSERT INTO clinical.prescriptions
                (tenant_id, patient_link_id, kind, items, mode, issued_at)
            VALUES (1, %s, 'record_legacy', %s, 'free', now() - interval '1 day')
            """,
            (
                seed_clinical_data["link_id"],
                Jsonb([{"drug_name": "داروی نسخه قدیمی", "dose": "20 mg"}]),
            ),
        )

    return {
        **seed_clinical_data,
        "second_uuid": second_uuid,
        "second_link_id": int(second_link_id),
        "custom_condition_id": int(custom_condition_id),
    }


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_structured_record_reads_specialist_aggregate(structured_record_ready):
    token = _login(structured_record_ready)
    response = _client().get(
        f"/patients/{structured_record_ready['patient_uuid']}/record/structured",
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["patient_link_id"] == structured_record_ready["link_id"]
    assert {row["condition_code"] for row in body["conditions"] if row["is_active"]} >= {
        "diabetes",
        "hypertension",
    }
    assert {row["drug_name"] for row in body["medications"]} >= {
        "متفورمین",
        "آملودیپین",
        "گلیبنکلامید",
    }
    assert any(row["flag_key"] == "record_date" for row in body["flag_catalog"])
    assert any(
        row["test_key"] == "record_lab" and row["suggested"] is True
        for row in body["lab_catalog"]
    )
    assert any(row["generic_fa"] == "داروی کاتالوگ تست" for row in body["drug_catalog"])
    structured = next(
        row for row in body["prescriptions"] if row["kind"] == "record_structured"
    )
    assert structured["items"][0]["source"] == "structured"
    assert structured["items"][0]["drug_name"] == "داروی نسخه ساختاریافته"
    legacy = next(row for row in body["prescriptions"] if row["kind"] == "record_legacy")
    assert legacy["items"][0]["source"] == "legacy_json"
    assert legacy["items"][0]["drug_name"] == "داروی نسخه قدیمی"


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_condition_duplicate_and_cross_patient_delete_are_blocked(structured_record_ready):
    token = _login(structured_record_ready)
    patient_uuid = structured_record_ready["patient_uuid"]
    payload = {
        "condition_id": structured_record_ready["custom_condition_id"],
        "stage": "mild",
        "onset_date": "2024-01-01",
        "notes": "ثبت تست",
    }
    created = _client().post(
        f"/patients/{patient_uuid}/record/conditions",
        headers=_auth(token),
        json=payload,
    )
    assert created.status_code == 201, created.text
    condition_id = created.json()["id"]

    duplicate = _client().post(
        f"/patients/{patient_uuid}/record/conditions",
        headers=_auth(token),
        json=payload,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "conflict"

    wrong_patient = _client().delete(
        f"/patients/{structured_record_ready['second_uuid']}/record/conditions/{condition_id}",
        headers=_auth(token),
    )
    assert wrong_patient.status_code == 404

    removed = _client().delete(
        f"/patients/{patient_uuid}/record/conditions/{condition_id}",
        headers=_auth(token),
    )
    assert removed.status_code == 200
    assert removed.json() == {"deleted": True, "id": condition_id}


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_medication_state_and_timeline_are_atomic(structured_record_ready):
    token = _login(structured_record_ready)
    patient_uuid = structured_record_ready["patient_uuid"]

    invalid = _client().post(
        f"/patients/{patient_uuid}/record/medications",
        headers=_auth(token),
        json={
            "drug_name": "داروی rollback تست",
            "dose": "1 mg",
            "start_date": "2026-01-01",
            "drug_class": "missing_class",
        },
    )
    assert invalid.status_code == 422
    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM clinical.patient_medications
            WHERE tenant_id=1 AND patient_link_id=%s
              AND drug_name='داروی rollback تست'
            """,
            (structured_record_ready["link_id"],),
        ).fetchone()[0] == 0
        assert conn.execute(
            """
            SELECT COUNT(*) FROM clinical.medication_events
            WHERE tenant_id=1 AND patient_link_id=%s
              AND drug_name='داروی rollback تست'
            """,
            (structured_record_ready["link_id"],),
        ).fetchone()[0] == 0

    created = _client().post(
        f"/patients/{patient_uuid}/record/medications",
        headers=_auth(token),
        json={
            "drug_name": "داروی چرخه تست",
            "dose": "5 mg",
            "schedule": "روزی یک بار",
            "start_date": "2026-01-01",
            "refill_interval_days": 30,
            "drug_class": "record_class",
            "notes": "شروع درمان",
        },
    )
    assert created.status_code == 201, created.text
    medication_id = created.json()["id"]
    assert created.json()["refill_due_date"] == "2026-01-31"

    dose = _client().post(
        f"/patients/{patient_uuid}/record/medications/{medication_id}/dose",
        headers=_auth(token),
        json={"dose": "10 mg", "change_date": "2026-01-10", "note": "افزایش"},
    )
    assert dose.status_code == 200, dose.text
    assert dose.json()["dose"] == "10 mg"

    stopped = _client().post(
        f"/patients/{patient_uuid}/record/medications/{medication_id}/stop",
        headers=_auth(token),
        json={"end_date": "2026-01-20", "note": "پایان"},
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["is_active"] is False
    assert stopped.json()["end_date"] == "2026-01-20"

    aggregate = _client().get(
        f"/patients/{patient_uuid}/record/structured",
        headers=_auth(token),
    ).json()
    medication = next(row for row in aggregate["medications"] if row["id"] == medication_id)
    assert [row["event_type"] for row in reversed(medication["events"])] == [
        "start",
        "dose_change",
        "stop",
    ]


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_flags_are_partial_safe_and_invalid_batch_rolls_back(structured_record_ready):
    token = _login(structured_record_ready)
    patient_uuid = structured_record_ready["patient_uuid"]

    first = _client().patch(
        f"/patients/{patient_uuid}/record/flags",
        headers=_auth(token),
        json={
            "values": {
                "record_bool": True,
                "record_date": "",
                "record_enum": "low",
            },
            "clear_keys": [],
        },
    )
    assert first.status_code == 200, first.text
    values = {row["flag_key"]: row["value"] for row in first.json()}
    assert values["record_bool"] == "1"
    assert values["record_enum"] == "low"
    # Empty date is ignored unless clear_keys explicitly names it.
    assert values["record_date"] == "2025-01-02"

    invalid = _client().patch(
        f"/patients/{patient_uuid}/record/flags",
        headers=_auth(token),
        json={
            "values": {"record_bool": False, "record_enum": "not_allowed"},
            "clear_keys": [],
        },
    )
    assert invalid.status_code == 422
    # The bool write occurred earlier in sorted order only inside the transaction;
    # the invalid enum must roll the whole batch back.
    aggregate = _client().get(
        f"/patients/{patient_uuid}/record/structured",
        headers=_auth(token),
    ).json()
    current = {row["flag_key"]: row["value"] for row in aggregate["flag_catalog"]}
    assert current["record_bool"] == "1"
    assert current["record_enum"] == "low"

    cleared = _client().patch(
        f"/patients/{patient_uuid}/record/flags",
        headers=_auth(token),
        json={"values": {}, "clear_keys": ["record_date"]},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()[0]["value"] == ""


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_history_notes_and_ownership_checks(structured_record_ready):
    token = _login(structured_record_ready)
    patient_uuid = structured_record_ready["patient_uuid"]

    surgery = _client().post(
        f"/patients/{patient_uuid}/record/surgeries",
        headers=_auth(token),
        json={"title": "جراحی تست", "performed_on": "2022-02-02", "note": "بدون عارضه"},
    )
    assert surgery.status_code == 201, surgery.text
    surgery_id = surgery.json()["id"]

    history = _client().post(
        f"/patients/{patient_uuid}/record/medical-history",
        headers=_auth(token),
        json={"title": "سابقه تست", "since": "2020-01-01", "note": "شرح"},
    )
    assert history.status_code == 201, history.text

    note = _client().post(
        f"/patients/{patient_uuid}/record/notes",
        headers=_auth(token),
        json={"kind": "symptom", "body": "علامت تست"},
    )
    assert note.status_code == 201, note.text

    wrong_owner = _client().delete(
        f"/patients/{structured_record_ready['second_uuid']}/record/surgeries/{surgery_id}",
        headers=_auth(token),
    )
    assert wrong_owner.status_code == 404

    aggregate = _client().get(
        f"/patients/{patient_uuid}/record/structured",
        headers=_auth(token),
    ).json()
    assert any(row["id"] == surgery_id for row in aggregate["surgeries"])
    assert any(row["title"] == "سابقه تست" for row in aggregate["medical_history"])
    assert any(row["body"] == "علامت تست" for row in aggregate["clinical_notes"])

    deleted = _client().delete(
        f"/patients/{patient_uuid}/record/surgeries/{surgery_id}",
        headers=_auth(token),
    )
    assert deleted.status_code == 200


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_lab_catalog_autofill_and_observation_visibility(structured_record_ready):
    token = _login(structured_record_ready)
    patient_uuid = structured_record_ready["patient_uuid"]

    created = _client().post(
        f"/patients/{patient_uuid}/record/labs",
        headers=_auth(token),
        json={"test_key": "record_lab", "value": 14.5, "notes": "نمونه تست"},
    )
    assert created.status_code == 201, created.text
    lab = created.json()
    assert lab["test_name"] == "آزمایش رکورد تست"
    assert lab["unit"] == "mg/dL"
    assert lab["ref_low"] == 10
    assert lab["ref_high"] == 20

    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        observation = conn.execute(
            """
            SELECT source_table, obs_key, value, verified
            FROM clinical.observations
            WHERE tenant_id=1 AND patient_link_id=%s
              AND source_table='lab' AND source_id=%s
            """,
            (structured_record_ready["link_id"], lab["id"]),
        ).fetchone()
        assert observation == ("lab", "lab:record_lab", 14.5, True)

    wrong_owner = _client().delete(
        f"/patients/{structured_record_ready['second_uuid']}/record/labs/{lab['id']}",
        headers=_auth(token),
    )
    assert wrong_owner.status_code == 404

    deleted = _client().delete(
        f"/patients/{patient_uuid}/record/labs/{lab['id']}",
        headers=_auth(token),
    )
    assert deleted.status_code == 200


@pytest.mark.django_db(databases=["default", "accounting_read"], transaction=True)
def test_record_writes_are_audited(structured_record_ready):
    token = _login(structured_record_ready)
    patient_uuid = structured_record_ready["patient_uuid"]
    response = _client().post(
        f"/patients/{patient_uuid}/record/notes",
        headers=_auth(token),
        json={"kind": "general", "body": "یادداشت audit تست"},
    )
    assert response.status_code == 201, response.text
    note_id = response.json()["id"]

    with psycopg.connect(_conninfo(), autocommit=True) as conn:
        audit = conn.execute(
            """
            SELECT action_type, action_category, target_table,
                   target_id, patient_link_id
            FROM clinical.activity_logs
            WHERE tenant_id=1 AND target_table='clinical_notes'
              AND target_id=%s
            ORDER BY id DESC LIMIT 1
            """,
            (note_id,),
        ).fetchone()
        assert audit == (
            "clinical_note_added",
            "patient_record",
            "clinical_notes",
            note_id,
            structured_record_ready["link_id"],
        )
