from __future__ import annotations

import hashlib
import json

import pytest

from src.services.followup_orchestration.ownership_service import (
    FollowupOwnershipError,
    FollowupOwnershipService,
)


@pytest.fixture()
def fo4_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app
    from src.services.followup_orchestration.backfill import FollowupEpisodeBackfillService
    from src.services.followup_orchestration.projection_service import FollowupProjectionService

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "fo4.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "fo4-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": False,
            "FOLLOWUP_AUTO_ROUTING": False,
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()

    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, enrolled_by,
                enrolled_at, updated_at)
               VALUES ('FO4TEST001', 'بیمار تست مالکیت', '09120000404',
                       'pytest', '2026-08-03 09:00:00', '2026-08-03 09:00:00')"""
        ).lastrowid
    )
    db.execute(
        """INSERT INTO followup_tasks
           (patient_link_id, due_date, reason, detail, status,
            source_event, fulfillment, created_at)
           VALUES (?, '2026-08-04', 'manual', 'پیگیری فعال FO-4', 'open',
                   'manual', 'in_person', '2026-08-03 09:05:00')""",
        (patient_id,),
    )
    db.execute(
        """INSERT INTO followup_tasks
           (patient_link_id, due_date, reason, detail, status,
            source_event, fulfillment, created_at)
           VALUES (?, '2026-08-02', 'manual', 'پیگیری پایان‌یافته FO-4', 'done',
                   'manual', 'in_person', '2026-08-03 08:05:00')""",
        (patient_id,),
    )
    db.execute(
        """INSERT INTO users
           (username, password_hash, role, full_name, is_active)
           VALUES ('fo4-staff', ?, 'staff', 'کارمند پیگیری', 1)""",
        (b"not-used",),
    )
    db.execute(
        """INSERT INTO users
           (username, password_hash, role, full_name, is_active)
           VALUES ('fo4-viewer', ?, 'viewer', 'کاربر بدون مجوز', 1)""",
        (b"not-used",),
    )
    db.commit()

    FollowupEpisodeBackfillService(db).run(apply=True)
    FollowupProjectionService(db).run(
        as_of_at="2026-08-03 12:00:00",
        apply=True,
    )

    yield app
    context.pop()
    core._initialized = False


def _row(db, username: str):
    return db.execute(
        """SELECT id, username, full_name, role, is_active
           FROM users WHERE username=?""",
        (username,),
    ).fetchone()


def _episode(db, state_class: str) -> str:
    row = db.execute(
        """SELECT episode_id FROM followup_work_item_projection
           WHERE state_class=? ORDER BY episode_id LIMIT 1""",
        (state_class,),
    ).fetchone()
    assert row
    return str(row[0])


def _source_digest(db) -> str:
    payload = [
        list(row)
        for row in db.execute(
            """SELECT id, patient_link_id, due_date, reason, detail, status,
                      source_event, fulfillment, created_at
               FROM followup_tasks ORDER BY id"""
        ).fetchall()
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_atomic_claim_has_one_winner_and_exact_replay(fo4_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    episode_id = _episode(db, "ACTION_REQUIRED")
    service = FollowupOwnershipService(db)
    staff = _row(db, "fo4-staff")
    manager = _row(db, "admin")
    before = _source_digest(db)

    first = service.claim(
        episode_id=episode_id,
        actor=staff,
        expected_event_id=0,
        idempotency_key="fo4-claim-staff-0001",
    )
    replay = service.claim(
        episode_id=episode_id,
        actor=staff,
        expected_event_id=0,
        idempotency_key="fo4-claim-staff-0001",
    )

    assert first.owner_user_id == int(staff["id"])
    assert replay.ownership_event_id == first.ownership_event_id
    assert db.execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='CLAIMED'""",
        (episode_id,),
    ).fetchone()[0] == 1

    with pytest.raises(FollowupOwnershipError) as conflict:
        service.claim(
            episode_id=episode_id,
            actor=manager,
            expected_event_id=0,
            idempotency_key="fo4-claim-manager-01",
        )
    assert conflict.value.code == "ALREADY_CLAIMED"
    assert _source_digest(db) == before


def test_stale_assign_and_unauthorized_role_claim_fail_closed(fo4_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    episode_id = _episode(db, "ACTION_REQUIRED")
    service = FollowupOwnershipService(db)
    manager = _row(db, "admin")
    staff = _row(db, "fo4-staff")

    routed = service.route(
        episode_id=episode_id,
        owner_role="PHYSICIAN",
        actor=manager,
        expected_event_id=0,
        idempotency_key="fo4-route-physician-01",
        reason_code="MANAGER_ROUTE",
    )
    assert routed.owner_role == "PHYSICIAN"

    with pytest.raises(FollowupOwnershipError) as denied:
        service.claim(
            episode_id=episode_id,
            actor=staff,
            expected_event_id=routed.expected_event_id,
            idempotency_key="fo4-claim-unauth-001",
        )
    assert denied.value.code == "OWNER_ROLE_PERMISSION_MISMATCH"

    with pytest.raises(FollowupOwnershipError) as stale:
        service.assign(
            episode_id=episode_id,
            owner_user_id=int(manager["id"]),
            actor=manager,
            expected_event_id=0,
            idempotency_key="fo4-stale-assign-001",
            reason_code="MANAGER_ASSIGN",
        )
    assert stale.value.code == "STALE_OWNERSHIP_FORM"


def test_manager_reassign_release_and_projection_rebuild_preserve_history(fo4_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_orchestration.projection_service import FollowupProjectionService

    db = get_db()
    episode_id = _episode(db, "ACTION_REQUIRED")
    service = FollowupOwnershipService(db)
    manager = _row(db, "admin")
    staff = _row(db, "fo4-staff")
    viewer = _row(db, "fo4-viewer")

    assigned = service.assign(
        episode_id=episode_id,
        owner_user_id=int(staff["id"]),
        actor=manager,
        expected_event_id=0,
        idempotency_key="fo4-assign-staff-001",
        reason_code="MANAGER_ASSIGN",
    )
    assert assigned.owner_user_id == int(staff["id"])

    reassigned = service.assign(
        episode_id=episode_id,
        owner_user_id=int(manager["id"]),
        actor=manager,
        expected_event_id=assigned.expected_event_id,
        idempotency_key="fo4-reassign-admin-1",
        reason_code="MANAGER_REASSIGN",
    )
    assert reassigned.owner_user_id == int(manager["id"])

    with pytest.raises(FollowupOwnershipError) as denied:
        service.release(
            episode_id=episode_id,
            actor=viewer,
            expected_event_id=reassigned.expected_event_id,
            idempotency_key="fo4-viewer-release1",
        )
    assert denied.value.code == "NON_OWNER_RELEASE"

    before_rebuild = service.state(episode_id)
    FollowupProjectionService(db).run(
        as_of_at="2026-08-03 12:00:00",
        apply=True,
    )
    after_rebuild = service.state(episode_id)
    assert after_rebuild.owner_user_id == before_rebuild.owner_user_id
    assert after_rebuild.owner_role == before_rebuild.owner_role
    assert after_rebuild.ownership_event_id == before_rebuild.ownership_event_id

    event_types = [
        str(row[0])
        for row in db.execute(
            """SELECT event_type FROM followup_episode_events
               WHERE episode_id=? AND event_type IN ('ROUTED','CLAIMED','ASSIGNED')
               ORDER BY id""",
            (episode_id,),
        ).fetchall()
    ]
    assert event_types == ["ASSIGNED", "ASSIGNED"]


def test_terminal_item_rejects_ownership_mutation(fo4_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    episode_id = _episode(db, "TERMINAL")
    manager = _row(db, "admin")

    with pytest.raises(FollowupOwnershipError) as error:
        FollowupOwnershipService(db).claim(
            episode_id=episode_id,
            actor=manager,
            expected_event_id=0,
            idempotency_key="fo4-terminal-claim1",
        )
    assert error.value.code == "TERMINAL_OWNERSHIP_MUTATION"


def test_routes_are_actions_flagged_and_render_actual_owner(fo4_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    episode_id = _episode(db, "ACTION_REQUIRED")
    admin_id = int(_row(db, "admin")["id"])
    client = fo4_app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = admin_id

    disabled = client.post(
        f"/followups/unified/{episode_id}/claim",
        data={
            "expected_event_id": "0",
            "idempotency_key": "fo4-route-flag-off1",
        },
    )
    assert disabled.status_code == 404

    fo4_app.config["FOLLOWUP_UNIFIED_WORKLIST_ACTIONS"] = True
    claimed = client.post(
        f"/followups/unified/{episode_id}/claim",
        data={
            "expected_event_id": "0",
            "idempotency_key": "fo4-route-claim-on1",
        },
    )
    assert claimed.status_code in {302, 303}

    detail = client.get(f"/followups/unified/{episode_id}")
    html = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert "صف و مسئول" in html
    assert "مسئول فعلی" in html
    assert "admin" in html or "مدیر" in html
    assert "آزادکردن و بازگرداندن به صف" in html
    assert "Ownership event" in html

    fo4_app.config["FOLLOWUP_AUTO_ROUTING"] = False
    route_disabled = client.post(
        f"/followups/unified/{episode_id}/route",
        data={
            "owner_role": "NURSING",
            "expected_event_id": "0",
            "idempotency_key": "fo4-route-flag-off2",
        },
    )
    assert route_disabled.status_code == 404
