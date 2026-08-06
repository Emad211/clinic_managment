from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for


@pytest.fixture()
def waitlist_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.adapters.sqlite.core import get_db
    from src.app import create_app
    from src.common.utils import iran_now

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "growth-waitlist.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "growth-waitlist-test",
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()
    now = iran_now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    patients = {}
    for key, name in (
        ("auto", "بیمار رزرو خودکار"),
        ("manual", "بیمار پیشنهاد دستی"),
        ("future", "بیمار دارای نوبت"),
    ):
        patients[key] = int(
            db.execute(
                """INSERT INTO patient_links
                   (national_id,full_name,phone_number,enrolled_by,
                    enrolled_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    f"WAIT-{key}",
                    name,
                    f"09131111{len(patients):03d}",
                    "pytest",
                    now.isoformat(sep=" ", timespec="seconds"),
                    now.isoformat(sep=" ", timespec="seconds"),
                ),
            ).lastrowid
        )
    db.commit()

    appointments = AppointmentRepository(db)
    slot_auto = appointments.create(
        patients["future"],
        scheduled_at=(now + timedelta(days=2)).replace(
            hour=10, minute=0, second=0, microsecond=0
        ).isoformat(sep=" ", timespec="seconds"),
        appt_type="visit",
        created_by="pytest",
    )
    appointments.set_status(slot_auto, "cancelled")
    slot_manual = appointments.create(
        patients["future"],
        scheduled_at=(now + timedelta(days=3)).replace(
            hour=15, minute=0, second=0, microsecond=0
        ).isoformat(sep=" ", timespec="seconds"),
        appt_type="followup",
        created_by="pytest",
    )
    appointments.set_status(slot_manual, "cancelled")
    appointments.create(
        patients["future"],
        scheduled_at=(now + timedelta(days=5)).replace(
            hour=11, minute=0, second=0, microsecond=0
        ).isoformat(sep=" ", timespec="seconds"),
        appt_type="visit",
        created_by="pytest",
    )

    admin = db.execute(
        "SELECT id,username FROM users WHERE username='admin'"
    ).fetchone()
    yield {
        "app": app,
        "db": db,
        "admin": admin,
        "patients": patients,
        "slot_auto": slot_auto,
        "slot_manual": slot_manual,
        "now": now,
    }
    context.pop()
    core._initialized = False


def _client(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def _url(fixture, endpoint: str, **values) -> str:
    with fixture["app"].test_request_context():
        return url_for(endpoint, **values)


def test_auto_fill_books_cancelled_slot_and_creates_notification_task(waitlist_app):
    from src.services.growth_waitlist_service import GrowthWaitlistService

    service = GrowthWaitlistService(waitlist_app["db"])
    entry = service.create_entry(
        patient_link_id=waitlist_app["patients"]["auto"],
        appt_type="visit",
        date_from=None,
        date_to=None,
        time_window="MORNING",
        auto_fill=True,
        priority=10,
        notes=None,
        created_by="admin",
    )
    result = service.fill_cancelled_slots(
        actor_username="admin",
        assigned_to="admin",
    )

    assert result["auto_booked"] == 1
    assert result["offers"] == 0
    current = service.repo.get(entry["id"])
    assert current["status"] == "BOOKED"
    assert current["booked_appointment_id"] is not None
    appointment = waitlist_app["db"].execute(
        "SELECT * FROM appointments WHERE id=?",
        (current["booked_appointment_id"],),
    ).fetchone()
    assert int(appointment["patient_link_id"]) == waitlist_app["patients"]["auto"]
    assert appointment["status"] == "scheduled"
    task = waitlist_app["db"].execute(
        """SELECT * FROM followup_tasks
           WHERE source_rule=?""",
        (f"growth:waitlist-auto:{waitlist_app['slot_auto']}",),
    ).fetchone()
    assert task["reason"] == "waitlist_auto_booked_notification"
    assert int(task["appointment_id"]) == int(current["booked_appointment_id"])


def test_consumed_cancelled_slot_is_not_filled_twice(waitlist_app):
    from src.services.growth_waitlist_service import GrowthWaitlistService

    service = GrowthWaitlistService(waitlist_app["db"])
    service.create_entry(
        patient_link_id=waitlist_app["patients"]["auto"],
        appt_type="visit",
        date_from=None,
        date_to=None,
        time_window="MORNING",
        auto_fill=True,
        priority=10,
        notes=None,
        created_by="admin",
    )
    first = service.fill_cancelled_slots(actor_username="admin")
    second = service.fill_cancelled_slots(actor_username="admin")

    assert first["auto_booked"] == 1
    assert second["auto_booked"] == 0
    assert waitlist_app["db"].execute(
        """SELECT COUNT(*) FROM growth_slot_fill_events
           WHERE cancelled_appointment_id=?""",
        (waitlist_app["slot_auto"],),
    ).fetchone()[0] == 1


def test_manual_waitlist_creates_offer_task_not_appointment(waitlist_app):
    from src.services.growth_waitlist_service import GrowthWaitlistService

    service = GrowthWaitlistService(waitlist_app["db"])
    entry = service.create_entry(
        patient_link_id=waitlist_app["patients"]["manual"],
        appt_type="followup",
        date_from=None,
        date_to=None,
        time_window="AFTERNOON",
        auto_fill=False,
        priority=20,
        notes="قبل از رزرو تماس بگیرید",
        created_by="admin",
    )
    result = service.fill_cancelled_slots(
        actor_username="admin",
        assigned_to="admin",
    )

    assert result["offers"] == 1
    current = service.repo.get(entry["id"])
    assert current["status"] == "OFFERED"
    assert current["booked_appointment_id"] is None
    task = waitlist_app["db"].execute(
        """SELECT * FROM followup_tasks
           WHERE source_rule=?""",
        (f"growth:waitlist-offer:{waitlist_app['slot_manual']}",),
    ).fetchone()
    assert task["status"] == "open"
    assert task["reason"] == "waitlist_slot_offer"


def test_accepting_manual_offer_creates_appointment_and_closes_task(waitlist_app):
    from src.services.growth_waitlist_service import GrowthWaitlistService

    service = GrowthWaitlistService(waitlist_app["db"])
    entry = service.create_entry(
        patient_link_id=waitlist_app["patients"]["manual"],
        appt_type="followup",
        date_from=None,
        date_to=None,
        time_window="AFTERNOON",
        auto_fill=False,
        priority=20,
        notes=None,
        created_by="admin",
    )
    service.fill_cancelled_slots(actor_username="admin", assigned_to="admin")
    result = service.book_offered_entry(entry["id"], actor_username="admin")

    assert result["appointment_id"]
    current = service.repo.get(entry["id"])
    assert current["status"] == "BOOKED"
    task = waitlist_app["db"].execute(
        """SELECT status,appointment_id,call_log FROM followup_tasks
           WHERE source_rule=?""",
        (f"growth:waitlist-offer:{waitlist_app['slot_manual']}",),
    ).fetchone()
    assert task["status"] == "done"
    assert int(task["appointment_id"]) == int(result["appointment_id"])
    assert "پیشنهاد پذیرفته شد" in task["call_log"]


def test_patient_with_future_appointment_is_not_waitlist_candidate(waitlist_app):
    from src.services.growth_waitlist_service import GrowthWaitlistService

    service = GrowthWaitlistService(waitlist_app["db"])
    service.create_entry(
        patient_link_id=waitlist_app["patients"]["future"],
        appt_type="visit",
        date_from=None,
        date_to=None,
        time_window="MORNING",
        auto_fill=True,
        priority=1,
        notes=None,
        created_by="admin",
    )
    result = service.fill_cancelled_slots(actor_username="admin")

    assert result["auto_booked"] == 0
    entry = service.repo.active_for_patient(waitlist_app["patients"]["future"])
    assert entry["status"] == "WAITING"


def test_waitlist_page_and_patient_context_render(waitlist_app):
    client = _client(waitlist_app)
    patient_id = waitlist_app["patients"]["auto"]
    response = client.get(
        _url(waitlist_app, "growth_waitlist.index", patient_id=patient_id)
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "صف انتظار و ظرفیت خالی" in html
    assert f'value="{patient_id}" selected' in html
    assert "رزرو خودکار مجاز است" in html
    assert "هر نوبت لغوشده فقط یک‌بار" in html
