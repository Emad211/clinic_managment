from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def action_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app
    from src.services.followup_orchestration.backfill import (
        FollowupEpisodeBackfillService,
    )
    from src.services.followup_orchestration.projection_service import (
        FollowupProjectionService,
    )

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "work-actions.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "work-actions-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": True,
            "FOLLOWUP_AUTO_ROUTING": True,
            "FOLLOWUP_STRUCTURED_CONTACT": True,
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()

    for index in range(1, 4):
        patient_id = int(
            db.execute(
                """INSERT INTO patient_links
                   (national_id, full_name, phone_number, enrolled_by,
                    enrolled_at, updated_at)
                   VALUES (?, ?, ?, 'pytest',
                           '2026-08-05 08:00:00', '2026-08-05 08:00:00')""",
                (
                    f"WCA2{index:06d}",
                    f"بیمار اقدام مرکز کار {index}",
                    f"0912111111{index}",
                ),
            ).lastrowid
        )
        db.execute(
            """INSERT INTO followup_tasks
               (patient_link_id, due_date, reason, detail, status,
                source_event, fulfillment, created_at)
               VALUES (?, '2026-08-05', 'manual', ?, 'open',
                       'manual', 'remote', '2026-08-05 08:05:00')""",
            (patient_id, f"اقدام تست {index}"),
        )
    db.commit()

    FollowupEpisodeBackfillService(db).run(apply=True)
    FollowupProjectionService(db).run(
        as_of_at="2026-08-05 12:00:00",
        apply=True,
    )
    rows = db.execute(
        """SELECT projection.episode_id, link.source_id AS task_id
           FROM followup_work_item_projection projection
           JOIN followup_episode_links link
             ON link.episode_id=projection.episode_id
            AND link.source_type='ADMIN_TASK'
           WHERE projection.state_class<>'TERMINAL'
           ORDER BY projection.episode_id"""
    ).fetchall()
    assert len(rows) == 3
    admin = db.execute(
        """SELECT id, username, full_name, role, is_active
           FROM users WHERE username='admin'"""
    ).fetchone()

    yield {
        "app": app,
        "db": db,
        "admin": admin,
        "episodes": [str(row["episode_id"]) for row in rows],
        "tasks": [int(row["task_id"]) for row in rows],
    }

    context.pop()
    core._initialized = False


def client_for(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def jalali_day(days: int) -> str:
    from src.common.utils import gregorian_to_jalali, iran_now

    target = (iran_now() + timedelta(days=days)).date()
    year, month, day = gregorian_to_jalali(
        target.year,
        target.month,
        target.day,
    )
    return f"{year}/{month:02d}/{day:02d}"


def test_work_item_renders_only_authoritative_in_context_actions(action_app):
    response = client_for(action_app).get(
        f"/followups/unified/{action_app['episodes'][0]}?view=all"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "اقدام بعدی" in html
    assert "فردا" in html
    assert "سه روز بعد" in html
    assert "یک هفته بعد" in html
    assert "ثبت نوبت ویزیت" in html
    assert "تکمیل و رفتن به کار بعدی" in html
    assert "followups.work_center_defer" not in html
    assert "/followups/work-center/" in html
    assert "پیگیری بالینی همچنان به شاهد معتبر نیاز دارد" in html


def test_defer_updates_authoritative_task_projection_and_opens_next(action_app):
    episode_id = action_app["episodes"][0]
    task_id = action_app["tasks"][0]
    next_url = f"/followups/unified/{action_app['episodes'][1]}?view=all"
    response = client_for(action_app).post(
        f"/followups/work-center/{episode_id}/defer",
        data={
            "defer_days": "3",
            "idempotency_key": "work-center-defer-admin-0001",
            "current_url": f"/followups/unified/{episode_id}?view=all",
            "return_url": "/followups/unified/?view=all",
            "next_url": next_url,
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(next_url)
    source = action_app["db"].execute(
        "SELECT due_date,assigned_to,status FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    assert source["status"] == "open"
    assert source["assigned_to"] == "admin"
    assert str(source["due_date"]) > "2026-08-05"
    projection = action_app["db"].execute(
        """SELECT action_due_at,rebuilt_at
           FROM followup_work_item_projection WHERE episode_id=?""",
        (episode_id,),
    ).fetchone()
    assert projection["action_due_at"] == source["due_date"]
    assert projection["rebuilt_at"]


def test_booking_creates_real_appointment_links_task_and_opens_next(action_app):
    episode_id = action_app["episodes"][1]
    task_id = action_app["tasks"][1]
    next_url = f"/followups/unified/{action_app['episodes'][2]}?view=all"
    response = client_for(action_app).post(
        f"/followups/work-center/{episode_id}/book",
        data={
            "booking_date": jalali_day(5),
            "booking_time": "10:15",
            "idempotency_key": "work-center-book-admin-0001",
            "current_url": f"/followups/unified/{episode_id}?view=all",
            "return_url": "/followups/unified/?view=all",
            "next_url": next_url,
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(next_url)
    source = action_app["db"].execute(
        """SELECT patient_link_id,appointment_id,status
           FROM followup_tasks WHERE id=?""",
        (task_id,),
    ).fetchone()
    assert source["status"] == "open"
    assert source["appointment_id"] is not None
    appointment = action_app["db"].execute(
        "SELECT patient_link_id,status,scheduled_at FROM appointments WHERE id=?",
        (int(source["appointment_id"]),),
    ).fetchone()
    assert int(appointment["patient_link_id"]) == int(source["patient_link_id"])
    assert appointment["status"] == "scheduled"
    projection = action_app["db"].execute(
        """SELECT appointment_state,state_class
           FROM followup_work_item_projection WHERE episode_id=?""",
        (episode_id,),
    ).fetchone()
    assert projection["appointment_state"]
    assert projection["state_class"] != "TERMINAL"


def test_administrative_completion_updates_source_projection_and_opens_next(action_app):
    episode_id = action_app["episodes"][2]
    task_id = action_app["tasks"][2]
    response = client_for(action_app).post(
        f"/followups/work-center/{episode_id}/complete",
        data={
            "note": "اقدام اداری انجام شد",
            "current_url": f"/followups/unified/{episode_id}?view=all",
            "return_url": "/followups/unified/?view=all",
            "next_url": "",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert "/followups/unified/" in response.headers["Location"]
    source = action_app["db"].execute(
        "SELECT status,resolved_at,call_log FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    assert source["status"] == "done"
    assert source["resolved_at"]
    assert source["call_log"] == "اقدام اداری انجام شد"
    projection = action_app["db"].execute(
        """SELECT state_class,current_state
           FROM followup_work_item_projection WHERE episode_id=?""",
        (episode_id,),
    ).fetchone()
    assert projection["state_class"] == "TERMINAL"


def test_committed_source_action_remains_success_when_projection_refresh_fails(
    action_app, monkeypatch
):
    from src.security.permissions import Permission
    from src.services.followup_orchestration.work_center_action_service import (
        WorkCenterActionService,
    )

    episode_id = action_app["episodes"][0]
    task_id = action_app["tasks"][0]
    service = WorkCenterActionService(action_app["db"])
    monkeypatch.setattr(
        service,
        "refresh_projection",
        lambda _episode: (_ for _ in ()).throw(RuntimeError("projection down")),
    )
    result = service.complete_administrative(
        episode_id,
        actor_username="admin",
        permissions=frozenset({Permission.FOLLOWUP_ADMIN_MANAGE}),
        note="منبع اصلی تکمیل شد",
    )

    assert result["status"] == "done"
    assert result["projection_refreshed"] is False
    assert result["projection_refresh_error"] == "RuntimeError"
    source = action_app["db"].execute(
        "SELECT status FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    assert source["status"] == "done"


def test_stage_one_roadmap_and_ui_stay_narrow():
    roadmap = (
        ROOT / "docs/FRONTEND_AUTOMATION_V2_EXECUTION_ROADMAP.md"
    ).read_text(encoding="utf-8")
    detail = (
        ROOT / "src/templates/followups/unified_detail.html"
    ).read_text(encoding="utf-8")
    routes = (ROOT / "src/api/followups.py").read_text(encoding="utf-8")
    service = (
        ROOT
        / "src/services/followup_orchestration/work_center_action_service.py"
    ).read_text(encoding="utf-8")

    assert "## Stage 1 — Complete Work Center end to end" in roadmap
    assert "generic workflow engine" in roadmap
    assert "work_center_defer" in routes
    assert "work_center_book" in routes
    assert "work_center_complete" in routes
    assert "WorkCenterActionService" in routes
    assert "FollowupBookingService" in service
    assert "ClinicalCareLoopService" in service
    assert "EncounterPlanCommitmentService" in service
    assert "ارسال پیام" not in detail
    assert "تکمیل و رفتن به کار بعدی" in detail
