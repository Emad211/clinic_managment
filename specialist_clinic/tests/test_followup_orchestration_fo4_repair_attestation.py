from __future__ import annotations

import json
from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPECIALIST_ROOT.parent


def test_fo4_repair_attestation_is_current_and_fo5_remains_blocked():
    state = json.loads((REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    stream = state["streams"]["followup_orchestration_ux_v1"]
    fo4 = stream["fo4_evidence"]

    assert stream["plan_version"] == "1.5.2"
    assert stream["current_tranche"] == "FO_4_LOCAL_OWNER_UX_ACCEPTANCE"
    assert stream["fo4_allowed"] is True
    assert stream["fo5_allowed"] is False
    assert stream["next_gate"] == (
        "ISSUE_94_FO4_LOCAL_OWNER_UX_ACCEPTANCE_ON_CD243424"
    )
    assert fo4["runtime_ui_review_commit"] == (
        "cd243424ecbae98892e0dfde1780bb846554942f"
    )

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


def test_plan_and_agent_point_owner_to_repaired_runtime_commit():
    plan = (
        SPECIALIST_ROOT
        / "docs"
        / "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md"
    ).read_text(encoding="utf-8")
    agent = (SPECIALIST_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for text in (plan, agent):
        assert "cd243424ecbae98892e0dfde1780bb846554942f" in text
        assert "prepare_seeded_followup_view.py" in text
        assert "FO-5" in text
        assert "BLOCKED" in text
    assert "Final CI 30844075841" in plan
    assert "CI 30851594179" in plan
    assert "CI 30852909213" in plan
