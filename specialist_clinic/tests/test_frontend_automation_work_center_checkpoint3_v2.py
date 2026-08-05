from __future__ import annotations

from pathlib import Path

import pytest

from test_frontend_automation_work_center_outcomes_v2 import (
    client_for,
    outcome_app,
)


ROOT = Path(__file__).resolve().parents[1]


def test_focus_query_is_read_only_and_start_next_claims_with_post(outcome_app):
    client = client_for(outcome_app)
    db = outcome_app["db"]

    read_only = client.get("/followups/unified/?view=mine&focus=first")
    assert read_only.status_code == 200
    assert db.execute(
        "SELECT COUNT(*) FROM followup_episode_events WHERE event_type='CLAIMED'"
    ).fetchone()[0] == 0

    started = client.post(
        "/followups/work-center-outcomes/start-next",
        data={"work_view": "mine", "q": "", "state": "", "role": "", "sla": ""},
        follow_redirects=False,
    )
    assert started.status_code in {302, 303}
    assert "/followups/unified/" in started.headers["Location"]
    claims = db.execute(
        """SELECT * FROM followup_episode_events
           WHERE event_type='CLAIMED' ORDER BY id"""
    ).fetchall()
    assert len(claims) == 1
    assert str(claims[0]["actor_username"]) == "admin"


def test_start_next_opens_existing_owned_work_without_duplicate_claim(outcome_app):
    client = client_for(outcome_app)
    first = client.post(
        "/followups/work-center-outcomes/start-next",
        data={"work_view": "mine"},
        follow_redirects=False,
    )
    second = client.post(
        "/followups/work-center-outcomes/start-next",
        data={"work_view": "mine"},
        follow_redirects=False,
    )

    assert first.status_code in {302, 303}
    assert second.status_code in {302, 303}
    assert outcome_app["db"].execute(
        "SELECT COUNT(*) FROM followup_episode_events WHERE event_type='CLAIMED'"
    ).fetchone()[0] == 1


def test_message_queue_requires_approval_permission_not_view_permission(outcome_app):
    from src.security.permissions import Permission
    from src.services.followup_orchestration.work_center_message_service import (
        WorkCenterMessageError,
        WorkCenterMessageService,
    )

    with pytest.raises(WorkCenterMessageError) as captured:
        WorkCenterMessageService(outcome_app["db"]).queue(
            outcome_app["message_episode"],
            actor_username="staff",
            actor_user_id=int(outcome_app["admin"]["id"]),
            permissions=frozenset({Permission.SMS_VIEW}),
        )
    assert captured.value.code == "MESSAGE_APPROVAL_PERMISSION_REQUIRED"
    assert outcome_app["db"].execute(
        "SELECT COUNT(*) FROM engagement_approvals"
    ).fetchone()[0] == 0


def test_disabled_visit_invite_never_creates_approval(outcome_app):
    from src.security.permissions import Permission
    from src.services.followup_orchestration.work_center_message_service import (
        WorkCenterMessageError,
        WorkCenterMessageService,
    )

    db = outcome_app["db"]
    db.execute(
        "UPDATE engagement_events SET is_active=0 WHERE event_key='visit_invite'"
    )
    db.commit()
    with pytest.raises(WorkCenterMessageError) as captured:
        WorkCenterMessageService(db).queue(
            outcome_app["message_episode"],
            actor_username="admin",
            actor_user_id=int(outcome_app["admin"]["id"]),
            permissions=frozenset({Permission.SMS_APPROVAL_REVIEW}),
        )
    assert captured.value.code == "MESSAGE_EVENT_DISABLED"
    assert db.execute("SELECT COUNT(*) FROM engagement_approvals").fetchone()[0] == 0


def test_message_approval_and_episode_link_roll_back_together(
    outcome_app, monkeypatch
):
    from src.adapters.sqlite.followup_episode_repo import FollowupEpisodeRepository
    from src.security.permissions import Permission
    from src.services.followup_orchestration.work_center_message_service import (
        WorkCenterMessageService,
    )

    def fail_link(self, **kwargs):
        raise RuntimeError("link failed")

    monkeypatch.setattr(FollowupEpisodeRepository, "link_source_once", fail_link)
    with pytest.raises(RuntimeError, match="link failed"):
        WorkCenterMessageService(outcome_app["db"]).queue(
            outcome_app["message_episode"],
            actor_username="admin",
            actor_user_id=int(outcome_app["admin"]["id"]),
            permissions=frozenset({Permission.SMS_APPROVAL_REVIEW}),
        )
    assert outcome_app["db"].execute(
        "SELECT COUNT(*) FROM engagement_approvals"
    ).fetchone()[0] == 0
    assert outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_links
           WHERE source_type='ENGAGEMENT_APPROVAL'"""
    ).fetchone()[0] == 0


def test_message_queue_is_atomic_idempotent_and_projection_aware(outcome_app):
    from src.security.permissions import Permission
    from src.services.followup_orchestration.work_center_message_service import (
        WorkCenterMessageService,
    )

    service = WorkCenterMessageService(outcome_app["db"])
    permissions = frozenset({Permission.SMS_APPROVAL_REVIEW})
    first = service.queue(
        outcome_app["message_episode"],
        actor_username="admin",
        actor_user_id=int(outcome_app["admin"]["id"]),
        permissions=permissions,
    )
    second = service.queue(
        outcome_app["message_episode"],
        actor_username="admin",
        actor_user_id=int(outcome_app["admin"]["id"]),
        permissions=permissions,
    )

    assert first["queued"] is True
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["approval_id"] == second["approval_id"]
    assert outcome_app["db"].execute(
        "SELECT COUNT(*) FROM engagement_approvals"
    ).fetchone()[0] == 1
    assert outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_links
           WHERE episode_id=? AND source_type='ENGAGEMENT_APPROVAL'""",
        (outcome_app["message_episode"],),
    ).fetchone()[0] == 1
    assert outcome_app["db"].execute(
        """SELECT COUNT(*) FROM followup_episode_events
           WHERE episode_id=? AND event_type='SMS_QUEUED'""",
        (outcome_app["message_episode"],),
    ).fetchone()[0] == 1


def test_contract_service_filters_clinical_outcomes_and_plan_evidence(monkeypatch):
    from src.security.permissions import Permission
    from src.services.followup_orchestration.work_center_action_service import (
        WorkCenterActionService,
    )
    from src.services.followup_orchestration.work_center_contract_service import (
        WorkCenterContractService,
    )

    clinical_description = {
        "available": True,
        "kind": "clinical",
        "can_complete_clinical": True,
        "can_complete_plan": False,
        "task_contract": {
            "allowed_outcome_types": ["LAB_COMPLETED"],
            "required_fact_keys": ["lab.hba1c"],
            "minimum_verification": "CONFIRMED",
            "canonical_ingestion": "REQUIRED",
            "urgency": "PRIORITY",
        },
    }
    monkeypatch.setattr(
        WorkCenterActionService,
        "describe",
        lambda self, episode_id, permissions: dict(clinical_description),
    )
    clinical = WorkCenterContractService(object()).build(
        "episode-clinical",
        permissions=frozenset({
            Permission.CLINICAL_OUTCOME_RECORD,
            Permission.CLINICAL_TASK_TRANSITION,
            Permission.SMS_APPROVAL_REVIEW,
        }),
    )
    assert clinical["clinical_contract"]["allowed_outcomes"] == [
        {"code": "LAB_COMPLETED", "label": "آزمایش انجام شد"}
    ]
    assert clinical["clinical_contract"]["required_fact_keys"] == ["lab.hba1c"]
    assert clinical["clinical_contract"]["requires_value"] is True
    assert clinical["can_message"] is True

    plan_description = {
        "available": True,
        "kind": "plan",
        "can_complete_clinical": False,
        "can_complete_plan": True,
        "plan_context": {
            "commitment_type": "CALL_CHECK",
            "instruction": "تماس و بررسی وضعیت",
        },
    }
    monkeypatch.setattr(
        WorkCenterActionService,
        "describe",
        lambda self, episode_id, permissions: dict(plan_description),
    )
    plan = WorkCenterContractService(object()).build(
        "episode-plan",
        permissions=frozenset({Permission.FOLLOWUP_PLAN_TRANSITION}),
    )
    assert [item["code"] for item in plan["plan_contract"]["allowed_evidence"]] == [
        "CONTACT_EVENT",
        "MANUAL_VERIFIED",
    ]
    assert "APPOINTMENT" not in {
        item["code"] for item in plan["plan_contract"]["allowed_evidence"]
    }


def test_templates_use_post_start_and_contract_driven_options():
    home = (ROOT / "src/templates/dashboard_v1.html").read_text(encoding="utf-8")
    worklist = (
        ROOT / "src/templates/followups/unified_worklist.html"
    ).read_text(encoding="utf-8")
    detail = (
        ROOT / "src/templates/followups/_structured_contact_detail.html"
    ).read_text(encoding="utf-8")

    assert "work_center_outcomes.start_next" in home
    assert "work_center_outcomes.start_next" in worklist
    assert "focus='first'" not in home
    assert "focus='first'" not in worklist
    assert "clinical_contract.allowed_outcomes" in detail
    assert "clinical_contract.required_fact_keys" in detail
    assert "plan_contract.allowed_evidence" in detail
    assert "permissions.get('sms.view')" not in detail
    assert "Template فعال دعوت ویزیت" in detail
