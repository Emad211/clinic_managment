from __future__ import annotations

import json
from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPECIALIST_ROOT.parent
GUIDE = (
    SPECIALIST_ROOT
    / "docs"
    / "FOLLOWUP_ORCHESTRATION_FO5_LOCAL_UX_ACCEPTANCE.md"
)
LAUNCHER = SPECIALIST_ROOT / "scripts" / "start_fo5_local_review.ps1"


def test_fo5_local_review_guide_is_bound_to_validated_runtime_and_issue():
    guide = GUIDE.read_text(encoding="utf-8")

    assert "Issue:** `#107`" in guide
    assert "94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852" in guide
    assert "2ab1cb1ec956bb9534dea7dd383b76bbf5fb3f5c" in guide
    assert "30865955479" in guide
    assert "801 passed" in guide
    assert "54 passed" in guide
    assert "TEST_ONLY / SYNTHETIC_OR_RESETTABLE" in guide
    assert "Real patient data:** `FORBIDDEN`" in guide
    assert "FO5_UX_ACCEPTED = true|false" in guide
    assert "FO-6 remains blocked" in guide


def test_fo5_review_launcher_uses_canonical_database_and_bounded_flags():
    launcher = LAUNCHER.read_text(encoding="utf-8")

    required_on = (
        "FOLLOWUP_EPISODES_ENABLED",
        "FOLLOWUP_PROJECTION_SHADOW",
        "FOLLOWUP_UNIFIED_WORKLIST_READONLY",
        "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS",
        "FOLLOWUP_AUTO_ROUTING",
        "FOLLOWUP_STRUCTURED_CONTACT",
    )
    required_off = (
        "FOLLOWUP_SMS_AUTO_GUARDED",
        "FOLLOWUP_APPOINTMENT_SYNC",
        "FOLLOWUP_EVIDENCE_ASSIST",
        "FOLLOWUP_AUTOMATION_HEALTH",
    )
    for flag in required_on + required_off:
        assert flag in launcher

    assert '"SPECIALIST_DB_PATH"' in launcher
    assert "SPECIALIST_DATABASE_PATH" not in launcher
    assert "prepare_seeded_followup_view.py" in launcher
    assert "Copy-Item" in launcher
    assert "fo5-local-review-$Stamp.db" in launcher
    assert "PreviousValues" in launcher
    assert "94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852" in launcher
    assert "Acceptance Issue: #107" in launcher


def test_machine_state_has_one_unambiguous_fo5_owner_gate():
    state = json.loads(
        (REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8")
    )
    stream = state["streams"]["followup_orchestration_ux_v1"]
    programs = state["operational_programs"]

    assert state["schema_version"] == "2.6"
    assert stream["current_tranche"] == "FO_6_AUTHORIZED_IMPLEMENTATION_PENDING"
    assert stream["next_gate"] == (
        "FO6_IMPLEMENTATION_ISSUE_AND_PR"
    )
    assert stream["roadmap_progress"] == {
        "model": "TRANCHE_EQUIVALENT",
        "tranche_count": 11,
        "validated_equivalent": 6.0,
        "progress_percent": 54.5,
        "remaining_percent": 45.5,
        "technical_tranches_implemented": 6,
        "technical_implementation_percent": 54.5,
        "fully_accepted_tranches": 6,
        "current_partial_tranche": None,
        "current_partial_credit": 0.0,
        "next_required_gate": "FO6_TECHNICAL_IMPLEMENTATION",
        "not_a_product_wide_readiness_metric": True,
    }
    assert "FOUX_V1_FO_5_TECHNICALLY_VALIDATED_OWNER_UX_PENDING" not in programs
    assert (
        "FOUX_V1_FO_5_VALIDATED_WITH_OWNER_ACCEPTANCE"
        in programs
    )
    assert stream["fo6_allowed"] is True
    assert state["global_freeze"][
        "followup_orchestration_fo7_and_later"
    ].startswith("BLOCKED")


def test_temporary_governance_workflows_are_not_part_of_the_pr():
    workflows = REPO_ROOT / ".github" / "workflows"
    for name in (
        "temp_fo5_technical_attestation.yml",
        "temp_fo5_attestation_runner.yml",
        "temp_fo5_consistency_repair.yml",
        "temp_fo6_authorization.yml",
        "temp_fo6_runner.yml",
        "temp_fo6_test_repair.yml",
    ):
        assert not (workflows / name).exists()
