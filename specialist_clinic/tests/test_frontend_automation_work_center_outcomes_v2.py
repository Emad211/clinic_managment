from __future__ import annotations

from datetime import datetime

import pytest


@pytest.fixture()
def outcome_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.clinical_care_loop_repo import ClinicalCareLoopRepository
    from src.adapters.sqlite.clinical_task_contract_schema import (
        ensure_clinical_task_contract_storage,
    )
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
            "DATABASE_PATH": str(tmp_path / "work-outcomes.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "work-outcomes-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": True,
            "FOLLOWUP_AUTO_ROUTING": True,
            "FOLLOWUP_STRUCTURED_CONTACT": True,
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()

    patient_ids = []
    for index in range(1, 4):
        patient_ids.append(
            int(
                db.execute(
                    """INSERT INTO patient_links
                       (national_id, full_name, phone_number, enrolled_by,
                        enrolled_at, updated_at)
                       VALUES (?, ?, ?, 'pytest',
                               '2026-08-05 08:00:00', '2026-08-05 08:00:00')""",
                    (
                        f"WCO2{index:06d}",
                        f"بیمار نتیجه مرکز کار {index}",
                        f"0912222222{index}",
                    ),
                ).lastrowid
            )
        )

    admin_task = int(
        db.execute(
            """INSERT INTO followup_tasks
               (patient_link_id, due_date, reason, detail, status,
                source_event, fulfillment, created_at)
               VALUES (?, '2026-08-05', 'manual', 'کار اداری', 'open',
                       'manual', 'remote', '2026-08-05 08:05:00')""",
            (patient_ids[0],),
        ).lastrowid
    )
    message_task = int(
        db.execute(
            """INSERT INTO followup_tasks
               (patient_link_id, due_date, reason, detail, status,
                source_event, fulfillment, created_at)
               VALUES (?, '2026-08-05', 'manual', 'دعوت بیمار', 'open',
                       'manual', 'remote', '2026-08-05 08:06:00')""",
            (patient_ids[1],),
        ).lastrowid
    )
    clinical_task = int(
        db.execute(
            """INSERT INTO followup_tasks
               (patient_link_id, reason, detail, due_date, fulfillment,
                source_engine, clinical_semantic_key, clinical_context_hash,
                clinical_task_key, clinical_due_period, created_at)
               VALUES (?, 'monitoring', 'پیگیری بالینی', '2026-08-05',
                       'in_person', 'clinical_v2', 'monitoring:wco2', ?, ?,
                       '2026-H2', '2026-08-05 08:07:00')""",
            (patient_ids[2], "c" * 64, "t" * 64),
        ).lastrowid
    )
    ClinicalCareLoopRepository.create_initial_event(
        db,
        task_id=clinical_task,
        due_at="2026-08-05 09:00:00",
        actor_username="pytest",
        recorded_at=datetime(2026, 8, 5, 8, 7, 0),
    )
    db.commit()
    # The application installed contract storage before this fixture inserted its
    # task. Re-running the additive installer applies the same conservative legacy
    # contract used for copied pre-contract databases.
    ensure_clinical_task_contract_storage(db)
    db.commit()

    FollowupEpisodeBackfillService(db).run(apply=True)
    FollowupProjectionService(db).run(
        as_of_at="2026-08-05 12:00:00",
        apply=True,
    )

    def episode_for(task_id: int) -> str:
        row = db.execute(
            """SELECT episode_id FROM followup_episode_links
               WHERE source_id=?
                 AND source_type IN ('ADMIN_TASK','CLINICAL_TASK')
               ORDER BY id LIMIT 1""",
            (str(task_id),),
        ).fetchone()
        assert row
        return str(row["episode_id"])

    admin = db.execute(
        """SELECT id, username, full_name, role, is_active
           FROM users WHERE username='admin'"""
    ).fetchone()

    yield {
        "app": app,
        "db": db,
        "admin": admin,
        "admin_task": admin_task,
        "message_task": message_task,
        "clinical_task": clinical_task,
        "admin_episode": episode_for(admin_task),
        "message_episode": episode_for(message_task),
        "clinical_episode": episode_for(clinical_task),
    }

    context.pop()
    core._initialized = False


def client_for(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def action_context(episode_id: str, key: str) -> dict:
    return {
        "current_url": f"/followups/unified/{episode_id}?view=all",
        "return_url": "/followups/unified/?view=all",
        "next_url": "",
        "idempotency_key": key,
    }


def test_outcome_blueprint_is_registered_during_app_setup(outcome_app):
    endpoints = {rule.endpoint for rule in outcome_app["app"].url_map.iter_rules()}
    assert {
        "work_center_outcomes.clinical_complete",
        "work_center_outcomes.plan_complete",
        "work_center_outcomes.queue_message",
    } <= endpoints


def test_outcome_routes_are_hidden_when_work_center_actions_are_off(outcome_app):
    client = client_for(outcome_app)
    episode_id = outcome_app["message_episode"]
    outcome_app["app"].config["FOLLOWUP_UNIFIED_WORKLIST_ACTIONS"] = False
    try:
        response = client.post(
            f"/followups/work-center-outcomes/{episode_id}/queue-message",
            data={"current_url": f"/followups/unified/{episode_id}?view=all"},
        )
    finally:
        outcome_app["app"].config["FOLLOWUP_UNIFIED_WORKLIST_ACTIONS"] = True
    assert response.status_code == 404


def test_administrative_defer_retry_writes_one_source_change_and_one_audit_event(
    outcome_app,
):
    client = client_for(outcome_app)
    episode_id = outcome_app["admin_episode"]
    payload = {
        **action_context(episode_id, "work-center-defer-retry-0001"),
        "defer_days": "3",
    }
    first = client.post(
        f"/followups/work-center/{episode_id}/defer",
        data=payload,
        follow_redirects=False,
    )
    due_after_first = outcome_app["db"].execute(
        "SELECT due_date FROM followup_tasks WHERE id=?",
        (outcome_app["admin_task"],),
    ).fetchone()["due_date"]
    second = client.post(
        f"/followups/work-center/{episode_id}/defer",
        data=payload,
        follow_redirects=False,
    )
    due_after_second = outcome_app["db"].execute(
        "SELECT due_date FROM followup_tasks WHERE id=?",
        (outcome_app["admin_task"],),
    ).fetchone()["due_date"]

    assert first.status_code in {302, 303}
    assert second.status_code in {302, 303}
    assert due_after_second == due_after_first
    event_count = outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='ACTION_DUE_CHANGED'
             AND idempotency_key='work-center-defer-retry-0001'""",
        (episode_id,),
    ).fetchone()[0]
    assert event_count == 1


def test_administrative_completion_retry_is_one_authoritative_event(outcome_app):
    client = client_for(outcome_app)
    episode_id = outcome_app["admin_episode"]
    payload = {
        **action_context(episode_id, "work-center-admin-complete-0001"),
        "note": "کار اداری واقعاً انجام شد",
    }
    first = client.post(
        f"/followups/work-center/{episode_id}/complete",
        data=payload,
        follow_redirects=False,
    )
    second = client.post(
        f"/followups/work-center/{episode_id}/complete",
        data=payload,
        follow_redirects=False,
    )

    assert first.status_code in {302, 303}
    assert second.status_code in {302, 303}
    task = outcome_app["db"].execute(
        "SELECT status,call_log FROM followup_tasks WHERE id=?",
        (outcome_app["admin_task"],),
    ).fetchone()
    assert task["status"] == "done"
    assert task["call_log"] == "کار اداری واقعاً انجام شد"
    assert outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='ADMINISTRATIVE_GOAL_MET'""",
        (episode_id,),
    ).fetchone()[0] == 1


def test_clinical_completion_is_atomic_idempotent_and_terminal(outcome_app):
    client = client_for(outcome_app)
    episode_id = outcome_app["clinical_episode"]
    payload = {
        **action_context(episode_id, "work-center-clinical-complete-0001"),
        "outcome_type": "OTHER",
        # Blank observed_at exercises the stable date-level server default.
        "note": "شاهد بالینی بررسی شد",
    }
    first = client.post(
        f"/followups/work-center-outcomes/{episode_id}/clinical-complete",
        data=payload,
        follow_redirects=False,
    )
    second = client.post(
        f"/followups/work-center-outcomes/{episode_id}/clinical-complete",
        data=payload,
        follow_redirects=False,
    )

    assert first.status_code in {302, 303}
    assert second.status_code in {302, 303}
    current = outcome_app["db"].execute(
        """SELECT event.status,event.outcome_event_id
           FROM clinical_task_events event
           WHERE event.task_id=? AND NOT EXISTS(
             SELECT 1 FROM clinical_task_events child
             WHERE child.supersedes_event_id=event.id
           )""",
        (outcome_app["clinical_task"],),
    ).fetchone()
    assert current["status"] == "COMPLETED"
    assert current["outcome_event_id"] is not None
    assert outcome_app["db"].execute(
        "SELECT COUNT(*) FROM clinical_outcome_events WHERE task_id=?",
        (outcome_app["clinical_task"],),
    ).fetchone()[0] == 1
    assert outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_links
           WHERE episode_id=? AND source_type='CLINICAL_OUTCOME'""",
        (episode_id,),
    ).fetchone()[0] == 1
    assert outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='EPISODE_CLOSED'
             AND idempotency_key='work-center-clinical-complete-0001'""",
        (episode_id,),
    ).fetchone()[0] == 1
    projection = outcome_app["db"].execute(
        """SELECT state_class FROM followup_work_item_projection
           WHERE episode_id=?""",
        (episode_id,),
    ).fetchone()
    assert projection["state_class"] == "TERMINAL"


def test_message_action_queues_one_template_approval_and_links_episode(outcome_app):
    client = client_for(outcome_app)
    episode_id = outcome_app["message_episode"]
    payload = {
        "current_url": f"/followups/unified/{episode_id}?view=all",
        "return_url": "/followups/unified/?view=all",
        "next_url": "",
    }
    first = client.post(
        f"/followups/work-center-outcomes/{episode_id}/queue-message",
        data=payload,
        follow_redirects=False,
    )
    second = client.post(
        f"/followups/work-center-outcomes/{episode_id}/queue-message",
        data=payload,
        follow_redirects=False,
    )

    assert first.status_code in {302, 303}
    assert second.status_code in {302, 303}
    approvals = outcome_app["db"].execute(
        """SELECT * FROM engagement_approvals
           WHERE patient_link_id=(
             SELECT patient_link_id FROM followup_tasks WHERE id=?
           ) AND event_key='visit_invite'""",
        (outcome_app["message_task"],),
    ).fetchall()
    assert len(approvals) == 1
    approval_id = int(approvals[0]["id"])
    assert outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_links
           WHERE episode_id=? AND source_type='ENGAGEMENT_APPROVAL'
             AND source_id=?""",
        (episode_id, str(approval_id)),
    ).fetchone()[0] == 1
    assert outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='SMS_QUEUED'""",
        (episode_id,),
    ).fetchone()[0] == 1


def test_work_center_detail_exposes_only_safe_message_and_evidence_forms(outcome_app):
    client = client_for(outcome_app)
    clinical = client.get(
        f"/followups/unified/{outcome_app['clinical_episode']}?view=all"
    ).get_data(as_text=True)
    administrative = client.get(
        f"/followups/unified/{outcome_app['message_episode']}?view=all"
    ).get_data(as_text=True)

    assert "تکمیل پیگیری بالینی با شاهد" in clinical
    assert "ثبت شاهد، تکمیل و کار بعدی" in clinical
    assert "متن آزاد ارسال نمی‌شود" in clinical
    assert "افزودن به صف پیام و کار بعدی" in administrative
    assert "ارسال مستقیم" not in administrative
    assert "work_center_outcomes.queue_message" not in administrative
