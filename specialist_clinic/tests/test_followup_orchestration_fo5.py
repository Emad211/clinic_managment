from __future__ import annotations

from datetime import datetime, timedelta
import json

import pytest

from src.services.followup_orchestration.structured_contact_service import (
    FollowupStructuredContactError,
    FollowupStructuredContactService,
)


@pytest.fixture()
def fo5_app(tmp_path):
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
            "DATABASE_PATH": str(tmp_path / "fo5.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "fo5-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": True,
            "FOLLOWUP_AUTO_ROUTING": True,
            "FOLLOWUP_STRUCTURED_CONTACT": True,
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()

    task_ids: dict[str, int] = {}
    definitions = (
        ("callback", "FO5TEST001", "بیمار تماس مجدد", "manual", "open"),
        ("retry", "FO5TEST002", "بیمار تلاش مجدد", "refill", "open"),
        ("phone", "FO5TEST003", "بیمار شماره نامعتبر", "lab", "open"),
        ("guard", "FO5TEST004", "بیمار کنترل دسترسی", "no_show", "open"),
        ("terminal", "FO5TEST005", "بیمار پایان‌یافته", "manual", "done"),
    )
    for index, (key, national_id, name, reason, status) in enumerate(
        definitions, start=1
    ):
        patient_id = int(
            db.execute(
                """INSERT INTO patient_links
                   (national_id, full_name, phone_number, enrolled_by,
                    enrolled_at, updated_at)
                   VALUES (?, ?, ?, 'pytest',
                           '2026-08-03 09:00:00',
                           '2026-08-03 09:00:00')""",
                (national_id, name, f"0912000050{index}"),
            ).lastrowid
        )
        task_ids[key] = int(
            db.execute(
                """INSERT INTO followup_tasks
                   (patient_link_id, due_date, reason, detail, status,
                    source_event, fulfillment, created_at)
                   VALUES (?, '2026-08-05', ?, ?, ?,
                           'manual', 'in_person', ?)""",
                (
                    patient_id,
                    reason,
                    f"پیگیری FO-5 {key}",
                    status,
                    f"2026-08-03 09:{index:02d}:00",
                ),
            ).lastrowid
        )

    db.execute(
        """INSERT INTO users
           (username, password_hash, role, full_name, is_active)
           VALUES ('fo5-staff', ?, 'staff', 'کارمند تماس', 1)""",
        (b"not-used",),
    )
    db.execute(
        """INSERT INTO users
           (username, password_hash, role, full_name, is_active)
           VALUES ('fo5-viewer', ?, 'viewer', 'کاربر بدون مجوز', 1)""",
        (b"not-used",),
    )
    db.commit()

    FollowupEpisodeBackfillService(db).run(apply=True)
    FollowupProjectionService(db).run(
        as_of_at="2026-08-04 09:00:00",
        apply=True,
    )

    episodes = {}
    for key, task_id in task_ids.items():
        row = db.execute(
            """SELECT episode_id FROM followup_episode_links
               WHERE source_type='ADMIN_TASK' AND source_id=?
               ORDER BY id LIMIT 1""",
            (str(task_id),),
        ).fetchone()
        assert row
        episodes[key] = str(row[0])

    staff = _user(db, "fo5-staff")
    ownership = FollowupOwnershipService(db)
    for index, key in enumerate(("callback", "retry", "phone", "guard"), start=1):
        ownership.claim(
            episode_id=episodes[key],
            actor=staff,
            expected_event_id=0,
            idempotency_key=f"fo5-fixture-claim-{index:04d}",
        )

    app.config["FO5_EPISODES"] = episodes
    app.config["FO5_TASKS"] = task_ids
    app.config["FO5_STAFF_ID"] = int(staff["id"])
    yield app
    context.pop()
    core._initialized = False


def _user(db, username: str):
    return db.execute(
        """SELECT id, username, full_name, role, is_active
           FROM users WHERE username=?""",
        (username,),
    ).fetchone()


def _head(db, episode_id: str) -> int:
    row = db.execute(
        """SELECT id FROM followup_episode_events
           WHERE episode_id=? ORDER BY id DESC LIMIT 1""",
        (episode_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def _count(db, table: str) -> int:
    return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_callback_validation_exact_replay_and_note_privacy(fo5_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_orchestration.timeline_service import (
        FollowupTimelineService,
    )

    db = get_db()
    episode_id = fo5_app.config["FO5_EPISODES"]["callback"]
    staff = _user(db, "fo5-staff")
    service = FollowupStructuredContactService(db)
    now = datetime(2026, 8, 4, 10, 0, 0)

    with pytest.raises(FollowupStructuredContactError) as missing:
        service.record(
            episode_id=episode_id,
            actor=staff,
            structured_outcome="CALLBACK_REQUESTED",
            expected_event_id=_head(db, episode_id),
            idempotency_key="fo5-callback-missing-0001",
            now=now,
        )
    assert missing.value.code == "CALLBACK_REQUIRED"

    with pytest.raises(FollowupStructuredContactError) as past:
        service.record(
            episode_id=episode_id,
            actor=staff,
            structured_outcome="CALLBACK_REQUESTED",
            callback_at="2026-08-04 09:59:00",
            expected_event_id=_head(db, episode_id),
            idempotency_key="fo5-callback-past-000001",
            now=now,
        )
    assert past.value.code == "CALLBACK_NOT_FUTURE"

    expected = _head(db, episode_id)
    secret_note = "متن محرمانهٔ تماس که نباید در Timeline دیده شود"
    first = service.record(
        episode_id=episode_id,
        actor=staff,
        structured_outcome="CALLBACK_REQUESTED",
        callback_at="2026-08-05 11:30:00",
        note=secret_note,
        expected_event_id=expected,
        idempotency_key="fo5-callback-valid-00001",
        now=now,
    )
    replay = service.record(
        episode_id=episode_id,
        actor=staff,
        structured_outcome="CALLBACK_REQUESTED",
        callback_at="2026-08-05 11:30:00",
        note=secret_note,
        expected_event_id=expected,
        idempotency_key="fo5-callback-valid-00001",
        now=now,
    )

    assert first["callback_at"] == "2026-08-05 11:30:00"
    assert replay["contact_event_id"] == first["contact_event_id"]
    assert _count(db, "followup_contact_events") == 1
    assert db.execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='CONTACT_RECORDED'""",
        (episode_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT note FROM followup_contact_events WHERE id=?",
        (first["contact_event_id"],),
    ).fetchone()[0] == secret_note

    rendered_timeline = json.dumps(
        FollowupTimelineService(db).build(episode_id),
        ensure_ascii=False,
    )
    assert secret_note not in rendered_timeline
    assert "درخواست تماس مجدد" in rendered_timeline

    client = fo5_app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = fo5_app.config["FO5_STAFF_ID"]
    html = client.get(f"/followups/unified/{episode_id}").get_data(as_text=True)
    assert "ثبت نتیجهٔ تماس" in html
    assert "درخواست تماس مجدد" in html
    assert secret_note not in html


def test_retry_threshold_escalates_once_and_stops_callback(fo5_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_orchestration.ownership_service import (
        FollowupOwnershipService,
    )

    db = get_db()
    episode_id = fo5_app.config["FO5_EPISODES"]["retry"]
    staff = _user(db, "fo5-staff")
    admin = _user(db, "admin")
    service = FollowupStructuredContactService(db)
    now = datetime(2026, 8, 4, 10, 0, 0)

    summaries = []
    for attempt in range(1, 4):
        summaries.append(
            service.record(
                episode_id=episode_id,
                actor=staff,
                structured_outcome="NO_ANSWER",
                expected_event_id=_head(db, episode_id),
                idempotency_key=f"fo5-retry-attempt-{attempt:04d}",
                now=now + timedelta(minutes=attempt),
            )
        )

    assert summaries[0]["callback_at"]
    assert summaries[1]["callback_at"]
    assert summaries[2]["callback_at"] is None
    assert summaries[2]["failed_attempt_count"] == 3
    assert summaries[2]["next_action_code"] == "MANAGER_REVIEW_UNREACHABLE"
    assert summaries[2]["escalated"] is True
    assert FollowupOwnershipService(db).state(episode_id).owner_role == "MANAGER"

    assert db.execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='ESCALATED'
             AND json_extract(payload_json,'$.reason_code')='UNREACHABLE_THRESHOLD'""",
        (episode_id,),
    ).fetchone()[0] == 1

    service.record(
        episode_id=episode_id,
        actor=admin,
        structured_outcome="BUSY",
        expected_event_id=_head(db, episode_id),
        idempotency_key="fo5-retry-fourth-manager",
        now=now + timedelta(hours=1),
    )
    assert db.execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='ESCALATED'
             AND json_extract(payload_json,'$.reason_code')='UNREACHABLE_THRESHOLD'""",
        (episode_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='ROUTED'
             AND json_extract(payload_json,'$.reason_code')='UNREACHABLE_THRESHOLD'""",
        (episode_id,),
    ).fetchone()[0] == 1


def test_phone_invalid_routes_to_reception_without_sms_or_appointment(fo5_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_orchestration.ownership_service import (
        FollowupOwnershipService,
    )

    db = get_db()
    episode_id = fo5_app.config["FO5_EPISODES"]["phone"]
    staff = _user(db, "fo5-staff")
    service = FollowupStructuredContactService(db)
    before = {
        "sms": _count(db, "sms_messages"),
        "appointments": _count(db, "appointments"),
        "tasks": [
            tuple(row)
            for row in db.execute(
                "SELECT id, status, due_date FROM followup_tasks ORDER BY id"
            ).fetchall()
        ],
    }

    summary = service.record(
        episode_id=episode_id,
        actor=staff,
        structured_outcome="PHONE_INVALID",
        expected_event_id=_head(db, episode_id),
        idempotency_key="fo5-phone-invalid-0001",
        now=datetime(2026, 8, 4, 10, 0, 0),
    )

    assert summary["next_action_code"] == "FIX_CONTACT_DATA"
    assert summary["callback_at"] is None
    assert FollowupOwnershipService(db).state(episode_id).owner_role == "RECEPTION"
    contact_row = db.execute(
        """SELECT outcome, next_contact_at FROM followup_contact_events
           WHERE id=?""",
        (summary["contact_event_id"],),
    ).fetchone()
    assert tuple(contact_row) == ("WRONG_NUMBER", None)
    assert _count(db, "sms_messages") == before["sms"]
    assert _count(db, "appointments") == before["appointments"]
    assert [
        tuple(row)
        for row in db.execute(
            "SELECT id, status, due_date FROM followup_tasks ORDER BY id"
        ).fetchall()
    ] == before["tasks"]


def test_non_owner_stale_and_terminal_contact_mutations_fail_closed(fo5_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_orchestration.ownership_service import (
        FollowupOwnershipService,
    )

    db = get_db()
    service = FollowupStructuredContactService(db)
    viewer = _user(db, "fo5-viewer")
    staff = _user(db, "fo5-staff")
    admin = _user(db, "admin")
    guard = fo5_app.config["FO5_EPISODES"]["guard"]
    terminal = fo5_app.config["FO5_EPISODES"]["terminal"]

    with pytest.raises(FollowupStructuredContactError) as denied:
        service.record(
            episode_id=guard,
            actor=viewer,
            structured_outcome="REACHED",
            expected_event_id=_head(db, guard),
            idempotency_key="fo5-viewer-denied-0001",
            now=datetime(2026, 8, 4, 10, 0, 0),
        )
    assert denied.value.code == "CONTACT_PERMISSION_REQUIRED"

    with pytest.raises(FollowupStructuredContactError) as terminal_error:
        service.record(
            episode_id=terminal,
            actor=viewer,
            structured_outcome="REACHED",
            expected_event_id=_head(db, terminal),
            idempotency_key="fo5-terminal-denied-001",
            now=datetime(2026, 8, 4, 10, 0, 0),
        )
    assert terminal_error.value.code == "TERMINAL_CONTACT_MUTATION"

    stale_head = _head(db, guard)
    ownership = FollowupOwnershipService(db)
    state = ownership.state(guard)
    ownership.route(
        episode_id=guard,
        owner_role="NURSING",
        actor=admin,
        expected_event_id=state.expected_event_id,
        idempotency_key="fo5-stale-route-00001",
        reason_code="TEST_STALE",
    )
    with pytest.raises(FollowupStructuredContactError) as stale:
        service.record(
            episode_id=guard,
            actor=staff,
            structured_outcome="REACHED",
            expected_event_id=stale_head,
            idempotency_key="fo5-stale-contact-0001",
            now=datetime(2026, 8, 4, 10, 0, 0),
        )
    assert stale.value.code == "STALE_CONTACT_FORM"


def test_feature_off_hides_controls_and_contact_post_returns_404(fo5_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    episode_id = fo5_app.config["FO5_EPISODES"]["callback"]
    client = fo5_app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = fo5_app.config["FO5_STAFF_ID"]

    fo5_app.config["FOLLOWUP_STRUCTURED_CONTACT"] = False
    html = client.get(f"/followups/unified/{episode_id}").get_data(as_text=True)
    assert "ثبت نتیجهٔ تماس" not in html
    response = client.post(
        f"/followups/unified/{episode_id}/contact",
        data={
            "structured_outcome": "REACHED",
            "expected_event_id": _head(db, episode_id),
            "idempotency_key": "fo5-flag-off-contact-01",
        },
    )
    assert response.status_code == 404


def test_contact_list_summary_is_batched_and_get_is_non_mutating(fo5_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    service = FollowupStructuredContactService(db)
    staff = _user(db, "fo5-staff")
    episodes = [
        fo5_app.config["FO5_EPISODES"]["callback"],
        fo5_app.config["FO5_EPISODES"]["phone"],
    ]
    service.record(
        episode_id=episodes[0],
        actor=staff,
        structured_outcome="REACHED",
        expected_event_id=_head(db, episodes[0]),
        idempotency_key="fo5-batch-contact-00001",
        now=datetime(2026, 8, 4, 10, 0, 0),
    )
    service.record(
        episode_id=episodes[1],
        actor=staff,
        structured_outcome="CALLBACK_REQUESTED",
        callback_at="2026-08-05 10:00:00",
        expected_event_id=_head(db, episodes[1]),
        idempotency_key="fo5-batch-contact-00002",
        now=datetime(2026, 8, 4, 10, 0, 0),
    )

    statements: list[str] = []
    db.set_trace_callback(statements.append)
    items = [{"episode_id": value} for value in episodes]
    service.decorate_items(items)
    db.set_trace_callback(None)
    selects = [
        value
        for value in statements
        if value.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    assert len(selects) == 2
    assert all(item["contact"]["has_contact"] for item in items)

    before = {
        "contacts": _count(db, "followup_contact_events"),
        "events": _count(db, "followup_episode_events"),
        "links": _count(db, "followup_episode_links"),
    }
    client = fo5_app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = fo5_app.config["FO5_STAFF_ID"]
    html = client.get("/followups/unified/").get_data(as_text=True)
    after = {
        "contacts": _count(db, "followup_contact_events"),
        "events": _count(db, "followup_episode_events"),
        "links": _count(db, "followup_episode_links"),
    }
    assert before == after
    assert "آخرین تماس" in html
    assert "اقدام بعدی" in html
