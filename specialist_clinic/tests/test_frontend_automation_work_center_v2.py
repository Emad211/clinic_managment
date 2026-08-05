from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def work_center_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app
    from src.services.followup_orchestration.backfill import (
        FollowupEpisodeBackfillService,
    )
    from src.services.followup_orchestration.ownership_service import (
        FollowupOwnershipService,
    )
    from src.services.followup_orchestration.projection_service import (
        FollowupProjectionService,
    )

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "work-center.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "work-center-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": True,
            "FOLLOWUP_AUTO_ROUTING": True,
            "FOLLOWUP_STRUCTURED_CONTACT": True,
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()

    for index in range(1, 5):
        patient_id = int(
            db.execute(
                """INSERT INTO patient_links
                   (national_id, full_name, phone_number, enrolled_by,
                    enrolled_at, updated_at)
                   VALUES (?, ?, ?, 'pytest',
                           '2026-08-05 08:00:00', '2026-08-05 08:00:00')""",
                (
                    f"WCV2{index:06d}",
                    f"بیمار مرکز کار {index}",
                    f"0912000000{index}",
                ),
            ).lastrowid
        )
        db.execute(
            """INSERT INTO followup_tasks
               (patient_link_id, due_date, reason, detail, status,
                source_event, fulfillment, created_at)
               VALUES (?, '2026-08-05', 'manual', ?, ?,
                       'manual', 'remote', '2026-08-05 08:05:00')""",
            (
                patient_id,
                f"کار تست {index}",
                "done" if index == 4 else "open",
            ),
        )

    db.execute(
        """INSERT INTO users
           (username, password_hash, role, full_name, is_active)
           VALUES ('work-center-staff', ?, 'staff', 'کاربر دیگر', 1)""",
        (b"not-used",),
    )
    db.commit()

    FollowupEpisodeBackfillService(db).run(apply=True)
    FollowupProjectionService(db).run(
        as_of_at="2026-08-05 12:00:00",
        apply=True,
    )

    active = [
        str(row["episode_id"])
        for row in db.execute(
            """SELECT episode_id FROM followup_work_item_projection
               WHERE state_class<>'TERMINAL' ORDER BY episode_id"""
        ).fetchall()
    ]
    terminal = str(
        db.execute(
            """SELECT episode_id FROM followup_work_item_projection
               WHERE state_class='TERMINAL' ORDER BY episode_id LIMIT 1"""
        ).fetchone()["episode_id"]
    )
    assert len(active) == 3

    admin = db.execute(
        """SELECT id, username, full_name, role, is_active
           FROM users WHERE username='admin'"""
    ).fetchone()
    staff = db.execute(
        """SELECT id, username, full_name, role, is_active
           FROM users WHERE username='work-center-staff'"""
    ).fetchone()
    ownership = FollowupOwnershipService(db)
    ownership.claim(
        episode_id=active[0],
        actor=admin,
        expected_event_id=0,
        idempotency_key="work-center-mine-0001",
    )
    ownership.assign(
        episode_id=active[2],
        owner_user_id=int(staff["id"]),
        actor=admin,
        expected_event_id=0,
        idempotency_key="work-center-other-0001",
        reason_code="MANAGER_ASSIGN",
    )

    yield {
        "app": app,
        "db": db,
        "active": active,
        "terminal": terminal,
        "admin": admin,
        "staff": staff,
    }

    context.pop()
    core._initialized = False


def _client(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def test_read_model_exposes_exact_approved_work_center_views(work_center_app):
    from src.services.followup_orchestration.work_center_read_model import (
        WorkCenterReadModelService,
    )

    service = WorkCenterReadModelService(work_center_app["db"])
    counts = service.counts(actor_user_id=int(work_center_app["admin"]["id"]))
    assert counts == {
        "mine": 1,
        "unassigned": 1,
        "all": 3,
        "completed": 1,
        "manager": 3,
    }

    mine = service.list_items(
        actor_user_id=int(work_center_app["admin"]["id"]),
        allow_manager_view=True,
        work_view="mine",
    )
    unassigned = service.list_items(
        actor_user_id=int(work_center_app["admin"]["id"]),
        allow_manager_view=True,
        work_view="unassigned",
    )
    all_open = service.list_items(
        actor_user_id=int(work_center_app["admin"]["id"]),
        allow_manager_view=True,
        work_view="all",
    )
    completed = service.list_items(
        actor_user_id=int(work_center_app["admin"]["id"]),
        allow_manager_view=True,
        work_view="completed",
    )
    manager = service.list_items(
        actor_user_id=int(work_center_app["admin"]["id"]),
        allow_manager_view=True,
        work_view="manager",
    )

    assert [item["episode_id"] for item in mine["items"]] == [
        work_center_app["active"][0]
    ]
    assert [item["episode_id"] for item in unassigned["items"]] == [
        work_center_app["active"][1]
    ]
    assert len(all_open["items"]) == 3
    assert [item["episode_id"] for item in completed["items"]] == [
        work_center_app["terminal"]
    ]
    assert len(manager["items"]) == 3

    staff_manager_attempt = service.list_items(
        actor_user_id=int(work_center_app["staff"]["id"]),
        allow_manager_view=False,
        work_view="manager",
    )
    assert staff_manager_attempt["filters"]["view"] == "mine"
    assert [item["episode_id"] for item in staff_manager_attempt["items"]] == [
        work_center_app["active"][2]
    ]


def test_tabs_render_and_handle_auto_claims_without_claim_screen(work_center_app):
    from src.services.followup_orchestration.ownership_service import (
        FollowupOwnershipService,
    )

    client = _client(work_center_app)
    listing = client.get("/followups/unified/?view=unassigned")
    html = listing.get_data(as_text=True)
    assert listing.status_code == 200
    for label in (
        "کارهای من",
        "بدون مسئول",
        "همهٔ کارهای باز",
        "تکمیل‌شده",
        "نمای مدیریتی",
    ):
        assert label in html
    assert "دریافت برای رسیدگی" not in html
    assert html.count("data-primary-action") == 1
    assert "/handle" in html

    episode_id = work_center_app["active"][1]
    response = client.post(
        f"/followups/unified/{episode_id}/handle",
        data={
            "expected_event_id": "0",
            "idempotency_key": "work-center-handle-0001",
            "work_view": "unassigned",
            "q": "",
            "state": "",
            "role": "",
            "sla": "",
            "page": "1",
            "per_page": "20",
        },
    )
    assert response.status_code in {302, 303}
    assert f"/followups/unified/{episode_id}" in response.headers["Location"]
    assert "view=unassigned" in response.headers["Location"]

    owner = FollowupOwnershipService(work_center_app["db"]).state(episode_id)
    assert owner.owner_user_id == int(work_center_app["admin"]["id"])

    detail = client.get(response.headers["Location"])
    detail_html = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert "کاری که اکنون باید انجام شود" in detail_html
    assert "دریافت برای رسیدگی" not in detail_html
    assert "رسیدگی و واگذاری" in detail_html


def test_successful_contact_continues_to_next_item_in_same_view(work_center_app):
    from src.adapters.sqlite.followup_episode_repo import FollowupEpisodeRepository

    client = _client(work_center_app)
    episode_id = work_center_app["active"][0]
    current = FollowupEpisodeRepository(work_center_app["db"]).current_event(episode_id)
    expected = int(current["id"]) if current else 0

    response = client.post(
        f"/followups/unified/{episode_id}/contact",
        data={
            "structured_outcome": "REACHED",
            "expected_event_id": str(expected),
            "idempotency_key": "work-center-contact-0001",
            "auto_next": "1",
            "work_view": "all",
            "q": "",
            "state": "",
            "role": "",
            "sla": "",
            "page": "1",
            "per_page": "20",
        },
    )
    assert response.status_code in {302, 303}
    location = response.headers["Location"]
    assert "/followups/unified/" in location
    assert episode_id not in location
    assert "view=all" in location

    contact_count = work_center_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='CONTACT_RECORDED'""",
        (episode_id,),
    ).fetchone()[0]
    assert contact_count == 1


def test_work_center_templates_lock_progressive_and_mobile_contracts():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    listing = (root / "src/templates/followups/unified_worklist.html").read_text(
        encoding="utf-8"
    )
    detail = (root / "src/templates/followups/unified_detail.html").read_text(
        encoding="utf-8"
    )
    contact = (
        root / "src/templates/followups/_structured_contact_detail.html"
    ).read_text(encoding="utf-8")
    css = (
        root / "src/static/css/work-center-automation-v2.css"
    ).read_text(encoding="utf-8")

    assert listing.count("data-primary-action") == 1
    assert "unified_followups.handle" in listing
    assert "مسیر قدیمی پیگیری" not in listing
    assert "work-center-tabs" in listing
    assert "work-item-drawer" in detail
    assert "دریافت برای رسیدگی" not in detail
    assert 'name="auto_next" value="1"' in contact
    assert "ثبت نتیجه و رفتن به کار بعدی" in contact
    assert "@media(max-width:700px)" in css
    assert "@media(max-width:420px)" in css
