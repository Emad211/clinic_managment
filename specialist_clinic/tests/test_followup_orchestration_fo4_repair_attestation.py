from __future__ import annotations

import json
from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPECIALIST_ROOT.parent


def test_fo4_repairs_remain_attested_after_owner_acceptance():
    state = json.loads(
        (REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8")
    )
    stream = state["streams"]["followup_orchestration_ux_v1"]
    fo4 = stream["fo4_evidence"]

    assert stream["plan_version"] == "1.8.0"
    assert stream["current_tranche"] == (
        "FO_6_AUTHORIZED_IMPLEMENTATION_PENDING"
    )
    assert stream["fo4_allowed"] is True
    assert stream["fo5_allowed"] is True
    assert stream["fo6_allowed"] is True
    assert fo4["runtime_ui_review_commit"] == (
        "cd243424ecbae98892e0dfde1780bb846554942f"
    )
    assert fo4["local_ux_acceptance"] is True
    assert fo4["critical_ux_defects"] == 0
    assert fo4["status"] == "VALIDATED_WITH_OWNER_ACCEPTANCE"

    seeded = fo4["seeded_worklist_repair"]
    assert seeded["merge_commit"] == (
        "24119671b8b93fdb20db3064a59d416e02d81ef6"
    )
    assert seeded["final_ci_run"] == 30851594179
    assert seeded["explicit_seed_preparation"] is True
    assert seeded["request_time_rebuild"] is False
    assert seeded["manual_test_followups_preserved"] is True
    assert seeded["duplicate_episode_link_event_count"] == 0
    assert seeded["controlled_empty_projection_state"] == (
        "PROJECTION_EMPTY_WITH_SOURCE_DATA"
    )

    sla = fo4["effective_sla_repair"]
    assert sla["merge_commit"] == (
        "cd243424ecbae98892e0dfde1780bb846554942f"
    )
    assert sla["final_ci_run"] == 30852909213
    assert sla["canonical_states"] == [
        "FUTURE",
        "DUE_TODAY",
        "OVERDUE",
        "DUE_UNKNOWN",
        "WAITING",
        "BLOCKED",
        "TERMINAL",
    ]
    assert sla["request_time_effective_filtering"] is True
    assert sla["read_time_write"] is False


def test_plan_and_agent_preserve_fo4_evidence_while_authorizing_fo5():
    plan = (
        SPECIALIST_ROOT
        / "docs"
        / "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md"
    ).read_text(encoding="utf-8")
    agent = (SPECIALIST_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for value in (
        "cd243424ecbae98892e0dfde1780bb846554942f",
        "prepare_seeded_followup_view.py",
    ):
        assert value in plan
        assert value in agent
    assert "Final CI 30844075841" in plan
    assert "CI 30851594179" in plan
    assert "CI 30852909213" in plan
    assert "FO-5 = VALIDATED WITH OWNER ACCEPTANCE" in agent
    assert "FO-6 = AUTHORIZED / IMPLEMENTATION PENDING" in agent
