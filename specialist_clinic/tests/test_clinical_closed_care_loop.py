"""Closed-care-loop safety, evidence and concurrency contracts."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_care_loop_repo import (
    ClinicalCareLoopConflict,
    ClinicalCareLoopRepository,
    ClinicalCareLoopValidationError,
)
from src.adapters.sqlite.clinical_care_loop_schema import (
    ensure_clinical_care_loop_storage,
)
from src.adapters.sqlite.followups_repo import FollowupRepository


@pytest.fixture()
def care_loop_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "care-loop.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "care-loop-test",
        }
    )
    context = app.app_context()
    context.push()
    ensure_clinical_care_loop_storage(core.get_db())
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id: str) -> int:
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by)
               VALUES (?, ?, 'pytest')""",
            (national_id, f"Care Loop {national_id}"),
        ).lastrowid
    )
    db.commit()
    return patient_id


def _task(db, patient_id: int, *, suffix: str = "a", due_period="2026-H1") -> int:
    task_id = int(
        db.execute(
            """INSERT INTO followup_tasks
               (patient_link_id, reason, detail, due_date, fulfillment,
                source_engine, clinical_semantic_key, clinical_context_hash,
                clinical_task_key, clinical_due_period)
               VALUES (?, 'monitoring', 'پیگیری آزمون', '2026-07-22',
                       'in_person', 'clinical_v2', ?, ?, ?, ?)""",
            (
                patient_id,
                f"monitoring:{suffix}",
                (suffix * 64)[:64],
                (f"{suffix}task" * 16)[:64],
                due_period,
            ),
        ).lastrowid
    )
    ClinicalCareLoopRepository.create_initial_event(
        db,
        task_id=task_id,
        due_at="2026-07-22",
        actor_username="clinical-followup",
        recorded_at=datetime(2026, 7, 20, 9, 0, 0),
    )
    db.commit()
    return task_id


def test_fresh_storage_projects_one_open_root(care_loop_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    task_id = _task(db, _patient(db, "LOOP001"))
    task = ClinicalCareLoopRepository().current_task(task_id)

    assert task["current_status"] == "OPEN"
    assert task["current_event"]["event_type"] == "CREATED"
    assert task["latest_outcome_event_id"] is None
    assert len(task["current_event"]["content_hash"]) == 64


def test_completion_requires_outcome_evidence_and_history_is_append_only(
    care_loop_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    task_id = _task(db, _patient(db, "LOOP002"))
    repo = ClinicalCareLoopRepository()
    root = repo.current_task(task_id)["current_event_id"]

    with pytest.raises(sqlite3.IntegrityError, match="invalid clinical task lifecycle"):
        repo.append_task_event(
            task_id,
            event_type="COMPLETED",
            expected_current_event_id=root,
            actor_username="doctor",
        )

    outcome = repo.record_outcome(
        task_id,
        outcome_type="LAB_COMPLETED",
        fact_key="lab.hba1c",
        value="7.1",
        unit="%",
        verification="CONFIRMED",
        actor_username="doctor",
        observed_at="2026-07-22 10:00:00",
        recorded_at=datetime(2026, 7, 22, 10, 5, 0),
        note="آزمایش در پرونده مشاهده شد",
    )
    completed = repo.append_task_event(
        task_id,
        event_type="COMPLETED",
        expected_current_event_id=root,
        actor_username="doctor",
        outcome_event_id=int(outcome["id"]),
        recorded_at=datetime(2026, 7, 22, 10, 6, 0),
    )

    assert completed["status"] == "COMPLETED"
    assert repo.current_task(task_id)["current_status"] == "COMPLETED"
    with pytest.raises(ClinicalCareLoopValidationError, match="non-terminal"):
        repo.record_outcome(
            task_id,
            outcome_type="OTHER",
            actor_username="doctor",
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE clinical_task_events SET note='changed' WHERE id=?",
            (completed["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute(
            "DELETE FROM clinical_outcome_events WHERE id=?",
            (outcome["id"],),
        )
    db.rollback()


def test_outcome_from_another_task_cannot_close_task(care_loop_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "LOOP003")
    first = _task(db, patient_id, suffix="b")
    second = _task(db, patient_id, suffix="c")
    repo = ClinicalCareLoopRepository()
    outcome = repo.record_outcome(
        first,
        outcome_type="OTHER",
        actor_username="doctor",
        note="شاهد مربوط به task اول",
    )

    with pytest.raises(sqlite3.IntegrityError, match="invalid clinical task lifecycle"):
        repo.append_task_event(
            second,
            event_type="COMPLETED",
            expected_current_event_id=repo.current_task(second)["current_event_id"],
            actor_username="doctor",
            outcome_event_id=int(outcome["id"]),
        )


def test_stale_form_and_terminal_reopen_are_rejected(care_loop_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    task_id = _task(db, _patient(db, "LOOP004"), suffix="d")
    repo = ClinicalCareLoopRepository()
    root = repo.current_task(task_id)["current_event_id"]
    assigned = repo.append_task_event(
        task_id,
        event_type="ASSIGNED",
        expected_current_event_id=root,
        actor_username="doctor",
        assigned_to="nurse-a",
    )
    with pytest.raises(ClinicalCareLoopConflict, match="changed after load"):
        repo.append_task_event(
            task_id,
            event_type="STARTED",
            expected_current_event_id=root,
            actor_username="doctor",
        )
    not_done = repo.append_task_event(
        task_id,
        event_type="NOT_DONE",
        expected_current_event_id=int(assigned["id"]),
        actor_username="doctor",
        disposition_code="PATIENT_DECLINED",
    )
    with pytest.raises(sqlite3.IntegrityError, match="invalid clinical task lifecycle"):
        repo.append_task_event(
            task_id,
            event_type="STARTED",
            expected_current_event_id=int(not_done["id"]),
            actor_username="doctor",
        )


def test_not_done_requires_explicit_disposition(care_loop_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    task_id = _task(db, _patient(db, "LOOP005"), suffix="e")
    repo = ClinicalCareLoopRepository()
    with pytest.raises(sqlite3.IntegrityError, match="invalid clinical task lifecycle"):
        repo.append_task_event(
            task_id,
            event_type="NOT_DONE",
            expected_current_event_id=repo.current_task(task_id)["current_event_id"],
            actor_username="doctor",
        )


def test_foreign_patient_appointment_is_rejected(care_loop_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    first_patient = _patient(db, "LOOP006")
    second_patient = _patient(db, "LOOP007")
    task_id = _task(db, first_patient, suffix="f")
    appointment_id = int(
        db.execute(
            """INSERT INTO appointments
               (patient_link_id, scheduled_at, status, created_by)
               VALUES (?, '2026-07-25 09:00:00', 'scheduled', 'pytest')""",
            (second_patient,),
        ).lastrowid
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="does not belong"):
        ClinicalCareLoopRepository().append_task_event(
            task_id,
            event_type="SCHEDULED",
            expected_current_event_id=(
                ClinicalCareLoopRepository().current_task(task_id)["current_event_id"]
            ),
            actor_username="doctor",
            appointment_id=appointment_id,
        )


def test_generic_repository_cannot_resolve_or_relink_clinical_task(care_loop_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    task_id = _task(db, _patient(db, "LOOP008"), suffix="g")
    repo = FollowupRepository()

    with pytest.raises(ValueError, match="append-only"):
        repo.resolve(task_id, "done")
    with pytest.raises(ValueError, match="append-only"):
        repo.set_appointment(task_id, None)
    assert ClinicalCareLoopRepository().current_task(task_id)["current_status"] == "OPEN"


def test_worklist_does_not_offer_legacy_done_for_clinical_task(care_loop_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    _task(db, _patient(db, "LOOP009"), suffix="h")
    client = care_loop_app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert response.status_code in {302, 303}

    page = client.get("/followups/")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "ثبت lifecycle / نتیجه" in html
    assert "برای تکمیل، ابتدا شاهد نتیجه ثبت شود" in html

    task_id = db.execute(
        "SELECT id FROM followup_tasks WHERE source_engine='clinical_v2'"
    ).fetchone()["id"]
    blocked = client.post(
        f"/followups/{task_id}/resolve",
        data={"status": "done"},
        follow_redirects=True,
    )
    assert "فقط از مسیر lifecycle" in blocked.get_data(as_text=True)
    assert ClinicalCareLoopRepository().current_task(task_id)["current_status"] == "OPEN"
