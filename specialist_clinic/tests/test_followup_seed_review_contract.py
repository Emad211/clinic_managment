from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_seed_repair_marks_fixture_rows_and_preserves_other_tasks():
    repository = (
        ROOT / "src" / "adapters" / "sqlite" / "demo_cohort_repo.py"
    ).read_text(encoding="utf-8")
    assert "source_engine='demo_cohort'" in repository
    assert "demo-followup:" in repository
    assert "User-created administrative tasks" in repository
    assert "synthetic follow-up fixture shape changed" not in repository


def test_orchestration_service_uses_persistence_adapter():
    service = (
        ROOT / "src" / "services" / "followup_orchestration"
        / "demo_seed_preparation.py"
    ).read_text(encoding="utf-8")
    adapter = (
        ROOT / "src" / "adapters" / "sqlite"
        / "demo_seed_followup_repo.py"
    ).read_text(encoding="utf-8")
    assert "DemoSeedFollowupRepository" in service
    assert "SELECT " not in service.upper()
    assert "WITH demo_patients AS" in adapter
