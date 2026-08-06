from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for


@pytest.fixture()
def automation_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.adapters.sqlite.core import get_db
    from src.app import create_app
    from src.common.utils import iran_now

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "growth-automation.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "growth-automation-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": True,
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()
    now = iran_now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    def patient(name: str, phone: str, enrolled_days_ago: int) -> int:
        enrolled = now - timedelta(days=enrolled_days_ago)
        return int(
            db.execute(
                """INSERT INTO patient_links
                   (national_id,full_name,phone_number,enrolled_by,enrolled_at,updated_at)
                   VALUES (NULL,?,?, 'pytest',?,?)""",
                (
                    name,
                    phone,
                    enrolled.isoformat(sep=" ", timespec="seconds"),
                    enrolled.isoformat(sep=" ", timespec="seconds"),
                ),
            ).lastrowid
        )

    no_show_patient = patient("بیمار عدم حضور", "09128888881", 300)
    cancelled_patient = patient("بیمار لغوشده", "09128888882", 300)
    protected_patient = patient("بیمار دارای نوبت آینده", "09128888883", 300)
    inactive_patient = patient("بیمار غیرفعال", "09128888884", 400)
    db.commit()

    appointments = AppointmentRepository(db)
    no_show_id = appointments.create(
        no_show_patient,
        scheduled_at=(now - timedelta(days=5)).isoformat(sep=" ", timespec="seconds"),
        appt_type="visit",
        created_by="pytest",
    )
    appointments.set_status(no_show_id, "no_show")
    cancelled_id = appointments.create(
        cancelled_patient,
        scheduled_at=(now - timedelta(days=2)).isoformat(sep=" ", timespec="seconds"),
        appt_type="visit",
        created_by="pytest",
    )
    appointments.set_status(cancelled_id, "cancelled")
    protected_cancelled_id = appointments.create(
        protected_patient,
        scheduled_at=(now - timedelta(days=3)).isoformat(sep=" ", timespec="seconds"),
        appt_type="visit",
        created_by="pytest",
    )
    appointments.set_status(protected_cancelled_id, "cancelled")
    appointments.create(
        protected_patient,
        scheduled_at=(now + timedelta(days=7)).isoformat(sep=" ", timespec="seconds"),
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
        "no_show_patient": no_show_patient,
        "cancelled_patient": cancelled_patient,
        "protected_patient": protected_patient,
        "inactive_patient": inactive_patient,
        "no_show_id": no_show_id,
        "cancelled_id": cancelled_id,
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


def test_no_show_recovery_creates_one_linked_task(automation_app):
    from src.services.growth_automation_service import GrowthAutomationService

    service = GrowthAutomationService(automation_app["db"])
    first = service.recover_no_shows(assigned_to="admin")
    second = service.recover_no_shows(assigned_to="admin")

    assert first["created"] == 1
    assert second["created"] == 0
    task = automation_app["db"].execute(
        """SELECT * FROM followup_tasks
           WHERE source_rule=?""",
        (f"growth:no-show:{automation_app['no_show_id']}",),
    ).fetchone()
    assert int(task["patient_link_id"]) == automation_app["no_show_patient"]
    assert int(task["appointment_id"]) == automation_app["no_show_id"]
    assert task["reason"] == "no_show_recovery"


def test_cancellation_with_future_appointment_is_not_recovered(automation_app):
    from src.services.growth_automation_service import GrowthAutomationService

    result = GrowthAutomationService(automation_app["db"]).recover_cancellations()

    assert result["created"] == 1
    created_patients = {
        int(row["patient_link_id"])
        for row in automation_app["db"].execute(
            """SELECT patient_link_id FROM followup_tasks
               WHERE reason='cancellation_recovery'"""
        ).fetchall()
    }
    assert automation_app["cancelled_patient"] in created_patients
    assert automation_app["protected_patient"] not in created_patients


def test_inactive_recall_excludes_patient_with_future_appointment(automation_app):
    from src.services.growth_automation_service import GrowthAutomationService

    result = GrowthAutomationService(automation_app["db"]).recall_inactive_patients(
        inactive_days=180,
        assigned_to="admin",
    )

    assert result["created"] >= 1
    recalled = {
        int(row["patient_link_id"])
        for row in automation_app["db"].execute(
            """SELECT patient_link_id FROM followup_tasks
               WHERE reason='inactive_patient_recall'"""
        ).fetchall()
    }
    assert automation_app["inactive_patient"] in recalled
    assert automation_app["protected_patient"] not in recalled


def test_run_all_is_idempotent_across_all_growth_automations(automation_app):
    from src.services.growth_automation_service import GrowthAutomationService

    service = GrowthAutomationService(automation_app["db"])
    first = service.run_all(inactive_days=180)
    count_after_first = automation_app["db"].execute(
        "SELECT COUNT(*) FROM followup_tasks WHERE source_rule LIKE 'growth:%'"
    ).fetchone()[0]
    second = service.run_all(inactive_days=180)
    count_after_second = automation_app["db"].execute(
        "SELECT COUNT(*) FROM followup_tasks WHERE source_rule LIKE 'growth:%'"
    ).fetchone()[0]

    assert count_after_first > 0
    assert count_after_second == count_after_first
    assert sum(part["created"] for part in second.values()) == 0


def test_automation_page_previews_and_runs_into_work_center(automation_app):
    client = _client(automation_app)
    preview = client.get(_url(automation_app, "growth.automation"))
    html = preview.get_data(as_text=True)

    assert preview.status_code == 200
    assert "اتوماسیون رشد و بازیابی" in html
    assert "عدم حضور بدون پیگیری" in html
    assert "ساخت کارها و ارسال به مرکز کارها" in html

    run = client.post(
        _url(automation_app, "growth.run_automation"),
        data={"inactive_days": "180", "assigned_to": "admin"},
        follow_redirects=False,
    )
    assert run.status_code in {302, 303}
    assert automation_app["db"].execute(
        "SELECT COUNT(*) FROM followup_tasks WHERE source_rule LIKE 'growth:%'"
    ).fetchone()[0] > 0


def test_growth_automation_never_sends_messages_directly():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    service = (
        root / "src/services/growth_automation_service.py"
    ).read_text(encoding="utf-8")

    assert "FollowupRepository" in service
    assert "SmsService" not in service
    assert "send_single" not in service
    assert "enqueue_approval" not in service
