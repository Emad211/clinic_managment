from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from flask import url_for


@pytest.fixture()
def messaging_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.followups_repo import FollowupRepository
    from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
    from src.app import create_app
    from src.common.utils import iran_now

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "growth-messaging.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "growth-messaging-test",
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()
    now = iran_now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    patients = {}
    for key, phone in (
        ("no_show", "09132222001"),
        ("recall", "09132222002"),
        ("no_phone", None),
        ("reminder", "09132222004"),
    ):
        patients[key] = int(
            db.execute(
                """INSERT INTO patient_links
                   (national_id,full_name,phone_number,enrolled_by,
                    enrolled_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    f"MSG-{key}",
                    f"بیمار پیام {key}",
                    phone,
                    "pytest",
                    (now - timedelta(days=200)).isoformat(
                        sep=" ", timespec="seconds"
                    ),
                    now.isoformat(sep=" ", timespec="seconds"),
                ),
            ).lastrowid
        )
        SmsGovernanceRepository(db).ensure_patient_defaults(
            patients[key],
            actor_username="pytest",
        )
    db.commit()

    followups = FollowupRepository(db)
    tasks = {
        "no_show": followups.create(
            patients["no_show"],
            reason="no_show_recovery",
            detail="نوبت قبلی انجام نشد",
            due_date=now.isoformat(sep=" ", timespec="seconds"),
            source_rule="growth:no-show:501",
            source_event="appointment_no_show",
            fulfillment="remote",
        ),
        "recall": followups.create(
            patients["recall"],
            reason="inactive_patient_recall",
            detail="بیش از شش ماه بدون مراجعه",
            due_date=now.isoformat(sep=" ", timespec="seconds"),
            source_rule="growth:inactive:502:2026-08",
            source_event="inactive_patient_recall",
            fulfillment="remote",
        ),
        "no_phone": followups.create(
            patients["no_phone"],
            reason="cancellation_recovery",
            detail="نوبت لغو شد",
            due_date=now.isoformat(sep=" ", timespec="seconds"),
            source_rule="growth:cancelled:503",
            source_event="appointment_cancelled",
            fulfillment="remote",
        ),
    }
    reminder_appointment = int(
        db.execute(
            """INSERT INTO appointments
               (patient_link_id,scheduled_at,appt_type,status,created_by)
               VALUES (?,?,'visit','scheduled','pytest')""",
            (
                patients["reminder"],
                (now + timedelta(hours=12)).isoformat(
                    sep=" ", timespec="seconds"
                ),
            ),
        ).lastrowid
    )
    db.commit()

    admin = db.execute(
        "SELECT id,username FROM users WHERE username='admin'"
    ).fetchone()
    yield {
        "app": app,
        "db": db,
        "admin": admin,
        "patients": patients,
        "tasks": tasks,
        "reminder_appointment": reminder_appointment,
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


def test_playbook_seeds_manager_editable_growth_events(messaging_app):
    from src.services.growth_messaging_playbook_service import (
        GrowthMessagingPlaybookService,
    )

    GrowthMessagingPlaybookService(messaging_app["db"])
    rows = messaging_app["db"].execute(
        """SELECT event_key,channel,cooldown_days,is_active
           FROM engagement_events
           WHERE event_key LIKE 'growth_%' ORDER BY event_key"""
    ).fetchall()

    assert {row["event_key"] for row in rows} == {
        "growth_cancellation_recovery",
        "growth_inactive_recall",
        "growth_no_show_recovery",
        "growth_waitlist_auto_booked",
        "growth_waitlist_offer",
    }
    assert all(row["channel"] == "sms" for row in rows)
    assert all(int(row["is_active"]) == 1 for row in rows)


def test_valid_growth_tasks_queue_once_through_existing_approval_pipeline(
    messaging_app,
):
    from src.services.growth_messaging_playbook_service import (
        GrowthMessagingPlaybookService,
    )

    service = GrowthMessagingPlaybookService(messaging_app["db"])
    first = service.run(actor_username="admin")
    second = service.run(actor_username="admin")

    assert first["queued"] >= 2
    assert second["queued"] == 0
    assert second["existing"] >= 2
    approvals = messaging_app["db"].execute(
        """SELECT event_key,period_key,status
           FROM engagement_approvals
           WHERE event_key IN (
             'growth_no_show_recovery','growth_inactive_recall'
           ) ORDER BY event_key"""
    ).fetchall()
    assert len(approvals) == 2
    assert all(row["status"] == "pending" for row in approvals)
    assert {
        row["period_key"] for row in approvals
    } == {
        "growth:no-show:501",
        "growth:inactive:502:2026-08",
    }


def test_booking_stop_condition_rejects_pending_no_show_message(messaging_app):
    from src.services.growth_messaging_playbook_service import (
        GrowthMessagingPlaybookService,
    )

    service = GrowthMessagingPlaybookService(messaging_app["db"])
    service.run(actor_username="admin")
    messaging_app["db"].execute(
        """INSERT INTO appointments
           (patient_link_id,scheduled_at,appt_type,status,created_by)
           VALUES (?,?,'visit','scheduled','pytest')""",
        (
            messaging_app["patients"]["no_show"],
            (messaging_app["now"] + timedelta(days=4)).isoformat(
                sep=" ", timespec="seconds"
            ),
        ),
    )
    messaging_app["db"].commit()

    result = service.run(actor_username="admin")
    approval = messaging_app["db"].execute(
        """SELECT status,decided_by FROM engagement_approvals
           WHERE event_key='growth_no_show_recovery'
             AND period_key='growth:no-show:501'"""
    ).fetchone()

    assert result["stopped_pending"] >= 1
    assert result["stop_reasons"]["BOOKED"] >= 1
    assert approval["status"] == "rejected"
    assert approval["decided_by"] == "system:growth-stop-condition"


def test_appointment_reminder_is_queued_then_stopped_after_cancellation(
    messaging_app,
):
    from src.services.growth_messaging_playbook_service import (
        GrowthMessagingPlaybookService,
    )

    service = GrowthMessagingPlaybookService(messaging_app["db"])
    service.run(actor_username="admin")
    period = f"appt:{messaging_app['reminder_appointment']}"
    approval = messaging_app["db"].execute(
        """SELECT * FROM engagement_approvals
           WHERE event_key='appointment_reminder' AND period_key=?""",
        (period,),
    ).fetchone()
    assert approval
    assert approval["status"] == "pending"

    messaging_app["db"].execute(
        "UPDATE appointments SET status='cancelled' WHERE id=?",
        (messaging_app["reminder_appointment"],),
    )
    messaging_app["db"].commit()
    result = service.run(actor_username="admin")
    approval = messaging_app["db"].execute(
        "SELECT status,decided_by FROM engagement_approvals WHERE id=?",
        (approval["id"],),
    ).fetchone()

    assert result["stopped_pending"] >= 1
    assert approval["status"] == "rejected"
    assert approval["decided_by"] == "system:growth-stop-condition"


def test_missing_phone_and_disabled_event_do_not_queue_messages(messaging_app):
    from src.services.growth_messaging_playbook_service import (
        GrowthMessagingPlaybookService,
    )

    service = GrowthMessagingPlaybookService(messaging_app["db"])
    messaging_app["db"].execute(
        """UPDATE engagement_events SET channel='off'
           WHERE event_key='growth_inactive_recall'"""
    )
    messaging_app["db"].commit()
    result = service.run(actor_username="admin")

    assert result["skipped"] >= 2
    assert messaging_app["db"].execute(
        """SELECT COUNT(*) FROM engagement_approvals
           WHERE patient_link_id=?
             AND event_key='growth_cancellation_recovery'""",
        (messaging_app["patients"]["no_phone"],),
    ).fetchone()[0] == 0
    assert messaging_app["db"].execute(
        """SELECT COUNT(*) FROM engagement_approvals
           WHERE event_key='growth_inactive_recall'"""
    ).fetchone()[0] == 0


def test_growth_message_route_queues_approvals_not_sms_messages(messaging_app):
    client = _client(messaging_app)
    before_sms = messaging_app["db"].execute(
        "SELECT COUNT(*) FROM sms_messages"
    ).fetchone()[0]
    response = client.post(
        _url(messaging_app, "growth.run_messaging_playbooks"),
        follow_redirects=False,
    )
    after_sms = messaging_app["db"].execute(
        "SELECT COUNT(*) FROM sms_messages"
    ).fetchone()[0]
    pending = messaging_app["db"].execute(
        "SELECT COUNT(*) FROM engagement_approvals WHERE status='pending'"
    ).fetchone()[0]

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith("/growth/automation")
    assert after_sms == before_sms
    assert pending > 0


def test_playbook_source_has_no_direct_sms_send_path():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "src/services/growth_messaging_playbook_service.py"
    ).read_text(encoding="utf-8")

    assert "enqueue_event_for_patient" in source
    assert "send_single" not in source
    assert "add_message" not in source
    assert "sms_messages" not in source
