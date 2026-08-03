from __future__ import annotations

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

    assert "4.8 / 11 = 43.6%" in roadmap
    assert "Remaining                                = 56.4%" in roadmap
    assert "CURRENT = FO-4 Local Owner UX Acceptance" in roadmap
    assert "ISSUE   = #94" in roadmap
    assert "THEN    = separate governance decision whether FO-5 may start" in roadmap
    assert "FO-5  Structured Contact, Retry & Escalation       = BLOCKED" in roadmap


def test_important_governance_docs_link_the_complete_roadmap():
    plan = PLAN.read_text(encoding="utf-8")
    state = (REPO_ROOT / "PROJECT_STATE.md").read_text(encoding="utf-8")
    agent = (SPECIALIST_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    roadmap_name = "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md"

    assert roadmap_name in plan
    assert roadmap_name in state
    assert roadmap_name in agent
    assert "4.8 / 11 = 43.6%" in plan
    assert "Gate progress = 4.8 / 11 = 43.6%" in state
    assert "ROADMAP PROGRESS = 4.8 / 11 = 43.6%" in agent
    assert "cd243424ecbae98892e0dfde1780bb846554942f" in plan
    assert "cd243424ecbae98892e0dfde1780bb846554942f" in state
    assert "cd243424ecbae98892e0dfde1780bb846554942f" in agent
