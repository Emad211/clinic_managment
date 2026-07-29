from __future__ import annotations

from datetime import datetime
import sqlite3

import pytest


@pytest.fixture()
def followup_state_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "followup-state.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "followup-state-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db, name="بیمار پیگیری") -> int:
    cursor = db.execute(
        "INSERT INTO patient_links(full_name, phone_number) VALUES (?, '09120000001')",
        (name,),
    )
    db.commit()
    return int(cursor.lastrowid)


def _admin_task(db, patient_id: int, reason="manual") -> int:
    cursor = db.execute(
        """INSERT INTO followup_tasks
           (patient_link_id, reason, detail, due_date, status, fulfillment)
           VALUES (?, ?, 'پیگیری تست', '2026-07-26', 'open', 'in_person')""",
        (patient_id, reason),
    )
    db.commit()
    return int(cursor.lastrowid)


def test_contact_events_are_idempotent_append_only_and_projected(followup_state_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.followup_operations_repo import (
        FollowupOperationsRepository,
    )
    from src.services.followup_contact_service import FollowupContactService
    from src.services.followup_projection_service import FollowupProjectionService

    db = get_db()
    patient_id = _patient(db)
    task_id = _admin_task(db, patient_id)
    service = FollowupContactService()
    first = service.record(
        task_id=task_id,
        channel="PHONE",
        outcome="NO_ANSWER",
        actor_username="admin",
        actor_user_id=1,
        idempotency_key="contact-test-idempotent-001",
        note="تماس اول",
        next_contact_at="2026-07-27 09:00:00",
    )
    repeated = service.record(
        task_id=task_id,
        channel="PHONE",
        outcome="NO_ANSWER",
        actor_username="admin",
        actor_user_id=1,
        idempotency_key="contact-test-idempotent-001",
        note="تماس اول",
        next_contact_at="2026-07-27 09:00:00",
    )
    assert first["id"] == repeated["id"]
    projected = FollowupProjectionService().open_tasks()
    task = next(row for row in projected if int(row["id"]) == task_id)
    assert task["is_open"] is True
    assert task["contact_count"] == 1
    assert task["last_contact_outcome"] == "NO_ANSWER"
    assert task["next_contact_at"] == "2026-07-27 09:00:00"

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE followup_contact_events SET outcome='REACHED' WHERE id=?",
            (first["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute("DELETE FROM followup_contact_events WHERE id=?", (first["id"],))
    db.rollback()
    assert len(FollowupOperationsRepository().list_for_task(task_id)) == 1


def test_callback_requires_next_contact_time(followup_state_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_contact_service import (
        FollowupContactService,
        FollowupContactValidationError,
    )

    db = get_db()
    task_id = _admin_task(db, _patient(db))
    with pytest.raises(FollowupContactValidationError, match="زمان تماس بعدی"):
        FollowupContactService().record(
            task_id=task_id,
            channel="PHONE",
            outcome="CALLBACK_REQUESTED",
            actor_username="admin",
            actor_user_id=1,
            idempotency_key="contact-callback-validation-001",
        )


def test_terminal_admin_task_is_not_reported_as_due_callback(followup_state_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.followups_repo import FollowupRepository
    from src.services.followup_contact_service import FollowupContactService
    from src.services.followup_projection_service import FollowupProjectionService

    db = get_db()
    task_id = _admin_task(db, _patient(db))
    FollowupContactService().record(
        task_id=task_id,
        channel="PHONE",
        outcome="CALLBACK_REQUESTED",
        actor_username="admin",
        actor_user_id=1,
        idempotency_key="callback-closed-task-001",
        next_contact_at="2026-07-27 09:00:00",
    )
    FollowupRepository().resolve(task_id, "done")

    summary = FollowupProjectionService().summary(as_of="2026-07-28")

    assert summary["due_callbacks"] == 0
    assert summary["callbacks"] == []


def test_booking_is_atomic_idempotent_and_does_not_complete_admin_task(
    followup_state_app,
):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_booking_service import FollowupBookingService

    db = get_db()
    patient_id = _patient(db)
    task_id = _admin_task(db, patient_id)
    service = FollowupBookingService(
        clock=lambda: datetime(2026, 7, 26, 10, 0, 0)
    )
    first = service.book(
        patient_link_id=patient_id,
        task_ids=[task_id],
        scheduled_at="2026-07-30 09:00:00",
        actor_username="admin",
        actor_user_id=1,
        idempotency_key="booking-idempotency-test-001",
    )
    second = service.book(
        patient_link_id=patient_id,
        task_ids=[task_id],
        scheduled_at="2026-07-30 09:00:00",
        actor_username="admin",
        actor_user_id=1,
        idempotency_key="booking-idempotency-test-001",
    )
    assert second["duplicate"] is True
    assert second["appointment_id"] == first["appointment_id"]
    task = db.execute("SELECT * FROM followup_tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "open"
    assert int(task["appointment_id"]) == first["appointment_id"]
    assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1
    contact = db.execute(
        "SELECT * FROM followup_contact_events WHERE task_id=?", (task_id,)
    ).fetchone()
    assert contact["outcome"] == "BOOKED"
    assert db.execute("SELECT COUNT(*) FROM followup_booking_requests").fetchone()[0] == 1


def test_booking_failure_rolls_back_appointment_task_and_contact(followup_state_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_booking_service import FollowupBookingService

    db = get_db()
    patient_id = _patient(db)
    task_id = _admin_task(db, patient_id)
    db.execute(
        """CREATE TRIGGER abort_contact_for_atomicity
           BEFORE INSERT ON followup_contact_events
           BEGIN SELECT RAISE(ABORT, 'simulated contact failure'); END"""
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="simulated contact failure"):
        FollowupBookingService().book(
            patient_link_id=patient_id,
            task_ids=[task_id],
            scheduled_at="2026-07-30 09:00:00",
            actor_username="admin",
            actor_user_id=1,
            idempotency_key="booking-rollback-test-001",
        )
    task = db.execute("SELECT * FROM followup_tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "open"
    assert task["appointment_id"] is None
    assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM followup_contact_events").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM followup_booking_requests").fetchone()[0] == 0


def test_completed_clinical_task_is_excluded_even_when_legacy_row_stays_open(
    followup_state_app,
):
    from test_clinical_engine_v2_followups import _patient as clinical_patient
    from test_clinical_engine_v2_followups import _run
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_care_loop_service import ClinicalCareLoopService
    from src.services.followup_engine import ClinicalV2FollowupService
    from src.services.followup_projection_service import FollowupProjectionService

    db = get_db()
    patient_id = clinical_patient(db, national_id="TEST0001")
    _run(patient_id)
    assert ClinicalV2FollowupService().generate_patient(patient_id)["created"] == 1
    task_id = int(db.execute("SELECT id FROM followup_tasks").fetchone()["id"])
    care = ClinicalCareLoopService()
    outcome = care.record_outcome(
        task_id,
        outcome_type="ENCOUNTER_COMPLETED",
        actor_username="admin",
        actor_user_id=1,
        verification="CONFIRMED",
        note="مراجعه انجام شد",
    )
    current = care.current(task_id)
    care.transition(
        task_id,
        transition="complete",
        expected_current_event_id=current["current_event_id"],
        actor_username="admin",
        actor_user_id=1,
        outcome_event_id=outcome["id"],
        note="بسته‌شدن با شاهد معتبر",
    )
    legacy = db.execute(
        "SELECT status FROM followup_tasks WHERE id=?", (task_id,)
    ).fetchone()["status"]
    assert legacy == "open"
    assert all(
        int(row["id"]) != task_id for row in FollowupProjectionService().open_tasks()
    )
    assert FollowupProjectionService().summary(as_of="2026-07-26")["open_tasks"] == 0


def test_worklist_shows_structured_contact_ui_and_staff_permission(
    followup_state_app,
):
    from src.adapters.sqlite.core import get_db
    from src.security.permissions import Permission, default_permissions
    from src.services.followup_contact_service import FollowupContactService

    db = get_db()
    patient_id = _patient(db)
    task_id = _admin_task(db, patient_id)
    FollowupContactService().record(
        task_id=task_id,
        channel="PHONE",
        outcome="REACHED",
        actor_username="admin",
        actor_user_id=1,
        idempotency_key="contact-worklist-render-001",
        note="بیمار پاسخ داد",
    )
    assert Permission.FOLLOWUP_CONTACT_RECORD in default_permissions("staff")
    client = followup_state_app.test_client()
    assert client.post(
        "/auth/login", data={"username": "admin", "password": "admin"}
    ).status_code in {302, 303}
    html = client.get("/followups/").get_data(as_text=True)
    assert "ثبت نتیجهٔ تماس" in html
    assert 'class="contact-result-details"' in html
    assert "contact-result-form" in html
    assert "contact-result-grid" in html
    assert "آخرین تماس" in html
    assert "پاسخ داد" in html
    assert "رزرو نوبت فقط مرحلهٔ BOOKED است" in html


def test_admin_followup_mutations_require_revocable_permissions(
    followup_state_app,
):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.security_permission_repo import (
        SecurityPermissionRepository,
    )
    from src.security.permissions import Permission, default_permissions

    db = get_db()
    patient_id = _patient(db)
    task_id = _admin_task(db, patient_id)
    admin = db.execute(
        "SELECT * FROM users WHERE username='admin'"
    ).fetchone()
    assert Permission.FOLLOWUP_ADMIN_MANAGE in default_permissions("staff")
    assert Permission.FOLLOWUP_BOOK_APPOINTMENT in default_permissions("staff")
    SecurityPermissionRepository().record(
        user_id=int(admin["id"]),
        permission=Permission.FOLLOWUP_ADMIN_MANAGE,
        effect="REVOKED",
        actor_username="admin",
        actor_user_id=int(admin["id"]),
        reason="test revocation",
        expected_current_event_id=None,
    )
    client = followup_state_app.test_client()
    assert client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    ).status_code in {302, 303}

    response = client.post(
        f"/followups/{task_id}/resolve",
        data={"status": "done"},
    )

    assert response.status_code in {302, 303}
    assert db.execute(
        "SELECT status FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()["status"] == "open"


def test_admin_followup_rejects_unknown_terminal_status(followup_state_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    task_id = _admin_task(db, _patient(db))
    client = followup_state_app.test_client()
    assert client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    ).status_code in {302, 303}

    response = client.post(
        f"/followups/{task_id}/resolve",
        data={"status": "hidden-by-typo"},
    )

    assert response.status_code in {302, 303}
    assert db.execute(
        "SELECT status FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()["status"] == "open"
