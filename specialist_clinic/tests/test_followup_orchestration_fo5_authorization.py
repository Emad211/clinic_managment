from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPECIALIST = ROOT / "specialist_clinic"


def test_fo4_owner_acceptance_and_fo5_authorization_are_consistent():
    state = json.loads(
        (ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8")
    )
    stream = state["streams"]["followup_orchestration_ux_v1"]
    assert stream["plan_version"] == "1.6.0"
    assert stream["current_tranche"] == (
        "FO_5_AUTHORIZED_IMPLEMENTATION_PENDING"
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
    assert stream["fo5_allowed"] is True
    assert stream["fo6_allowed"] is False
    assert stream["feature_flags"]["FOLLOWUP_STRUCTURED_CONTACT"] is False
    progress = stream["roadmap_progress"]
    assert progress["validated_equivalent"] == 5.0
    assert progress["progress_percent"] == 45.5
    assert progress["remaining_percent"] == 54.5
    freeze = state["global_freeze"]
    assert "followup_orchestration_fo5_and_later" not in freeze
    assert freeze["followup_orchestration_fo5"].startswith(
        "AUTHORIZED_IMPLEMENTATION_ONLY"
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

    assert "FO_5_AUTHORIZED_IMPLEMENTATION_PENDING" in plan
    assert "FO_6_AND_LATER_BLOCKED" in plan
    assert "FO-5 Structured Contact implementation" in roadmap
    assert "AUTHORIZED_NOT_STARTED" in roadmap
    assert "FO-5 = AUTHORIZED / IMPLEMENTATION PENDING" in agent
    assert "FO-6 and later = BLOCKED" in agent
    assert "FOLLOWUP_STRUCTURED_CONTACT" in plan
    assert "SMS automation" in plan
