"""Characterization and integration tests for specialist patient-record parity.

The suite exercises the real PostgreSQL SQL slices, RLS-enabled app role, JWT
routing, catalog defaults, atomic rollback, scoped deletes, medication event
history, canonical lab metadata, and the self-report audit boundary.
"""
from __future__ import annotations

from datetime import date
import os

import psycopg
import pytest
from django.core.management import call_command
from ninja.testing import TestClient

from clinical.models import LabResult, PatientCondition, PatientFlag, PatientMedication, VitalReading
from clinical.record_models import DrugCatalog, DrugClass, FlagCatalog, LabTestCatalog, MedicationEvent
from config.api import api
from platform_core.tenant_context import set_tenant_guc


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "55432")
TEST_DB = os.environ.get("PG_TEST_DB", "halqe_app_test")
PG_SU_USER = os.environ.get("PG_USER", "postgres")
PG_SU_PASSWORD = os.environ.get("PG_PASSWORD", "validate_only")


def _client() -> TestClient:
    return TestClient(api)


def _token(seed) -> str:
    response = _client().post(
        "/auth/login",
        json={"username": "testuser", "password": seed["test_password"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(seed) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(seed)}"}


def _su_conn():
    return psycopg.connect(
        f"host='{PG_HOST}' port='{PG_PORT}' user='{PG_SU_USER}' "
        f"password='{PG_SU_PASSWORD}' dbname='{TEST_DB}'",
        autocommit=True,
    )


@pytest.fixture(scope="session")
def record_ready(seed_clinical_data):
    call_command("seed_record_catalogs", tenant_id=1, verbosity=0)
    call_command("seed_record_catalogs", tenant_id=1, verbosity=0)
    return seed_clinical_data


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_catalog_seed_matches_specialist_defaults_and_is_idempotent(record_ready):
    set_tenant_guc(1)
    assert FlagCatalog.objects.filter(tenant_id=1).count() == 18
    assert DrugClass.objects.filter(tenant_id=1).count() == 25
    assert LabTestCatalog.objects.filter(tenant_id=1).count() == 46
    assert DrugCatalog.objects.filter(tenant_id=1).count() == 52

    with _su_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM clinical.condition_lab_tests WHERE tenant_id=1"
        ).fetchone()[0]
        assert count == 48

    smoking = FlagCatalog.objects.get(tenant_id=1, flag_key="smoking")
    assert smoking.record_section == "lifestyle"
    assert "current|فعلی" in smoking.options

    metformin = DrugCatalog.objects.get(tenant_id=1, generic_fa="متفورمین")
    assert metformin.drug_class_key == "metformin"
    assert "1000mg" in metformin.standard_doses


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_record_projection_contains_all_specialist_sections(record_ready):
    response = _client().get(
        f"/patients/{record_ready['patient_uuid']}/record-data",
        headers=_auth(record_ready),
    )
    assert response.status_code == 200, response.text
    data = response.json()

    expected = {
        "condition_catalog",
        "conditions",
        "surgeries",
        "medical_history",
        "notes",
        "flag_catalog",
        "patient_flags",
        "lab_catalog",
        "suggested_labs",
        "labs",
        "indicator_catalog",
        "drug_classes",
        "drug_catalog",
        "medications",
        "medication_events",
        "appointments",
        "prescriptions",
        "accounting_visit_history",
    }
    assert expected <= set(data)
    assert {row["condition_code"] for row in data["conditions"] if row["is_active"]} >= {
        "diabetes",
        "hypertension",
    }
    suggested_keys = [row["test_key"] for row in data["suggested_labs"]]
    assert "hba1c" in suggested_keys
    assert "creatinine" in suggested_keys
    assert len(suggested_keys) == len(set(suggested_keys))
    assert any(row["generic_fa"] == "متفورمین" for row in data["drug_catalog"])


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_history_surgery_and_notes_crud_are_scoped_and_audited(record_ready):
    client = _client()
    headers = _auth(record_ready)
    base = f"/patients/{record_ready['patient_uuid']}/record"

    surgery = client.post(
        f"{base}/surgeries",
        headers=headers,
        json={"title": "آپاندکتومی", "performed_on": "2010-05-01", "note": "بدون عارضه"},
    )
    assert surgery.status_code == 201, surgery.text
    assert surgery.json()["title"] == "آپاندکتومی"

    history = client.post(
        f"{base}/medical-history",
        headers=headers,
        json={"title": "آسم کودکی", "since": "2001-01-01", "note": "خاموش"},
    )
    assert history.status_code == 201, history.text

    note = client.post(
        f"{base}/notes",
        headers=headers,
        json={"kind": "symptom", "body": "  تشنگی و پرنوشی  "},
    )
    assert note.status_code == 201, note.text
    assert note.json()["body"] == "تشنگی و پرنوشی"

    invalid = client.post(
        f"{base}/notes",
        headers=headers,
        json={"kind": "unknown", "body": "x"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_note_kind"

    cross = client.delete(
        f"/patients/{record_ready['tenant2_patient_uuid']}/record/surgeries/{surgery.json()['id']}",
        headers=headers,
    )
    assert cross.status_code == 404

    assert client.delete(
        f"{base}/surgeries/{surgery.json()['id']}", headers=headers
    ).status_code == 200
    assert client.delete(
        f"{base}/medical-history/{history.json()['id']}", headers=headers
    ).status_code == 200
    assert client.delete(
        f"{base}/notes/{note.json()['id']}", headers=headers
    ).status_code == 200

    with _su_conn() as conn:
        actions = {
            row[0]
            for row in conn.execute(
                """
                SELECT action_type FROM clinical.activity_logs
                WHERE tenant_id=1 AND patient_link_id=%s
                  AND action_type LIKE 'record_%%'
                """,
                (record_ready["link_id"],),
            ).fetchall()
        }
    assert {
        "record_surgery_added",
        "record_surgery_deleted",
        "record_history_added",
        "record_history_deleted",
        "record_note_added",
        "record_note_deleted",
    } <= actions


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_partial_flag_update_preserves_blank_dates_and_rolls_back_invalid_enum(record_ready):
    client = _client()
    headers = _auth(record_ready)
    url = f"/patients/{record_ready['patient_uuid']}/record/flags"

    first = client.put(
        url,
        headers=headers,
        json={
            "managed_keys": ["eye_exam_date", "smoking"],
            "values": {"eye_exam_date": "2026-02-03", "smoking": "current"},
        },
    )
    assert first.status_code == 200, first.text

    second = client.put(
        url,
        headers=headers,
        json={
            "managed_keys": ["eye_exam_date", "smoking"],
            "values": {"eye_exam_date": "", "smoking": ""},
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["values"]["eye_exam_date"] == "2026-02-03"
    assert "smoking" not in second.json()["values"]

    bad = client.put(
        url,
        headers=headers,
        json={
            "managed_keys": ["ascvd", "smoking"],
            "values": {"ascvd": True, "smoking": "not-an-option"},
        },
    )
    assert bad.status_code == 422
    set_tenant_guc(1)
    assert not PatientFlag.objects.filter(
        tenant_id=1,
        patient_link_id=record_ready["link_id"],
        flag_key="ascvd",
    ).exists(), "transaction must roll back the bool write before invalid enum"


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_condition_duplicate_is_blocked_and_inactive_row_reactivates(record_ready):
    client = _client()
    headers = _auth(record_ready)
    base = f"/patients/{record_ready['patient_uuid']}/record/conditions"
    diabetes_assignment = record_ready["pc_ids"]["diabetes"]

    duplicate = client.post(
        base,
        headers=headers,
        json={"condition_id": record_ready["diabetes_condition_id"]},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "duplicate_condition"

    removed = client.delete(f"{base}/{diabetes_assignment}", headers=headers)
    assert removed.status_code == 200

    restored = client.post(
        base,
        headers=headers,
        json={
            "condition_id": record_ready["diabetes_condition_id"],
            "stage": "T2DM-updated",
            "onset_date": "2019-01-01",
        },
    )
    assert restored.status_code == 201, restored.text
    assert restored.json()["id"] == diabetes_assignment

    set_tenant_guc(1)
    row = PatientCondition.objects.get(id=diabetes_assignment)
    assert row.is_active is True
    assert row.stage == "T2DM-updated"
    assert row.onset_date == date(2019, 1, 1)


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_medication_lifecycle_is_atomic_catalog_backed_and_evented(record_ready):
    client = _client()
    headers = _auth(record_ready)
    set_tenant_guc(1)
    drug_id = DrugCatalog.objects.get(tenant_id=1, generic_fa="امپاگلیفلوزین").id
    base = f"/patients/{record_ready['patient_uuid']}/record/medications"

    created = client.post(
        base,
        headers=headers,
        json={
            "drug_id": drug_id,
            "dose": "10mg",
            "schedule": "روزی یک بار",
            "start_date": "2026-01-01",
            "refill_interval_days": 30,
        },
    )
    assert created.status_code == 201, created.text
    med = created.json()
    assert med["drug_name"] == "امپاگلیفلوزین"
    assert med["drug_class"] == "sglt2i"
    assert med["refill_due_date"] == "2026-01-31"

    changed = client.post(
        f"{base}/{med['id']}/dose",
        headers=headers,
        json={"new_dose": "25mg", "change_date": "2026-01-10"},
    )
    assert changed.status_code == 200
    assert changed.json()["dose"] == "25mg"

    stopped = client.post(
        f"{base}/{med['id']}/stop",
        headers=headers,
        json={"end_date": "2026-02-01", "note": "پایان دوره"},
    )
    assert stopped.status_code == 200
    assert stopped.json()["is_active"] is False

    after_stop = client.post(
        f"{base}/{med['id']}/dose",
        headers=headers,
        json={"new_dose": "10mg"},
    )
    assert after_stop.status_code == 409
    assert after_stop.json()["code"] == "medication_inactive"

    set_tenant_guc(1)
    events = list(
        MedicationEvent.objects.filter(
            tenant_id=1,
            patient_link_id=record_ready["link_id"],
            medication_id=med["id"],
        ).values_list("event_type", flat=True)
    )
    assert events == ["start", "dose_change", "stop"]


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_bulk_labs_are_all_or_nothing_and_use_canonical_metadata(record_ready):
    client = _client()
    headers = _auth(record_ready)
    url = f"/patients/{record_ready['patient_uuid']}/record/labs"

    set_tenant_guc(1)
    before = LabResult.objects.filter(
        tenant_id=1, patient_link_id=record_ready["link_id"]
    ).count()

    bad = client.post(
        url,
        headers=headers,
        json={
            "items": [
                {"test_key": "hba1c", "value": 7.1},
                {"test_key": "unknown", "value": 1},
            ],
            "taken_at": "2026-03-01T09:00:00+03:30",
        },
    )
    assert bad.status_code == 422
    set_tenant_guc(1)
    assert LabResult.objects.filter(
        tenant_id=1, patient_link_id=record_ready["link_id"]
    ).count() == before

    good = client.post(
        url,
        headers=headers,
        json={
            "items": [
                {"test_key": "hba1c", "value": 7.1},
                {"test_key": "creatinine", "value": 1.0},
            ],
            "taken_at": "2026-03-01T09:00:00+03:30",
        },
    )
    assert good.status_code == 201, good.text
    assert good.json()["count"] == 2

    set_tenant_guc(1)
    hba1c = LabResult.objects.get(id=good.json()["ids"][0])
    assert hba1c.test_name == "هموگلوبین A1c"
    assert hba1c.unit == "%"
    assert hba1c.ref_low == pytest.approx(4.0)
    assert hba1c.ref_high == pytest.approx(5.6)

    duplicate = client.post(
        url,
        headers=headers,
        json={
            "items": [
                {"test_key": "fbs", "value": 100},
                {"test_key": "fbs", "value": 101},
            ]
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "duplicate_test_key"


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_bulk_vitals_are_atomic_and_self_report_rows_cannot_be_deleted(record_ready):
    client = _client()
    headers = _auth(record_ready)
    base = f"/patients/{record_ready['patient_uuid']}/record/vitals"

    set_tenant_guc(1)
    before = VitalReading.objects.filter(
        tenant_id=1, patient_link_id=record_ready["link_id"]
    ).count()
    bad = client.post(
        base,
        headers=headers,
        json={
            "items": [
                {"type": "bp_systolic", "value": 125},
                {"type": "not_real", "value": 1},
            ]
        },
    )
    assert bad.status_code == 422
    set_tenant_guc(1)
    assert VitalReading.objects.filter(
        tenant_id=1, patient_link_id=record_ready["link_id"]
    ).count() == before

    good = client.post(
        base,
        headers=headers,
        json={"items": [{"type": "bp_systolic", "value": 125}]},
    )
    assert good.status_code == 201, good.text

    with _su_conn() as conn:
        self_id = conn.execute(
            """
            INSERT INTO clinical.vital_readings
                (tenant_id, patient_link_id, type, value, unit, measured_at,
                 source, verified)
            VALUES (1, %s, 'weight', 80, 'kg', now(), 'patient_self', FALSE)
            RETURNING id
            """,
            (record_ready["link_id"],),
        ).fetchone()[0]

    blocked = client.delete(f"{base}/{self_id}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "self_report_delete_blocked"


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_accounting_visit_history_is_read_only_and_tenant_scoped(record_ready):
    with _su_conn() as conn:
        invoice_id = conn.execute(
            """
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, status, total_amount, work_date)
            VALUES (1, %s, 'closed', 90000, '2026-04-01')
            RETURNING id
            """,
            (record_ready["patient_id"],),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accounting.visits
                (tenant_id, patient_id, visit_date, work_date, price,
                 invoice_id, doctor_name)
            VALUES (1, %s, now(), '2026-04-01', 90000, %s, 'دکتر تست')
            """,
            (record_ready["patient_id"], invoice_id),
        )

    response = _client().get(
        f"/patients/{record_ready['patient_uuid']}/record-data",
        headers=_auth(record_ready),
    )
    assert response.status_code == 200, response.text
    visits = response.json()["accounting_visit_history"]
    assert any(
        row["invoice_id"] == invoice_id
        and row["doctor_name"] == "دکتر تست"
        and row["price"] == 90000
        for row in visits
    )


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_foreign_tenant_record_is_not_discoverable(record_ready):
    response = _client().get(
        f"/patients/{record_ready['tenant2_patient_uuid']}/record-data",
        headers=_auth(record_ready),
    )
    assert response.status_code == 404


@pytest.mark.django_db(databases=["default", "accounting_read"])
def test_record_schema_constraints_and_rls_exist(record_ready):
    with _su_conn() as conn:
        constraints = {
            row[0]
            for row in conn.execute(
                """
                SELECT conname FROM pg_constraint
                WHERE conname IN (
                    'chk_clinical_notes_kind',
                    'chk_surgery_history_title_not_blank',
                    'chk_medical_history_title_not_blank',
                    'chk_flag_catalog_record_section',
                    'chk_medication_events_type'
                )
                """
            ).fetchall()
        }
        assert constraints == {
            "chk_clinical_notes_kind",
            "chk_surgery_history_title_not_blank",
            "chk_medical_history_title_not_blank",
            "chk_flag_catalog_record_section",
            "chk_medication_events_type",
        }

        rows = conn.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='clinical'
              AND c.relname IN (
                'surgery_history','medical_history','clinical_notes',
                'flag_catalog','drug_catalog','lab_test_catalog','medication_events'
              )
            """
        ).fetchall()
        assert rows
        assert all(enabled and forced for _name, enabled, forced in rows)
