from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_seed_repair_maps_fixture_rows_and_preserves_other_tasks():
    repository = (
        ROOT / "src" / "adapters" / "sqlite" / "demo_cohort_repo.py"
    ).read_text(encoding="utf-8")
    assert "demo_followup_task_id:" in repository
    assert "SELECT value FROM settings WHERE key=?" in repository
    assert "ON CONFLICT(key) DO UPDATE SET value=excluded.value" in repository
    assert "COUNT(DISTINCT task.id)" in repository
    assert '"followups": "followup_tasks"' not in repository
    assert "source_engine='demo_cohort'" not in repository
    assert "SET due_date=?, reason=?, detail=?, status=?, assigned_to=?" in repository
    assert "fixture_national_id: str" in repository
    assert "fixture_national_id=national_id" in repository
    assert "patient['national_id']" not in repository
    assert "user-created TEST-patient tasks untouched" in repository
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
