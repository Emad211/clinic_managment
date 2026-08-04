from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPECIALIST = ROOT / "specialist_clinic"


def test_fo5_technical_validation_and_owner_gate_are_consistent():
    state = json.loads(
        (ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8")
    )
    stream = state["streams"]["followup_orchestration_ux_v1"]
    assert stream["plan_version"] == "1.7.0"
    assert stream["current_tranche"] == (
        "FO_5_LOCAL_OWNER_UX_ACCEPTANCE"
    )
    assert stream["fo4_evidence"]["local_ux_acceptance"] is True
    assert stream["fo4_evidence"]["critical_ux_defects"] == 0
    assert stream["fo4_evidence"]["reviewed_commit"] == (
        "cd243424ecbae98892e0dfde1780bb846554942f"
    )
    authorization = stream["fo5_authorization"]
    assert authorization["tracking_issue"] == 103
    assert authorization["governance_pr"] == 104
    assert authorization["scope"] == (
        "STRUCTURED_CONTACT_RETRY_ESCALATION_ONLY"
    )
    assert authorization["default_enabled"] is False
    assert authorization["status"] == "VALIDATED"
    evidence = stream["fo5_evidence"]
    assert evidence["tracking_issue"] == 105
    assert evidence["implementation_pr"] == 106
    assert evidence["final_head"] == (
        "2ab1cb1ec956bb9534dea7dd383b76bbf5fb3f5c"
    )
    assert evidence["merge_commit"] == (
        "94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852"
    )
    assert evidence["final_ci_run"] == 30865955479
    assert evidence["specialist_tests_passed"] == 801
    assert evidence["accounting_tests_passed"] == 54
    assert evidence["threshold_callback_cleared_in_source_truth"] is True
    assert evidence["routing_kill_switch_required"] is True
    assert evidence["jalali_callback_input"] is True
    assert evidence["owner_acceptance_issue"] == 107
    assert evidence["local_ux_acceptance"] == "PENDING"
    assert evidence["status"] == "TECHNICALLY_VALIDATED_OWNER_UX_PENDING"
    assert stream["fo5_allowed"] is True
    assert stream["fo6_allowed"] is False
    assert stream["feature_flags"]["FOLLOWUP_STRUCTURED_CONTACT"] is False
    progress = stream["roadmap_progress"]
    assert progress["validated_equivalent"] == 5.8
    assert progress["progress_percent"] == 52.7
    assert progress["remaining_percent"] == 47.3
    freeze = state["global_freeze"]
    assert "followup_orchestration_fo5_and_later" not in freeze
    assert freeze["followup_orchestration_fo5"].startswith(
        "TECHNICALLY_VALIDATED_OWNER_UX_REVIEW_OR_FOCUSED_DEFECT_FIX_ONLY"
    )
    assert freeze["followup_orchestration_fo6_and_later"].startswith(
        "BLOCKED"
    )


def test_docs_keep_fo5_bounded_and_fo6_blocked():
    plan = (
        SPECIALIST
        / "docs"
        / "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md"
    ).read_text(encoding="utf-8")
    roadmap = (
        SPECIALIST
        / "docs"
        / "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md"
    ).read_text(encoding="utf-8")
    agent = (SPECIALIST / "AGENTS.md").read_text(encoding="utf-8")

    assert "FO_5_TECHNICALLY_VALIDATED_OWNER_UX_PENDING" in plan
    assert "FO_6_AND_LATER_BLOCKED" in plan
    assert "FO-5 Local Owner UX Acceptance" in roadmap
    assert "TECHNICALLY_VALIDATED_OWNER_UX_PENDING" in roadmap
    assert "FO-5 = TECHNICALLY VALIDATED / OWNER UX PENDING" in agent
    assert "FO-6 and later = BLOCKED" in agent
    assert "FOLLOWUP_STRUCTURED_CONTACT" in plan
    assert "SMS automation" in plan
