from __future__ import annotations

import json
from pathlib import Path


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPECIALIST_ROOT.parent
ROADMAP = SPECIALIST_ROOT / "docs" / "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md"
PLAN = SPECIALIST_ROOT / "docs" / "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md"


def test_complete_roadmap_preserves_fo6_through_fo10_and_current_gate():
    roadmap = ROADMAP.read_text(encoding="utf-8")
    for tranche in (
        "FO-6 — Governed SMS Automation & Freshness",
        "FO-7 — Cross-channel Transitions & Operational Outbox",
        "FO-8 — Clinical Evidence Assist",
        "FO-9 — Automation Health & Operational Control",
        "FO-10 — Controlled Pilot, KPI Proof, Cutover & Legacy Retirement",
    ):
        assert tranche in roadmap
    assert "6.0 / 11 = 54.5%" in roadmap
    assert "Remaining = 45.5%" in roadmap
    assert "CURRENT = FO-6 Governed SMS Automation & Freshness implementation" in roadmap
    assert "ISSUE   = #109" in roadmap
    assert "AUTHORIZED_NOT_STARTED" in roadmap
    assert roadmap.count("BLOCKED_NOT_STARTED") >= 4


def test_important_governance_docs_link_the_complete_roadmap():
    plan = PLAN.read_text(encoding="utf-8")
    state = (REPO_ROOT / "PROJECT_STATE.md").read_text(encoding="utf-8")
    agent = (SPECIALIST_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    name = "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md"
    assert name in plan and name in state and name in agent
    assert "6.0 / 11 = 54.5%" in plan
    assert "Gate progress = 6.0 / 11 = 54.5%" in state
    assert "ROADMAP PROGRESS = 6.0 / 11 = 54.5%" in agent
    assert "94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852" in plan
    assert "FO5_UX_ACCEPTED = true" in state
    assert "CURRENT ISSUE = #109" in agent


def test_project_state_json_registers_fo6_authorization_and_future_gates():
    state = json.loads((REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    stream = state["streams"]["followup_orchestration_ux_v1"]
    assert state["schema_version"] == "2.6"
    assert stream["roadmap_version"] == "1.3.0"
    progress = stream["roadmap_progress"]
    assert progress["model"] == "TRANCHE_EQUIVALENT"
    assert progress["tranche_count"] == 11
    assert progress["validated_equivalent"] == 6.0
    assert progress["progress_percent"] == 54.5
    assert progress["remaining_percent"] == 45.5
    assert progress["technical_tranches_implemented"] == 6
    assert progress["technical_implementation_percent"] == 54.5
    assert progress["fully_accepted_tranches"] == 6
    assert progress["current_partial_tranche"] is None
    assert progress["current_partial_credit"] == 0.0
    assert progress["next_required_gate"] == "FO6_TECHNICAL_IMPLEMENTATION"
    assert stream["future_tranches"]["FO-5"] == "VALIDATED_WITH_OWNER_ACCEPTANCE"
    assert stream["future_tranches"]["FO-6"] == "AUTHORIZED_NOT_STARTED"
    assert stream["fo6_allowed"] is True
    assert stream["fo7_allowed"] is False
