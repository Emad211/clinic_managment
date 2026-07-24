from __future__ import annotations

import pytest


@pytest.fixture()
def cohort_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "cohort.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "cohort-tests",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def test_longitudinal_cohort_is_complete_diverse_and_idempotent(cohort_app):
    from src.adapters.sqlite.core import get_db
    from src.domain.clinical_engine.demo_cohort import expected_totals
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    service = DemoCohortService()
    first = service.ensure(actor="qa")
    second = service.ensure(actor="qa")
    assert first["rebuilt"] is True
    assert second["rebuilt"] is False
    assert first["patient_count"] == 10
    assert first["totals"]["vitals"] == expected_totals()["vitals"] == 2100
    assert first["totals"]["labs"] == expected_totals()["labs"] == 1300
    assert first["totals"]["notes"] == 240
    assert first["totals"]["appointments"] == 250
    assert first["totals"]["medication_events"] >= 50
    assert first["totals"]["unmapped_active_medications"] == 0
    assert first["totals"]["unmapped_active_allergies"] == 0
    assert first["totals"]["unresolved_conflicts"] == 0

    db = get_db()
    per_patient = db.execute(
        """SELECT patient.national_id,
                  (SELECT COUNT(*) FROM vital_readings vital
                   WHERE vital.patient_link_id=patient.id) AS vitals,
                  (SELECT COUNT(*) FROM lab_results lab
                   WHERE lab.patient_link_id=patient.id) AS labs,
                  (SELECT COUNT(*) FROM clinical_notes note
                   WHERE note.patient_link_id=patient.id) AS notes,
                  (SELECT COUNT(*) FROM appointments appointment
                   WHERE appointment.patient_link_id=patient.id) AS appointments
           FROM patient_links patient
           WHERE patient.national_id LIKE 'TEST____'
           ORDER BY patient.national_id"""
    ).fetchall()
    assert len(per_patient) == 10
    assert all(
        row["vitals"] == 210 and row["labs"] == 130
        for row in per_patient
    )
    assert all(
        row["notes"] == 24 and row["appointments"] == 25
        for row in per_patient
    )

    span = db.execute(
        """SELECT MIN(measured_at) AS first_at,
                  MAX(measured_at) AS last_at
           FROM vital_readings
           WHERE patient_link_id IN (
               SELECT id FROM patient_links
               WHERE national_id LIKE 'TEST____'
           )"""
    ).fetchone()
    assert span["first_at"].startswith("2021-01")
    assert span["last_at"].startswith("2026-07-21")
    assert db.execute(
        "SELECT COUNT(DISTINCT drug_class) AS count "
        "FROM patient_medications"
    ).fetchone()["count"] >= 12
    allergy_mappings = db.execute(
        """SELECT allergy.substance, catalog.concept_key
           FROM allergies allergy
           JOIN allergy_catalog catalog ON catalog.id=allergy.allergy_concept_id
           WHERE allergy.patient_link_id IN (
               SELECT id FROM patient_links WHERE national_id LIKE 'TEST____'
           )
           ORDER BY allergy.substance"""
    ).fetchall()
    assert {row["concept_key"] for row in allergy_mappings} == {
        "ibuprofen",
        "penicillin",
        "trimethoprim_sulfamethoxazole",
    }
    assert db.execute(
        """SELECT COUNT(*) AS count
           FROM patient_medications medication
           LEFT JOIN drug_catalog catalog
             ON catalog.id=medication.drug_catalog_id
           WHERE medication.is_active=1
             AND (
                 medication.drug_catalog_id IS NULL
                 OR catalog.id IS NULL
                 OR catalog.is_active<>1
                 OR catalog.generic_fa<>medication.drug_name
                 OR catalog.drug_class_key<>medication.drug_class
             )"""
    ).fetchone()["count"] == 0
    assert {
        row["status"]
        for row in db.execute(
            "SELECT DISTINCT status FROM appointments"
        ).fetchall()
    } == {"done", "no_show", "scheduled"}
    assert {
        row["kind"]
        for row in db.execute(
            "SELECT DISTINCT kind FROM clinical_notes"
        ).fetchall()
    } == {"symptom", "exam", "lifestyle", "general"}


def test_cohort_contains_both_positive_safety_cases(cohort_app):
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    DemoCohortService().ensure(actor="qa")
    db = get_db()
    bp = db.execute(
        """SELECT type, value FROM vital_readings
           WHERE patient_link_id=(
               SELECT id FROM patient_links
               WHERE national_id='TEST0008'
           )
             AND type IN ('bp_systolic','bp_diastolic')
           ORDER BY measured_at DESC LIMIT 2"""
    ).fetchall()
    assert {row["type"]: row["value"] for row in bp} == {
        "bp_systolic": 184.0,
        "bp_diastolic": 112.0,
    }
    egfr = db.execute(
        """SELECT value FROM lab_results
           WHERE patient_link_id=(
               SELECT id FROM patient_links
               WHERE national_id='TEST0010'
           )
             AND test_key='egfr'
           ORDER BY taken_at DESC LIMIT 1"""
    ).fetchone()["value"]
    medication = db.execute(
        """SELECT medication.drug_catalog_id,
                  medication.drug_class,
                  catalog.generic_fa,
                  catalog.drug_class_key,
                  catalog.is_active
           FROM patient_medications medication
           JOIN drug_catalog catalog
             ON catalog.id=medication.drug_catalog_id
           WHERE medication.patient_link_id=(
               SELECT id FROM patient_links
               WHERE national_id='TEST0010'
           )
             AND medication.drug_class='metformin'
             AND medication.is_active=1"""
    ).fetchone()
    assert egfr == 24.0
    assert medication is not None
    assert medication["drug_catalog_id"] is not None
    assert medication["drug_class_key"] == "metformin"
    assert medication["is_active"] == 1


def test_forced_rebuild_replaces_only_synthetic_clinical_rows(cohort_app):
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    service = DemoCohortService()
    service.ensure(actor="qa")
    db = get_db()
    real_id = db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, enrolled_by)
           VALUES ('0012345678','واقعی','qa')"""
    ).lastrowid
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value)
           VALUES (?, 'weight', 70)""",
        (real_id,),
    )
    db.execute(
        """INSERT INTO clinical_notes
           (patient_link_id, kind, body)
           VALUES (
               (SELECT id FROM patient_links
                WHERE national_id='TEST0001'),
               'general',
               'tampered'
           )"""
    )
    db.commit()

    service.ensure(actor="qa", force=True)
    assert db.execute(
        "SELECT COUNT(*) AS count FROM vital_readings "
        "WHERE patient_link_id=?",
        (real_id,),
    ).fetchone()["count"] == 1
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_notes "
        "WHERE body='tampered'"
    ).fetchone()["count"] == 0
