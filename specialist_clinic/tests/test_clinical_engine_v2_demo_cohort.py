from __future__ import annotations

import pytest


@pytest.fixture()
def cohort_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "cohort.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "cohort-tests",
    })
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

    db = get_db()
    per_patient = db.execute(
        """SELECT p.national_id,
                  (SELECT COUNT(*) FROM vital_readings v WHERE v.patient_link_id=p.id) vitals,
                  (SELECT COUNT(*) FROM lab_results l WHERE l.patient_link_id=p.id) labs,
                  (SELECT COUNT(*) FROM clinical_notes n WHERE n.patient_link_id=p.id) notes,
                  (SELECT COUNT(*) FROM appointments a WHERE a.patient_link_id=p.id) appointments
           FROM patient_links p WHERE p.national_id LIKE 'TEST____'
           ORDER BY p.national_id"""
    ).fetchall()
    assert len(per_patient) == 10
    assert all(row["vitals"] == 210 and row["labs"] == 130 for row in per_patient)
    assert all(row["notes"] == 24 and row["appointments"] == 25 for row in per_patient)

    span = db.execute(
        """SELECT MIN(measured_at) first_at, MAX(measured_at) last_at
           FROM vital_readings WHERE patient_link_id IN
           (SELECT id FROM patient_links WHERE national_id LIKE 'TEST____')"""
    ).fetchone()
    assert span["first_at"].startswith("2021-01")
    assert span["last_at"].startswith("2026-07-21")
    assert db.execute(
        "SELECT COUNT(DISTINCT drug_class) c FROM patient_medications"
    ).fetchone()["c"] >= 12
    assert {row["status"] for row in db.execute(
        "SELECT DISTINCT status FROM appointments"
    ).fetchall()} == {"done", "no_show", "scheduled"}
    assert {row["kind"] for row in db.execute(
        "SELECT DISTINCT kind FROM clinical_notes"
    ).fetchall()} == {"symptom", "exam", "lifestyle", "general"}


def test_cohort_contains_both_positive_safety_cases(cohort_app):
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    DemoCohortService().ensure(actor="qa")
    db = get_db()
    bp = db.execute(
        """SELECT type, value FROM vital_readings
           WHERE patient_link_id=(SELECT id FROM patient_links WHERE national_id='TEST0008')
             AND type IN ('bp_systolic','bp_diastolic')
           ORDER BY measured_at DESC LIMIT 2"""
    ).fetchall()
    assert {row["type"]: row["value"] for row in bp} == {
        "bp_systolic": 184.0, "bp_diastolic": 112.0,
    }
    egfr = db.execute(
        """SELECT value FROM lab_results
           WHERE patient_link_id=(SELECT id FROM patient_links WHERE national_id='TEST0010')
             AND test_key='egfr' ORDER BY taken_at DESC LIMIT 1"""
    ).fetchone()["value"]
    active_metformin = db.execute(
        """SELECT COUNT(*) c FROM patient_medications
           WHERE patient_link_id=(SELECT id FROM patient_links WHERE national_id='TEST0010')
             AND drug_class='metformin' AND is_active=1"""
    ).fetchone()["c"]
    assert egfr == 24.0
    assert active_metformin == 1


def test_forced_rebuild_replaces_only_synthetic_clinical_rows(cohort_app):
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    service = DemoCohortService()
    service.ensure(actor="qa")
    db = get_db()
    real_id = db.execute(
        "INSERT INTO patient_links (national_id, full_name, enrolled_by) VALUES ('0012345678','واقعی','qa')"
    ).lastrowid
    db.execute(
        "INSERT INTO vital_readings (patient_link_id,type,value) VALUES (?, 'weight', 70)",
        (real_id,),
    )
    db.execute(
        "INSERT INTO clinical_notes (patient_link_id,kind,body) VALUES ((SELECT id FROM patient_links WHERE national_id='TEST0001'),'general','tampered')"
    )
    db.commit()

    service.ensure(actor="qa", force=True)
    assert db.execute(
        "SELECT COUNT(*) c FROM vital_readings WHERE patient_link_id=?", (real_id,)
    ).fetchone()["c"] == 1
    assert db.execute(
        "SELECT COUNT(*) c FROM clinical_notes WHERE body='tampered'"
    ).fetchone()["c"] == 0
