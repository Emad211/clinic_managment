from __future__ import annotations

from datetime import timedelta

import pytest
from flask import url_for


@pytest.fixture()
def closed_loop_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.followups_repo import FollowupRepository
    from src.app import create_app
    from src.common.utils import iran_now

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "growth-closed-loop.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "growth-closed-loop-test",
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()
    now = iran_now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id,full_name,phone_number,enrolled_by,
                enrolled_at,updated_at)
               VALUES ('LOOP-001','بیمار حلقه','09129999999','pytest',?,?)""",
            (
                (now - timedelta(days=300)).isoformat(
                    sep=" ", timespec="seconds"
                ),
                now.isoformat(sep=" ", timespec="seconds"),
            ),
        ).lastrowid
    )
    db.commit()
    followups = FollowupRepository(db)
    task_id = followups.create(
        patient_id,
        reason="inactive_patient_recall",
        detail="بازیابی بیمار",
        due_date=now.isoformat(sep=" ", timespec="seconds"),
        source_rule="growth:inactive:test",
        source_event="inactive_patient_recall",
        fulfillment="remote",
    )
    appointments = AppointmentRepository(db)
    old_appointment_id = appointments.create(
        patient_id,
        scheduled_at=(now - timedelta(days=10)).isoformat(
            sep=" ", timespec="seconds"
        ),
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
        "patient_id": patient_id,
        "task_id": task_id,
        "old_appointment_id": old_appointment_id,
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


def test_past_stale_scheduled_appointment_does_not_close_recovery_task(
    closed_loop_app,
):
    from src.services.growth_closed_loop_service import GrowthClosedLoopService

    result = GrowthClosedLoopService(
        closed_loop_app["db"]
    ).reconcile_recovery_tasks()

    assert result["closed"] == 0
    assert result["waiting"] == 1
    row = closed_loop_app["db"].execute(
        "SELECT status,appointment_id FROM followup_tasks WHERE id=?",
        (closed_loop_app["task_id"],),
    ).fetchone()
    assert row["status"] == "open"
    assert row["appointment_id"] is None


def test_future_replacement_appointment_links_and_closes_recovery_task(
    closed_loop_app,
):
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.services.growth_closed_loop_service import GrowthClosedLoopService

    replacement_id = AppointmentRepository(closed_loop_app["db"]).create(
        closed_loop_app["patient_id"],
        scheduled_at=(closed_loop_app["now"] + timedelta(days=3)).isoformat(
            sep=" ", timespec="seconds"
        ),
        appt_type="visit",
        created_by="pytest",
    )
    result = GrowthClosedLoopService(
        closed_loop_app["db"]
    ).reconcile_recovery_tasks()

    assert result["closed"] == 1
    assert result["linked"] == 1
    row = closed_loop_app["db"].execute(
        "SELECT status,appointment_id,call_log FROM followup_tasks WHERE id=?",
        (closed_loop_app["task_id"],),
    ).fetchone()
    assert row["status"] == "done"
    assert int(row["appointment_id"]) == replacement_id
    assert "نوبت جایگزین ثبت شد" in row["call_log"]


def test_completed_visit_after_task_creation_closes_recovery_task(
    closed_loop_app,
):
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.services.growth_closed_loop_service import GrowthClosedLoopService

    repo = AppointmentRepository(closed_loop_app["db"])
    appointment_id = repo.create(
        closed_loop_app["patient_id"],
        scheduled_at=(closed_loop_app["now"] + timedelta(minutes=5)).isoformat(
            sep=" ", timespec="seconds"
        ),
        appt_type="visit",
        created_by="pytest",
    )
    repo.set_status(appointment_id, "done")

    result = GrowthClosedLoopService(
        closed_loop_app["db"]
    ).reconcile_recovery_tasks()
    row = closed_loop_app["db"].execute(
        "SELECT status,call_log FROM followup_tasks WHERE id=?",
        (closed_loop_app["task_id"],),
    ).fetchone()

    assert result["closed"] == 1
    assert row["status"] == "done"
    assert "مراجعه انجام شد" in row["call_log"]


def test_partial_collection_creates_one_task_and_collected_evidence_closes_it(
    closed_loop_app,
    monkeypatch,
):
    from src.services.growth_closed_loop_service import GrowthClosedLoopService

    service = GrowthClosedLoopService(closed_loop_app["db"])
    partial = {
        "accounting_invoice_id": 8101,
        "patient_link_id": closed_loop_app["patient_id"],
        "appointment_id": None,
        "invoice_status": "closed",
        "collection_state": "PARTIALLY_COLLECTED",
        "billed_amount": 1_000_000,
        "collected_amount": 400_000,
    }
    monkeypatch.setattr(service.finance, "latest_observations", lambda: [partial])
    first = service.reconcile_collection_tasks(assigned_to="admin")
    second = service.reconcile_collection_tasks(assigned_to="admin")

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["waiting"] == 1
    task = closed_loop_app["db"].execute(
        "SELECT * FROM followup_tasks WHERE source_rule='growth:collection:8101'"
    ).fetchone()
    assert task["status"] == "open"
    assert task["assigned_to"] == "admin"
    assert "مانده=600000" in task["detail"]

    collected = {
        **partial,
        "collection_state": "COLLECTED",
        "collected_amount": 1_000_000,
    }
    monkeypatch.setattr(service.finance, "latest_observations", lambda: [collected])
    final = service.reconcile_collection_tasks(assigned_to="admin")
    task = closed_loop_app["db"].execute(
        "SELECT status,call_log FROM followup_tasks WHERE id=?",
        (task["id"],),
    ).fetchone()

    assert final["closed"] == 1
    assert task["status"] == "done"
    assert "وصول نهایی مشاهده شد" in task["call_log"]


def test_missing_financial_observation_creates_exception_and_later_closes_it(
    closed_loop_app,
    monkeypatch,
):
    from src.services.growth_closed_loop_service import GrowthClosedLoopService

    service = GrowthClosedLoopService(closed_loop_app["db"])
    context = {
        "accounting_invoice_id": 8201,
        "patient_link_id": closed_loop_app["patient_id"],
        "appointment_id": None,
    }
    monkeypatch.setattr(service.finance, "eligible_invoice_contexts", lambda: [context])
    monkeypatch.setattr(service.finance, "latest_observations", lambda: [])
    created = service.reconcile_finance_observations(assigned_to="admin")

    assert created["created"] == 1
    task = closed_loop_app["db"].execute(
        """SELECT * FROM followup_tasks
           WHERE source_rule='growth:finance-observation:8201'"""
    ).fetchone()
    assert task["status"] == "open"
    assert task["reason"] == "financial_observation_missing"

    observation = {
        "accounting_invoice_id": 8201,
        "collection_state": "UNPAID",
    }
    monkeypatch.setattr(
        service.finance,
        "latest_observations",
        lambda: [observation],
    )
    closed = service.reconcile_finance_observations(assigned_to="admin")
    task = closed_loop_app["db"].execute(
        "SELECT status,call_log FROM followup_tasks WHERE id=?",
        (task["id"],),
    ).fetchone()

    assert closed["closed"] == 1
    assert task["status"] == "done"
    assert "مشاهده مالی ثبت شد" in task["call_log"]


def test_closed_loop_route_is_visible_and_post_redirects(closed_loop_app):
    client = _client(closed_loop_app)
    page = client.get(_url(closed_loop_app, "growth.automation"))
    response = client.post(
        _url(closed_loop_app, "growth.reconcile_closed_loop"),
        data={"assigned_to": "admin"},
        follow_redirects=False,
    )

    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "تطبیق نتیجه‌ها و وصول" in html
    assert "فقط Evidence موجود بررسی می‌شود" in html
    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith("/growth/automation")
