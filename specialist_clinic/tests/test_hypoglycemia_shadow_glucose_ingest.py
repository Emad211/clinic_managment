from __future__ import annotations

from datetime import datetime
import sqlite3

import pytest


@pytest.fixture()
def glucose_ingest_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "hypoglycemia-glucose-ingest.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "hypoglycemia-glucose-ingest-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id: str) -> int:
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, gender, birthdate, enrolled_by,
                enrolled_at)
               VALUES (?, ?, 'female', '1980-01-01', 'pytest',
                       '2026-01-01 09:00:00')""",
            (national_id, f"Glucose Patient {national_id}"),
        ).lastrowid
    )
    db.commit()
    return patient_id


def _service(db):
    from src.services.hypoglycemia_shadow_glucose_ingest import (
        HypoglycemiaShadowGlucoseIngestService,
    )

    return HypoglycemiaShadowGlucoseIngestService(
        db,
        clock=lambda: datetime(2026, 8, 1, 12, 0, 0),
    )


def _shadow_table_count(db) -> int:
    return int(
        db.execute(
            """SELECT COUNT(*) FROM sqlite_master
               WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
        ).fetchone()[0]
    )


def _login(app):
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert response.status_code in {302, 303}
    return client


def test_non_fasting_reading_does_not_install_shadow_storage(glucose_ingest_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "HYPOING001")

    reading_id = _service(db).add_vital_reading(
        patient_id,
        vtype="weight",
        value=72,
        unit="kg",
        measured_at="2026-08-01 08:00:00",
        recorded_by="nurse",
    )

    row = db.execute(
        "SELECT * FROM vital_readings WHERE id=?", (reading_id,)
    ).fetchone()
    assert row["value"] == pytest.approx(72)
    assert _shadow_table_count(db) == 0


def test_fasting_glucose_at_boundary_does_not_create_candidate(
    glucose_ingest_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "HYPOING002")

    reading_id = _service(db).add_vital_reading(
        patient_id,
        vtype="fbs",
        value=54,
        unit="mg/dL",
        measured_at="2026-08-01 08:10:00",
        recorded_by="nurse",
    )

    assert db.execute(
        "SELECT COUNT(*) FROM vital_readings WHERE id=?", (reading_id,)
    ).fetchone()[0] == 1
    assert _shadow_table_count(db) == 0


def test_low_fasting_glucose_atomically_creates_candidate_only(
    glucose_ingest_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "HYPOING003")

    reading_id = _service(db).add_vital_reading(
        patient_id,
        vtype="fbs",
        value=53,
        unit="mg/dL",
        measured_at="2026-08-01 08:20:00",
        recorded_by="nurse",
    )

    reading = db.execute(
        "SELECT * FROM vital_readings WHERE id=?", (reading_id,)
    ).fetchone()
    event = db.execute(
        """SELECT * FROM hypoglycemia_shadow_event_versions
           WHERE source_system='vital_readings' AND source_record_id=?""",
        (str(reading_id),),
    ).fetchone()

    assert reading["patient_link_id"] == patient_id
    assert reading["type"] == "fbs"
    assert reading["measured_at"] == "2026-08-01 08:20:00"
    assert event["status"] == "CANDIDATE"
    assert event["event_level"] == "LEVEL_2"
    assert event["occurred_at"] == reading["measured_at"]
    assert event["glucose_value"] == pytest.approx(53)
    assert event["glucose_unit"] == "mg/dL"
    assert event["reporter_type"] == "SYSTEM"
    assert event["verification"] == "PROVISIONAL"
    assert event["actor_username"] == "nurse"
    assert db.execute("SELECT COUNT(*) FROM followup_tasks").fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM clinical_recommendation_events"
    ).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM patient_medications").fetchone()[0] == 0


def test_mmol_value_is_compared_after_unit_conversion(glucose_ingest_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "HYPOING004")
    service = _service(db)

    low_id = service.add_vital_reading(
        patient_id,
        vtype="fbs",
        value=2.9,
        unit="mmol/L",
        measured_at="2026-08-01 08:30:00",
        recorded_by="nurse",
    )
    boundary_id = service.add_vital_reading(
        patient_id,
        vtype="fbs",
        value=3.0,
        unit="mmol/L",
        measured_at="2026-08-01 08:31:00",
        recorded_by="nurse",
    )

    roots = db.execute(
        """SELECT source_record_id
           FROM hypoglycemia_shadow_event_versions
           WHERE version_number=1 ORDER BY source_record_id"""
    ).fetchall()
    assert [str(row["source_record_id"]) for row in roots] == [str(low_id)]
    assert db.execute(
        "SELECT COUNT(*) FROM vital_readings WHERE id=?", (boundary_id,)
    ).fetchone()[0] == 1


def test_existing_reading_candidate_processing_is_idempotent(
    glucose_ingest_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "HYPOING005")
    service = _service(db)
    reading_id = service.add_vital_reading(
        patient_id,
        vtype="fbs",
        value=50,
        unit="mg/dL",
        measured_at="2026-08-01 08:40:00",
        recorded_by="nurse",
    )

    first = service.ensure_candidate_for_reading(
        patient_link_id=patient_id,
        reading_id=reading_id,
        actor_username="nurse",
    )
    second = service.ensure_candidate_for_reading(
        patient_link_id=patient_id,
        reading_id=reading_id,
        actor_username="nurse",
    )

    assert first["event_id"] == second["event_id"]
    assert len(first["versions"]) == 1
    assert db.execute(
        "SELECT COUNT(*) FROM hypoglycemia_shadow_event_versions"
    ).fetchone()[0] == 1


def test_source_delete_invalidates_candidate_and_deletes_reading_atomically(
    glucose_ingest_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "HYPOING006")
    service = _service(db)
    reading_id = service.add_vital_reading(
        patient_id,
        vtype="fbs",
        value=49,
        unit="mg/dL",
        measured_at="2026-08-01 08:50:00",
        recorded_by="nurse",
    )

    service.delete_vital_reading(
        patient_link_id=patient_id,
        reading_id=reading_id,
        actor_username="doctor",
    )

    assert db.execute(
        "SELECT COUNT(*) FROM vital_readings WHERE id=?", (reading_id,)
    ).fetchone()[0] == 0
    history = db.execute(
        """SELECT status, actor_username, note
           FROM hypoglycemia_shadow_event_versions
           WHERE source_system='vital_readings' AND source_record_id=?
           ORDER BY version_number""",
        (str(reading_id),),
    ).fetchall()
    assert [row["status"] for row in history] == [
        "CANDIDATE",
        "ENTERED_IN_ERROR",
    ]
    assert history[-1]["actor_username"] == "doctor"
    assert "deleted" in history[-1]["note"].lower()


def test_candidate_failure_rolls_back_source_reading(glucose_ingest_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow import ensure_hypoglycemia_shadow_storage
    from src.services.hypoglycemia_shadow_glucose_ingest import (
        HypoglycemiaShadowConflict,
    )

    db = get_db()
    patient_id = _patient(db, "HYPOING007")
    ensure_hypoglycemia_shadow_storage(db)
    db.executescript(
        """CREATE TRIGGER fail_low_glucose_candidate
           BEFORE INSERT ON hypoglycemia_shadow_event_versions
           WHEN NEW.version_number=1
           BEGIN SELECT RAISE(ABORT, 'simulated candidate failure'); END;"""
    )
    db.commit()

    with pytest.raises(HypoglycemiaShadowConflict):
        _service(db).add_vital_reading(
            patient_id,
            vtype="fbs",
            value=48,
            unit="mg/dL",
            measured_at="2026-08-01 09:00:00",
            recorded_by="nurse",
        )

    assert db.execute(
        "SELECT COUNT(*) FROM vital_readings WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM hypoglycemia_shadow_event_versions"
    ).fetchone()[0] == 0


def test_incomplete_shadow_storage_blocks_source_delete(glucose_ingest_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.vitals_repo import VitalsRepository
    from src.services.hypoglycemia_shadow_glucose_ingest import (
        HypoglycemiaShadowSourceIntegrityError,
    )

    db = get_db()
    patient_id = _patient(db, "HYPOING008")
    reading_id = VitalsRepository(db).add_reading(
        patient_id,
        vtype="fbs",
        value=47,
        unit="mg/dL",
        measured_at="2026-08-01 09:10:00",
        recorded_by="nurse",
    )
    db.execute(
        "CREATE TABLE hypoglycemia_shadow_event_versions (id INTEGER PRIMARY KEY)"
    )
    db.commit()

    with pytest.raises(HypoglycemiaShadowSourceIntegrityError):
        _service(db).delete_vital_reading(
            patient_link_id=patient_id,
            reading_id=reading_id,
            actor_username="doctor",
        )

    assert db.execute(
        "SELECT COUNT(*) FROM vital_readings WHERE id=?", (reading_id,)
    ).fetchone()[0] == 1


def test_vitals_api_creates_candidate_without_clinical_side_effects(
    glucose_ingest_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "HYPOING009")
    client = _login(glucose_ingest_app)

    response = client.post(
        f"/vitals/{patient_id}/add",
        data={"fbs": "52"},
    )

    assert response.status_code in {302, 303}
    reading = db.execute(
        """SELECT * FROM vital_readings
           WHERE patient_link_id=? AND type='fbs'""",
        (patient_id,),
    ).fetchone()
    event = db.execute(
        """SELECT * FROM hypoglycemia_shadow_event_versions
           WHERE source_system='vital_readings' AND source_record_id=?
             AND version_number=1""",
        (str(reading["id"]),),
    ).fetchone()
    assert event["status"] == "CANDIDATE"
    assert event["verification"] == "PROVISIONAL"
    assert db.execute("SELECT COUNT(*) FROM followup_tasks").fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM clinical_recommendation_events"
    ).fetchone()[0] == 0

    delete_response = client.post(
        f"/vitals/{patient_id}/reading/{reading['id']}/delete"
    )
    assert delete_response.status_code in {302, 303}
    assert db.execute(
        "SELECT COUNT(*) FROM vital_readings WHERE id=?", (reading["id"],)
    ).fetchone()[0] == 0
    assert db.execute(
        """SELECT status FROM hypoglycemia_shadow_event_versions
           WHERE source_system='vital_readings' AND source_record_id=?
           ORDER BY version_number DESC LIMIT 1""",
        (str(reading["id"]),),
    ).fetchone()["status"] == "ENTERED_IN_ERROR"
