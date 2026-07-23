"""Longitudinal clinical-flag semantics, migration, UI and engine regressions."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_flag_common import ClinicalFlagConflict
from src.adapters.sqlite.clinical_flag_history_schema import (
    ensure_clinical_flag_history_storage,
)
from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
from src.domain.clinical_engine import FactStatus, VerificationStatus
from src.services.clinical_engine.fact_builder import FactBuilder


AT_1 = datetime(2026, 1, 10, 10, 0, 0)
AT_2 = datetime(2026, 2, 10, 10, 0, 0)
AT_3 = datetime(2026, 3, 10, 10, 0, 0)


@pytest.fixture()
def flag_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "flag-history.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "flag-history-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id: str) -> int:
    patient_id = int(db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, gender, birthdate, enrolled_by, enrolled_at)
           VALUES (?, ?, 'female', '1980-01-01', 'pytest',
                   '2026-01-01 09:00:00')""",
        (national_id, f"Patient {national_id}"),
    ).lastrowid)
    db.commit()
    return patient_id


def _definition(repo, key: str) -> dict:
    return next(item for item in repo.catalog() if item["flag_key"] == key)


def _append(
    repo,
    patient_id,
    updates,
    *,
    at,
    expected=None,
):
    hashes = {
        key: _definition(repo, key)["definition_hash"]
        for key in updates
    }
    return repo.append_batch(
        patient_id,
        updates,
        actor_username="doctor",
        expected_event_ids=(
            expected if expected is not None else {key: None for key in updates}
        ),
        expected_definition_hashes=hashes,
        effective_at=at,
        recorded_at=at,
        batch_id=f"pytest:{patient_id}:{at.isoformat()}:{','.join(sorted(updates))}",
    )


def test_false_unknown_and_not_asked_are_distinct_engine_facts(flag_app):
    from src.adapters.sqlite.core import get_db

    patient_id = _patient(get_db(), "FLAG0001")
    repo = ClinicalFlagsRepository()
    _append(
        repo,
        patient_id,
        {
            "pregnancy": {"state": "PRESENT", "value": False},
            "smoking": {"state": "UNKNOWN", "value": None},
        },
        at=AT_1,
    )

    states = repo.project_flags(patient_id, as_of_at=AT_1)
    assert states["pregnancy"]["state"] == "PRESENT"
    assert states["pregnancy"]["value"] is False
    assert states["smoking"]["state"] == "UNKNOWN"
    assert states["ascvd"]["state"] == "NOT_ASKED"

    snapshot = FactBuilder().build(patient_id, as_of_at=AT_1)
    pregnancy = next(f for f in snapshot.facts if f.key == "flag.pregnancy")
    smoking = next(f for f in snapshot.facts if f.key == "flag.smoking")
    ascvd = next(f for f in snapshot.facts if f.key == "flag.ascvd")
    assert pregnancy.status is FactStatus.PRESENT
    assert pregnancy.value is False
    assert pregnancy.verification is VerificationStatus.CONFIRMED
    assert smoking.status is FactStatus.UNKNOWN and smoking.value is None
    assert ascvd.status is FactStatus.NOT_ASKED and ascvd.value is None
    assert pregnancy.recorded_at == AT_1


def test_bitemporal_projection_does_not_rewrite_historical_knowledge(flag_app):
    from src.adapters.sqlite.core import get_db

    patient_id = _patient(get_db(), "FLAG0002")
    repo = ClinicalFlagsRepository()
    first = _append(
        repo,
        patient_id,
        {"pregnancy": {"state": "PRESENT", "value": True}},
        at=AT_1,
    )[0]
    second = _append(
        repo,
        patient_id,
        {
            "pregnancy": {
                "state": "PRESENT",
                "value": False,
                "effective_at": datetime(2026, 1, 1, 9, 0, 0),
            }
        },
        at=AT_2,
        expected={"pregnancy": first["id"]},
    )[0]

    historical = repo.project_flags(
        patient_id,
        as_of_at=datetime(2026, 1, 15, 12, 0, 0),
        knowledge_at=datetime(2026, 1, 15, 12, 0, 0),
    )
    current = repo.project_flags(patient_id, as_of_at=AT_3)
    assert historical["pregnancy"]["event_id"] == first["id"]
    assert historical["pregnancy"]["value"] is True
    assert current["pregnancy"]["event_id"] == second["id"]
    assert current["pregnancy"]["value"] is False


def test_stale_flag_in_batch_rolls_back_every_other_update(flag_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "FLAG0003")
    repo = ClinicalFlagsRepository()
    first = _append(
        repo,
        patient_id,
        {"pregnancy": {"state": "PRESENT", "value": False}},
        at=AT_1,
    )[0]
    _append(
        repo,
        patient_id,
        {"pregnancy": {"state": "PRESENT", "value": True}},
        at=AT_2,
        expected={"pregnancy": first["id"]},
    )
    before = db.execute(
        "SELECT COUNT(*) AS count FROM clinical_flag_events"
    ).fetchone()["count"]

    with pytest.raises(ClinicalFlagConflict):
        _append(
            repo,
            patient_id,
            {
                "pregnancy": {"state": "PRESENT", "value": False},
                "smoking": {"state": "PRESENT", "value": "never"},
            },
            at=AT_3,
            expected={"pregnancy": first["id"], "smoking": None},
        )
    after = db.execute(
        "SELECT COUNT(*) AS count FROM clinical_flag_events"
    ).fetchone()["count"]
    assert after == before
    assert repo.project_flags(patient_id, as_of_at=AT_3)["smoking"]["state"] == "NOT_ASKED"


def test_catalog_presentation_edit_is_stable_but_semantic_edit_requires_review(flag_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "FLAG0004")
    repo = ClinicalFlagsRepository()
    _append(
        repo,
        patient_id,
        {"pregnancy": {"state": "PRESENT", "value": False}},
        at=AT_1,
    )
    revision = db.execute(
        "SELECT clinical_data_revision FROM patient_links WHERE id=?",
        (patient_id,),
    ).fetchone()["clinical_data_revision"]

    db.execute(
        "UPDATE flag_catalog SET label='بارداری فعلی' WHERE flag_key='pregnancy'"
    )
    db.commit()
    assert db.execute(
        "SELECT clinical_data_revision FROM patient_links WHERE id=?",
        (patient_id,),
    ).fetchone()["clinical_data_revision"] == revision
    assert repo.project_flags(patient_id, as_of_at=AT_3)["pregnancy"]["state"] == "PRESENT"

    repo.update_catalog_semantics(
        "pregnancy",
        flag_type="text",
        is_active=True,
    )
    changed = repo.project_flags(patient_id, as_of_at=AT_3)["pregnancy"]
    assert changed["state"] == "UNKNOWN"
    assert changed["verification"] == "UNVERIFIED"
    assert "FLAG_DEFINITION_CHANGED_REVIEW_REQUIRED" in changed["warnings"]


def test_database_guards_event_immutability_and_enum_contract(flag_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "FLAG0005")
    repo = ClinicalFlagsRepository()
    event = _append(
        repo,
        patient_id,
        {"smoking": {"state": "PRESENT", "value": "never"}},
        at=AT_1,
    )[0]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE clinical_flag_events SET status='UNKNOWN' WHERE id=?",
            (event["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "DELETE FROM clinical_flag_events WHERE id=?",
            (event["id"],),
        )
    db.rollback()

    definition = _definition(repo, "smoking")
    with pytest.raises(sqlite3.IntegrityError, match="value violates"):
        db.execute(
            """INSERT INTO clinical_flag_events
               (patient_link_id, flag_key, status, value_json, flag_type,
                definition_hash, verification, source, actor_username,
                effective_at, recorded_at, batch_id, supersedes_event_id)
               VALUES (?, 'smoking', 'PRESENT', ?, 'enum', ?,
                       'CONFIRMED', 'clinician', 'doctor', ?, ?, 'invalid-enum', ?)""",
            (
                patient_id,
                '"not-in-catalog"',
                definition["definition_hash"],
                "2026-02-10 10:00:00",
                "2026-02-10 10:00:00",
                event["id"],
            ),
        )
    db.rollback()


def test_legacy_false_value_migrates_without_becoming_not_asked(tmp_path):
    db = sqlite3.connect(tmp_path / "legacy-flags.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE users(id INTEGER PRIMARY KEY);
        CREATE TABLE patient_links(
          id INTEGER PRIMARY KEY,
          clinical_data_revision INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE flag_catalog(
          id INTEGER PRIMARY KEY,
          flag_key TEXT UNIQUE NOT NULL,
          label TEXT NOT NULL,
          flag_type TEXT NOT NULL,
          options TEXT,
          category TEXT NOT NULL DEFAULT 'other',
          display_order INTEGER NOT NULL DEFAULT 100,
          is_active INTEGER NOT NULL DEFAULT 1,
          notes TEXT
        );
        CREATE TABLE patient_flags(
          id INTEGER PRIMARY KEY,
          patient_link_id INTEGER NOT NULL,
          flag_key TEXT NOT NULL,
          value TEXT,
          recorded_by TEXT,
          updated_at TEXT
        );
        INSERT INTO patient_links(id) VALUES(1);
        INSERT INTO flag_catalog(id,flag_key,label,flag_type)
          VALUES(1,'pregnancy','Pregnancy','bool');
        INSERT INTO patient_flags
          (id,patient_link_id,flag_key,value,recorded_by,updated_at)
          VALUES(7,1,'pregnancy','0','legacy-user','2026-01-01 09:00:00');
        """
    )
    result = ensure_clinical_flag_history_storage(db)
    event = db.execute(
        "SELECT * FROM clinical_flag_events WHERE source_record_id='patient_flags:7'"
    ).fetchone()
    assert result["migrated"] == 1
    assert event["status"] == "PRESENT"
    assert event["value_json"] == "false"
    assert event["verification"] == "PROVISIONAL"
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='patient_flags'"
    ).fetchone() is None


def test_patient_flag_form_is_four_state_and_rejects_stale_submission(flag_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "FLAG0006")
    smoking = db.execute(
        "SELECT definition_hash FROM flag_catalog WHERE flag_key='smoking'"
    ).fetchone()
    client = flag_app.test_client()
    assert client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    ).status_code in {302, 303}

    page = client.get(f"/patients/{patient_id}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "PRESENT_TRUE" in html
    assert "PRESENT_FALSE" in html
    assert "NOT_ASKED" in html

    payload = {
        "flag_section": "lifestyle",
        "flag_keys": "smoking",
        "flag__smoking__state": "PRESENT",
        "flag__smoking__value": "current",
        "flag__smoking__event_id": "",
        "flag__smoking__definition_hash": smoking["definition_hash"],
    }
    first = client.post(
        f"/patients/{patient_id}/flags",
        data=payload,
        follow_redirects=True,
    )
    assert first.status_code == 200
    count = db.execute(
        "SELECT COUNT(*) AS count FROM clinical_flag_events WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["count"]
    stale = client.post(
        f"/patients/{patient_id}/flags",
        data=payload,
        follow_redirects=True,
    )
    assert "هم‌زمان تغییر کرده" in stale.get_data(as_text=True)
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_flag_events WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["count"] == count


def test_reactivation_cannot_make_a_pre_change_answer_valid_again(flag_app):
    from src.adapters.sqlite.core import get_db

    patient_id = _patient(get_db(), "FLAG0007")
    repo = ClinicalFlagsRepository()
    event = _append(
        repo,
        patient_id,
        {"pregnancy": {"state": "PRESENT", "value": False}},
        at=AT_1,
    )[0]
    first_definition = _definition(repo, "pregnancy")

    disabled = repo.update_catalog_semantics(
        "pregnancy",
        flag_type="bool",
        is_active=False,
    )
    assert disabled["definition_version"] == first_definition["definition_version"] + 1
    reactivated = repo.update_catalog_semantics(
        "pregnancy",
        flag_type="bool",
        is_active=True,
    )
    assert reactivated["definition_version"] == disabled["definition_version"] + 1
    assert reactivated["definition_hash"] != first_definition["definition_hash"]

    projected = repo.project_flags(patient_id, as_of_at=AT_3)["pregnancy"]
    assert projected["event_id"] == event["id"]
    assert projected["state"] == "UNKNOWN"
    assert "FLAG_DEFINITION_CHANGED_REVIEW_REQUIRED" in projected["warnings"]


def test_invalid_calendar_date_is_rejected_by_database_guard(flag_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "FLAG0008")
    definition = db.execute(
        "SELECT * FROM flag_catalog WHERE flag_key='eye_exam_date'"
    ).fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="value violates"):
        db.execute(
            """INSERT INTO clinical_flag_events
               (patient_link_id, flag_key, status, value_json, flag_type,
                definition_hash, verification, source, actor_username,
                effective_at, recorded_at, batch_id)
               VALUES (?, 'eye_exam_date', 'PRESENT', '"2026-02-30"',
                       'date', ?, 'CONFIRMED', 'clinician', 'doctor',
                       '2026-02-10 10:00:00', '2026-02-10 10:00:00',
                       'invalid-calendar-date')""",
            (patient_id, definition["definition_hash"]),
        )
    db.rollback()


def test_orphan_legacy_flag_aborts_migration_without_dropping_source(tmp_path):
    # Keep the callable and exception class on the same module object. Several app
    # factory tests intentionally rebuild module state; importing one symbol at
    # collection time and the other inside the test can otherwise create a false
    # negative if a module reload occurs in the same pytest process.
    from src.adapters.sqlite import clinical_flag_history_schema as flag_schema

    db = sqlite3.connect(tmp_path / "orphan-legacy-flag.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE users(id INTEGER PRIMARY KEY);
        CREATE TABLE patient_links(
          id INTEGER PRIMARY KEY,
          clinical_data_revision INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE flag_catalog(
          id INTEGER PRIMARY KEY,
          flag_key TEXT UNIQUE NOT NULL,
          flag_type TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE patient_flags(
          id INTEGER PRIMARY KEY,
          patient_link_id INTEGER NOT NULL,
          flag_key TEXT NOT NULL,
          value TEXT,
          recorded_by TEXT,
          updated_at TEXT
        );
        INSERT INTO patient_links(id) VALUES(1);
        INSERT INTO patient_flags
          (id,patient_link_id,flag_key,value,recorded_by,updated_at)
          VALUES(11,1,'missing-definition','1','legacy-user',
                 '2026-01-01 09:00:00');
        """
    )
    with pytest.raises(
        flag_schema.ClinicalFlagHistoryMigrationError,
        match="without a catalog definition",
    ):
        flag_schema.ensure_clinical_flag_history_storage(db)
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='patient_flags'"
    ).fetchone() is not None
    assert db.execute(
        "SELECT COUNT(*) AS count FROM patient_flags"
    ).fetchone()["count"] == 1
