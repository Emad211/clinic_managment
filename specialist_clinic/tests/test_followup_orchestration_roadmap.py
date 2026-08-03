from __future__ import annotations

import json
from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPECIALIST_ROOT.parent
ROADMAP = (
    SPECIALIST_ROOT
    / "docs"
    / "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md"
)
PLAN = (
    SPECIALIST_ROOT
    / "docs"
    / "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md"
)


def test_complete_roadmap_preserves_fo5_through_fo10_and_current_gate():
    roadmap = ROADMAP.read_text(encoding="utf-8")
    for tranche in (
        "FO-5 — Structured Contact, Retry & Escalation",
        "FO-6 — Governed SMS Automation & Freshness",
        "FO-7 — Cross-channel Transitions & Operational Outbox",
        "FO-8 — Clinical Evidence Assist",
        "FO-9 — Automation Health & Operational Control",
        "FO-10 — Controlled Pilot, KPI Proof, Cutover & Legacy Retirement",
    ):
        assert tranche in roadmap

    assert "5.0 / 11 = 45.5%" in roadmap
    assert "54.5%" in roadmap
    assert "CURRENT = FO-5 Structured Contact implementation" in roadmap
    assert "ISSUE   = #103" in roadmap
    assert (
        "FO-5 technical validation and local owner UX acceptance"
        in roadmap
    )
    assert "AUTHORIZED_NOT_STARTED" in roadmap
    assert roadmap.count("BLOCKED_NOT_STARTED") >= 5


def test_important_governance_docs_link_the_complete_roadmap():
    plan = PLAN.read_text(encoding="utf-8")
    state = (REPO_ROOT / "PROJECT_STATE.md").read_text(encoding="utf-8")
    agent = (SPECIALIST_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    roadmap_name = "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md"

    assert roadmap_name in plan
    assert roadmap_name in state
    assert roadmap_name in agent
    assert "5.0 / 11 = 45.5%" in plan
    assert "Gate progress = 5.0 / 11 = 45.5%" in state
    assert "ROADMAP PROGRESS = 5.0 / 11 = 45.5%" in agent
    assert "cd243424ecbae98892e0dfde1780bb846554942f" in plan
    assert "cd243424ecbae98892e0dfde1780bb846554942f" in state
    assert "cd243424ecbae98892e0dfde1780bb846554942f" in agent


def test_project_state_json_registers_fo5_authorization_and_future_gates():
    state = json.loads(
        (REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8")
    )
    stream = state["streams"]["followup_orchestration_ux_v1"]

    assert state["schema_version"] == "2.4"
    assert stream["canonical_roadmap"].endswith(
        "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md"
    )
    assert stream["roadmap_version"] == "1.0.0"

    progress = stream["roadmap_progress"]
    assert progress["model"] == "TRANCHE_EQUIVALENT"
    assert progress["tranche_count"] == 11
    assert progress["validated_equivalent"] == 5.0
    assert progress["progress_percent"] == 45.5
    assert progress["remaining_percent"] == 54.5
    assert progress["technical_tranches_implemented"] == 5
    assert progress["technical_implementation_percent"] == 45.5
    assert progress["fully_accepted_tranches"] == 5
    assert progress["current_partial_tranche"] is None
    assert progress["current_partial_credit"] == 0.0
    assert progress["next_required_gate"] == "FO5_TECHNICAL_IMPLEMENTATION"
    assert progress["not_a_product_wide_readiness_metric"] is True

    assert list(stream["future_tranches"]) == [
        "FO-5",
        "FO-6",
        "FO-7",
        "FO-8",
        "FO-9",
        "FO-10",
    ]
    assert stream["future_tranches"]["FO-5"] == "AUTHORIZED_NOT_STARTED"
    assert stream["fo5_allowed"] is True
    assert stream["fo6_allowed"] is False
    assert state["global_freeze"][
        "followup_orchestration_fo6_and_later"
    ].startswith("BLOCKED")
