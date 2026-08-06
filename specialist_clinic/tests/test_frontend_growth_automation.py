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
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()
    now = iran_now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    patients = {}
    for key, name, enrolled_at in (
        ("no_show", "بیمار عدم حضور", now - timedelta(days=60)),
        ("cancelled", "بیمار لغوشده", now - timedelta(days=90)),
        ("inactive", "بیمار غیرفعال", now - timedelta(days=400)),
        ("future", "بیمار دارای نوبت آینده", now - timedelta(days=400)),
    ):
        patients[key] = int(
            db.execute(
                """INSERT INTO patient_links
                   (national_id,full_name,phone_number,enrolled_by,
                    enrolled_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    f"AUTO-{key}",
                    name,
                    f"09128888{len(patients):03d}",
                    "pytest",
                    enrolled_at.isoformat(sep=" ", timespec="seconds"),
                    enrolled_at.isoformat(sep=" ", timespec="seconds"),
                ),
            ).lastrowid
        )
    db.commit()

    appointments = AppointmentRepository(db)
    no_show_id = appointments.create(
        patients["no_show"],
        scheduled_at=(now - timedelta(days=3)).isoformat(sep=" ", timespec="seconds"),
        appt_type="visit",
        created_by="pytest",
    )
    appointments.set_status(no_show_id, "no_show")
    cancelled_id = appointments.create(
        patients["cancelled"],
        scheduled_at=(now - timedelta(days=2)).isoformat(sep=" ", timespec="seconds"),
        appt_type="visit",
        created_by="pytest",
    )
    appointments.set_status(cancelled_id, "cancelled")
    appointments.create(
        patients["future"],
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
        "patients": patients,
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


def test_no_show_recovery_is_idempotent_and_links_appointment(automation_app):
    from src.services.growth_automation_service import GrowthAutomationService

    service = GrowthAutomationService(automation_app["db"])
    first = service.recover_no_shows(assigned_to="admin")
    second = service.recover_no_shows(assigned_to="admin")

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["duplicates"] == 1
    row = automation_app["db"].execute(
        """SELECT reason,source_rule,appointment_id,assigned_to,status
           FROM followup_tasks WHERE source_rule=?""",
        (f"growth:no-show:{automation_app['no_show_id']}",),
    ).fetchone()
    assert row["reason"] == "no_show_recovery"
    assert int(row["appointment_id"]) == automation_app["no_show_id"]
    assert row["assigned_to"] == "admin"
    assert row["status"] == "open"


def test_cancelled_patient_with_no_replacement_gets_one_task(automation_app):
    from src.services.growth_automation_service import GrowthAutomationService

    result = GrowthAutomationService(automation_app["db"]).recover_cancellations()

    assert result["created"] == 1
    row = automation_app["db"].execute(
        "SELECT * FROM followup_tasks WHERE source_rule=?",
        (f"growth:cancelled:{automation_app['cancelled_id']}",),
    ).fetchone()
    assert row
    assert row["reason"] == "cancellation_recovery"


def test_inactive_recall_excludes_patient_with_future_appointment(automation_app):
    from src.services.growth_automation_service import GrowthAutomationService

    result = GrowthAutomationService(automation_app["db"]).recall_inactive_patients(
        inactive_days=180
    )

    assert result["created"] >= 1
    recalled_ids = {
        int(row["patient_link_id"])
        for row in automation_app["db"].execute(
            """SELECT patient_link_id FROM followup_tasks
               WHERE reason='inactive_patient_recall'"""
        ).fetchall()
    }
    assert automation_app["patients"]["inactive"] in recalled_ids
    assert automation_app["patients"]["future"] not in recalled_ids


def test_preview_does_not_write_tasks(automation_app):
    from src.services.growth_automation_service import GrowthAutomationService

    before = automation_app["db"].execute(
        "SELECT COUNT(*) FROM followup_tasks"
    ).fetchone()[0]
    preview = GrowthAutomationService(automation_app["db"]).preview(
        inactive_days=180
    )
    after = automation_app["db"].execute(
        "SELECT COUNT(*) FROM followup_tasks"
    ).fetchone()[0]

    assert preview["no_show"] == 1
    assert preview["cancelled"] == 1
    assert preview["inactive"] >= 1
    assert after == before


def test_automation_page_previews_and_run_redirects(automation_app):
    client = _client(automation_app)
    page = client.get(_url(automation_app, "growth.automation"))
    run = client.post(
        _url(automation_app, "growth.run_automation"),
        data={"inactive_days": "180", "assigned_to": "admin"},
        follow_redirects=False,
    )

    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "اتوماسیون رشد و بازیابی" in html
    assert "عدم حضور بدون پیگیری" in html
    assert "پیام خودکار در این مرحله ارسال نمی‌شود" in html
    assert run.status_code in {302, 303}
    assert run.headers["Location"].endswith("/growth/automation?inactive_days=180")
