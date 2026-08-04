from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPECIALIST = ROOT / "specialist_clinic"


def test_fo5_owner_acceptance_and_fo6_authorization_are_consistent():
    state = json.loads((ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    stream = state["streams"]["followup_orchestration_ux_v1"]

    assert stream["plan_version"] == "1.8.0"
    assert stream["roadmap_version"] == "1.3.0"
    assert stream["current_tranche"] == "FO_6_AUTHORIZED_IMPLEMENTATION_PENDING"
    fo5 = stream["fo5_evidence"]
    assert fo5["local_ux_acceptance"] is True
    assert fo5["reviewer"] == "Emad211"
    assert fo5["reviewed_commit"] == "94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852"
    assert fo5["reviewed_on_test_data"] is True
    assert fo5["critical_ux_defects"] == 0
    assert fo5["status"] == "VALIDATED_WITH_OWNER_ACCEPTANCE"

    auth = stream["fo6_authorization"]
    assert auth["tracking_issue"] == 109
    assert auth["governance_pr"] == 110
    assert auth["scope"] == "ADMINISTRATIVE_CARE_SMS_FRESHNESS_AUTO_GUARDED_ONLY"
    assert auth["feature_flag"] == "FOLLOWUP_SMS_AUTO_GUARDED"
    assert auth["default_enabled"] is False
    assert auth["policy_levels"] == [
        "CLINICIAN_ONLY", "MANUAL_APPROVAL", "AUTO_GUARDED"
    ]
    assert auth["initial_auto_guard_allowlist"] == [
        "appointment_reminder", "refill_due"
    ]
    assert auth["purpose"] == "CARE_ONLY"
    assert auth["approval_ttl_hours_default"] == 24
    assert auth["approval_ttl_hours_bounds"] == [1, 72]
    assert auth["status"] == "AUTHORIZED"
    assert stream["fo6_allowed"] is True
    assert stream["fo7_allowed"] is False
    assert stream["feature_flags"]["FOLLOWUP_SMS_AUTO_GUARDED"] is False
    assert stream["next_gate"] == "FO6_IMPLEMENTATION_ISSUE_AND_PR"

    progress = stream["roadmap_progress"]
    assert progress["validated_equivalent"] == 6.0
    assert progress["progress_percent"] == 54.5
    assert progress["remaining_percent"] == 45.5
    assert progress["fully_accepted_tranches"] == 6
    assert progress["current_partial_tranche"] is None
    assert progress["next_required_gate"] == "FO6_TECHNICAL_IMPLEMENTATION"

    freeze = state["global_freeze"]
    assert freeze["followup_orchestration_fo5"] == "VALIDATED_WITH_OWNER_ACCEPTANCE"
    assert freeze["followup_orchestration_fo6"].startswith("AUTHORIZED_IMPLEMENTATION_ONLY")
    assert freeze["followup_orchestration_fo7_and_later"].startswith("BLOCKED")

    programs = state["operational_programs"]
    assert "FOUX_V1_FO_5_TECHNICALLY_VALIDATED_OWNER_UX_PENDING" not in programs
    assert "FOUX_V1_FO_6_AND_LATER_BLOCKED" not in programs
    assert "FOUX_V1_FO_5_VALIDATED_WITH_OWNER_ACCEPTANCE" in programs
    assert "FOUX_V1_FO_6_AUTHORIZED_NOT_STARTED" in programs
    assert "FOUX_V1_FO_7_AND_LATER_BLOCKED" in programs


def test_docs_keep_fo6_bounded_and_fo7_blocked():
    plan = (SPECIALIST / "docs" / "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    roadmap = (SPECIALIST / "docs" / "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md").read_text(encoding="utf-8")
    agent = (SPECIALIST / "AGENTS.md").read_text(encoding="utf-8")

    for value in (
        "FO5_UX_ACCEPTED = true",
        "FO_6_AUTHORIZED_IMPLEMENTATION_PENDING",
        "appointment_reminder",
        "refill_due",
        "CLINICIAN_ONLY",
        "AUTO_GUARDED",
        "FOLLOWUP_SMS_AUTO_GUARDED",
        "FO-7 AND LATER = BLOCKED",
    ):
        assert value in plan or value in roadmap or value in agent
    assert "campaign/MARKETING/free-text" in plan
    assert "CURRENT = FO-6 Governed SMS Automation" in roadmap


def test_temporary_fo6_governance_workflows_are_absent():
    workflows = ROOT / ".github" / "workflows"
    for name in (
        "temp_fo6_authorization.yml",
        "temp_fo6_runner.yml",
        "temp_fo6_test_repair.yml",
    ):
        assert not (workflows / name).exists()
