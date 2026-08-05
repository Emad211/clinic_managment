from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from test_frontend_automation_work_center_outcomes_v2 import (
    client_for,
    outcome_app,
)


ROOT = Path(__file__).resolve().parents[1]


def test_work_center_list_loads_progressive_drawer_assets_only(outcome_app):
    client = client_for(outcome_app)
    listing = client.get("/followups/unified/?view=all")
    detail = client.get(
        f"/followups/unified/{outcome_app['message_episode']}?view=all"
    )
    list_html = listing.get_data(as_text=True)
    detail_html = detail.get_data(as_text=True)

    assert listing.status_code == 200
    assert "/static/js/work-center-drawer-v2.js" in list_html
    assert "/static/css/work-center-drawer-v2.css" in list_html
    assert "/static/css/work-center-actions-v2.css" in list_html
    assert "/static/js/work-center-drawer-v2.js" not in detail_html
    assert "work-item-drawer" in detail_html

    for path in (
        "/static/js/work-center-drawer-v2.js",
        "/static/css/work-center-drawer-v2.css",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.data


def test_handle_post_keeps_full_page_fallback_without_javascript(outcome_app):
    client = client_for(outcome_app)
    episode_id = outcome_app["message_episode"]
    response = client.post(
        f"/followups/unified/{episode_id}/handle",
        data={
            "work_view": "all",
            "expected_event_id": "0",
            "idempotency_key": f"full-page-fallback:{episode_id}:0001",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert f"/followups/unified/{episode_id}" in response.headers["Location"]
    page = client.get(response.headers["Location"])
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "رسیدگی به" in html
    assert "work-item-drawer" in html


def test_drawer_script_is_progressive_and_never_invents_mutations():
    script = (
        ROOT / "src/static/js/work-center-drawer-v2.js"
    ).read_text(encoding="utf-8")

    assert "DOMParser" in script
    assert "fetch(target" in script
    assert "redirect: 'follow'" in script
    assert "/\\/followups\\/unified\\/.+\\/handle$/" in script
    assert "window.location.assign" in script
    assert "role=\"dialog\"" in script
    assert "aria-modal=\"true\"" in script
    assert "event.key === 'Escape'" in script
    assert "requestSubmit" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "method: 'DELETE'" not in script


def test_drawer_javascript_is_syntactically_valid_when_node_is_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed in this test environment")
    result = subprocess.run(
        [node, "--check", str(ROOT / "src/static/js/work-center-drawer-v2.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_unified_rollout_absorbs_control_room_and_blocks_free_text_sms(outcome_app):
    client = client_for(outcome_app)

    index = client.get("/control-room/", follow_redirects=False)
    assert index.status_code in {302, 303}
    assert "/followups/unified/" in index.headers["Location"]
    assert "view=manager" in index.headers["Location"]

    sms = client.post(
        "/control-room/sms",
        data={"cohort": "lapsed", "body": "متن آزاد قدیمی"},
        follow_redirects=False,
    )
    assert sms.status_code == 404

    recall = client.post(
        "/control-room/recall",
        data={"cohort": "unknown-cohort"},
        follow_redirects=False,
    )
    assert recall.status_code in {302, 303}
    assert "/followups/unified/" in recall.headers["Location"]


def test_legacy_control_room_still_renders_when_unified_flag_is_off(outcome_app):
    app = outcome_app["app"]
    client = client_for(outcome_app)
    app.config["FOLLOWUP_UNIFIED_WORKLIST_READONLY"] = False
    try:
        response = client.get("/control-room/")
    finally:
        app.config["FOLLOWUP_UNIFIED_WORKLIST_READONLY"] = True
    assert response.status_code == 200
    assert "control-room" in response.get_data(as_text=True).lower() or "اتاق" in response.get_data(as_text=True)


def test_consent_default_approval_and_episode_link_roll_back_together(
    outcome_app, monkeypatch
):
    from src.adapters.sqlite.followup_episode_repo import FollowupEpisodeRepository
    from src.security.permissions import Permission
    from src.services.followup_orchestration.work_center_message_service import (
        WorkCenterMessageService,
    )

    db = outcome_app["db"]
    patient_id = int(
        db.execute(
            "SELECT patient_link_id FROM followup_tasks WHERE id=?",
            (outcome_app["message_task"],),
        ).fetchone()["patient_link_id"]
    )
    db.execute("DELETE FROM sms_consent_events WHERE patient_link_id=?", (patient_id,))
    db.commit()

    def fail_link(self, **kwargs):
        raise RuntimeError("episode link failed")

    monkeypatch.setattr(FollowupEpisodeRepository, "link_source_once", fail_link)
    with pytest.raises(RuntimeError, match="episode link failed"):
        WorkCenterMessageService(db).queue(
            outcome_app["message_episode"],
            actor_username="admin",
            actor_user_id=int(outcome_app["admin"]["id"]),
            permissions=frozenset({Permission.SMS_APPROVAL_REVIEW}),
        )

    assert db.execute(
        "SELECT COUNT(*) FROM sms_consent_events WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM engagement_approvals").fetchone()[0] == 0
    assert db.execute(
        """SELECT COUNT(*) FROM followup_episode_links
           WHERE source_type='ENGAGEMENT_APPROVAL'"""
    ).fetchone()[0] == 0


def test_checkpoint4_scope_stays_narrow():
    control_room = (ROOT / "src/api/control_room.py").read_text(encoding="utf-8")
    automation_base = (
        ROOT / "src/templates/automation_base.html"
    ).read_text(encoding="utf-8")
    drawer = (ROOT / "src/static/js/work-center-drawer-v2.js").read_text(
        encoding="utf-8"
    )

    assert "FOLLOWUP_UNIFIED_WORKLIST_READONLY" in control_room
    assert "abort(404)" in control_room
    assert "work-center-drawer-v2.js" in automation_base
    assert "request.endpoint == 'unified_followups.index'" in automation_base
    assert "document.importNode(workspace, true)" in drawer
    assert "Full-page" not in drawer  # implementation stays behavior-focused
