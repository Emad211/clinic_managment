from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from src.adapters.sqlite.followup_operations_schema import ensure_followup_operations_storage
from src.adapters.sqlite.followup_projection_repo import FollowupProjectionRepository
from src.services.followup_orchestration.backfill import FollowupEpisodeBackfillService
from src.services.followup_orchestration.projection_service import FollowupProjectionService

SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SPECIALIST_ROOT / "scripts" / "rebuild_followup_projection.py"


def _fo1_module():
    path = Path(__file__).with_name("test_followup_orchestration_fo1.py")
    spec = importlib.util.spec_from_file_location("fo1_fixture_module", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _upgrade_fo1_fixture_to_authoritative_state_schema(
    db: sqlite3.Connection,
) -> None:
    """Give the compact FO-1 identity fixture the lifecycle columns FO-2 reads."""
    db.executescript(
        """
        ALTER TABLE clinical_task_events ADD COLUMN supersedes_event_id INTEGER;
        ALTER TABLE clinical_task_events ADD COLUMN due_at TEXT;
        ALTER TABLE clinical_task_events ADD COLUMN assigned_to TEXT;

        ALTER TABLE clinical_outcome_events ADD COLUMN verification TEXT;
        ALTER TABLE clinical_outcome_events ADD COLUMN observed_at TEXT;
        ALTER TABLE clinical_outcome_events ADD COLUMN outcome_type TEXT;

        ALTER TABLE care_plan_commitments ADD COLUMN commitment_type TEXT;

        ALTER TABLE care_plan_commitment_events ADD COLUMN supersedes_event_id INTEGER;
        ALTER TABLE care_plan_commitment_events ADD COLUMN status TEXT;
        ALTER TABLE care_plan_commitment_events ADD COLUMN due_at TEXT;
        ALTER TABLE care_plan_commitment_events ADD COLUMN assigned_to TEXT;
        ALTER TABLE care_plan_commitment_events ADD COLUMN evidence_type TEXT;
        ALTER TABLE care_plan_commitment_events ADD COLUMN outcome_code TEXT;

        UPDATE clinical_task_events
        SET due_at='2026-08-12 00:00:00', assigned_to='nurse-1'
        WHERE id=11;

        UPDATE clinical_outcome_events
        SET verification='CONFIRMED',
            observed_at='2026-08-02 10:30:00',
            outcome_type='LAB_COMPLETED'
        WHERE id=12;

        UPDATE care_plan_commitments
        SET commitment_type='LAB_REVIEW'
        WHERE commitment_id='commit-1';

        UPDATE care_plan_commitment_events
        SET status='SCHEDULED',
            due_at='2026-08-13 09:00:00',
            assigned_to='nurse-2'
        WHERE id=1;
        """
    )
    db.commit()


def _db() -> sqlite3.Connection:
    module = _fo1_module()
    db = module._db()
    _upgrade_fo1_fixture_to_authoritative_state_schema(db)
    FollowupEpisodeBackfillService(db).run(apply=True)
    ensure_followup_operations_storage(db)
    return db


def _source_snapshot(db: sqlite3.Connection) -> str:
    return _fo1_module()._source_snapshot(db)


def test_projection_schema_is_additive_and_idempotent():
    db = _db()
    ensure_followup_operations_storage(db)
    ensure_followup_operations_storage(db)
    tables = {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "followup_work_item_projection" in tables
    assert db.execute(
        "SELECT COUNT(*) FROM followup_work_item_projection"
    ).fetchone()[0] == 0


def test_same_source_snapshot_produces_same_projection_hash():
    db = _db()
    service = FollowupProjectionService(db)
    first = service.build_rows(
        as_of_at="2026-08-03 12:00:00",
        rebuilt_at="2026-08-03 12:01:00",
    )
    second = service.build_rows(
        as_of_at="2026-08-03 12:00:00",
        rebuilt_at="2026-08-03 12:10:00",
    )
    assert service.set_hash(first) == service.set_hash(second)
    assert [row["projection_hash"] for row in first] == [
        row["projection_hash"] for row in second
    ]
    assert [row["rebuilt_at"] for row in first] != [
        row["rebuilt_at"] for row in second
    ]


def test_every_nonterminal_projection_has_exactly_one_explanation():
    rows = FollowupProjectionService(_db()).build_rows(
        as_of_at="2026-08-03 12:00:00",
        rebuilt_at="2026-08-03 12:01:00",
    )
    assert len(rows) == 4
    for row in rows:
        explanations = [
            bool(row.get("next_action_code")),
            bool(row.get("waiting_reason_code")),
            bool(row.get("blocked_reason_code")),
        ]
        if row["state_class"] == "TERMINAL":
            assert sum(explanations) == 0
            assert row["owner_role_proposal"] is None
        else:
            assert sum(explanations) == 1
            assert row["owner_role_proposal"] in {
                "RECEPTION",
                "NURSING",
                "PHYSICIAN",
                "MANAGER",
            }
        assert row["owner_user_id"] is None


def test_policy_maps_canonical_fo1_fixture_without_mutation():
    db = _db()
    before = _source_snapshot(db)
    rows = FollowupProjectionService(db).build_rows(
        as_of_at="2026-08-03 12:00:00",
        rebuilt_at="2026-08-03 12:01:00",
    )
    assert _source_snapshot(db) == before

    by_reason = {row["reason_code"]: row for row in rows}
    assert by_reason["LAPSED"]["state_class"] == "ACTION_REQUIRED"
    assert by_reason["LAPSED"]["next_action_code"] == "REVIEW_SMS"
    assert by_reason["LAPSED"]["owner_role_proposal"] == "RECEPTION"

    assert by_reason["CLINICAL_TASK"]["state_class"] == "ACTION_REQUIRED"
    assert by_reason["CLINICAL_TASK"]["next_action_code"] == "REVIEW_CLINICAL_EVIDENCE"
    assert by_reason["CLINICAL_TASK"]["owner_role_proposal"] == "NURSING"

    assert by_reason["ENCOUNTER_COMMITMENT"]["state_class"] == "WAITING"
    assert by_reason["ENCOUNTER_COMMITMENT"]["waiting_reason_code"] == "WAITING_FOR_APPOINTMENT"

    assert by_reason["ADMIN_FOLLOWUP"]["state_class"] == "WAITING"
    assert by_reason["ADMIN_FOLLOWUP"]["waiting_reason_code"] == "WAITING_UNTIL_ACTION_DUE"


def test_projection_apply_is_atomic_and_rebuild_equivalent():
    db = _db()
    service = FollowupProjectionService(db)
    first = service.run(as_of_at="2026-08-03 12:00:00", apply=True)
    repository = FollowupProjectionRepository(db)
    stored_first = repository.list_all()
    first_set_hash = repository.set_hash()

    db.execute("DELETE FROM followup_work_item_projection")
    db.commit()
    second = service.run(as_of_at="2026-08-03 12:00:00", apply=True)
    stored_second = repository.list_all()

    assert first["projection_count"] == 4
    assert second["projection_count"] == 4
    assert first["projection_set_hash"] == second["projection_set_hash"]
    assert first_set_hash == repository.set_hash()
    assert [row["projection_hash"] for row in stored_first] == [
        row["projection_hash"] for row in stored_second
    ]
    for row in stored_second:
        assert isinstance(json.loads(row["state_detail_json"]), dict)


def test_parity_is_complete_and_explainable_for_canonical_fixture():
    db = _db()
    result = FollowupProjectionService(db).run(
        as_of_at="2026-08-03 12:00:00",
        apply=False,
    )
    parity = result["parity"]
    assert parity["legacy_open_count"] == 4
    assert parity["matched_legacy_sources"] == 4
    assert parity["coverage_percent"] == 100.0
    assert parity["hidden_legacy_source_count"] == 0
    assert parity["explainable_mismatch_percent"] == 100.0


def test_missing_source_becomes_blocked_and_mismatch_is_classified():
    db = _db()
    db.execute("DELETE FROM followup_tasks WHERE id=4")
    db.commit()
    service = FollowupProjectionService(db)
    rows = service.build_rows(
        as_of_at="2026-08-03 12:00:00",
        rebuilt_at="2026-08-03 12:01:00",
    )
    blocked = [
        row
        for row in rows
        if row["blocked_reason_code"] == "SOURCE_STATE_UNAVAILABLE"
    ]
    assert len(blocked) == 1
    assert blocked[0]["owner_role_proposal"] == "MANAGER"
    assert "ADMIN_TASK_NOT_FOUND" in blocked[0]["state_detail_json"]["error_codes"]

    parity = service.parity_report(rows)
    assert parity["explainable_mismatch_percent"] == 100.0
    assert parity["projection_only_reasons"] == {
        "BLOCKED_EPISODE_WITHOUT_LEGACY_OPEN_SOURCE": 1
    }


def test_patient_scope_drift_fails_closed():
    db = _db()
    db.execute("UPDATE followup_tasks SET patient_link_id=1 WHERE id=4")
    db.commit()
    rows = FollowupProjectionService(db).build_rows(
        as_of_at="2026-08-03 12:00:00",
        rebuilt_at="2026-08-03 12:01:00",
    )
    blocked = [row for row in rows if row["state_class"] == "BLOCKED"]
    assert len(blocked) == 1
    assert "SOURCE_PATIENT_MISMATCH" in blocked[0]["state_detail_json"]["error_codes"]


def test_shadow_report_contains_no_phi_fields():
    payload = FollowupProjectionService(_db()).run(
        as_of_at="2026-08-03 12:00:00",
        apply=False,
    )
    rendered = json.dumps(payload, ensure_ascii=False)
    lowered = rendered.lower()
    assert "full_name" not in lowered
    assert "phone_number" not in lowered
    assert "message" not in lowered
    assert "note" not in lowered


def test_cli_apply_requires_explicit_shadow_flag(tmp_path):
    fixture = _db()
    database = tmp_path / "specialist.db"
    target = sqlite3.connect(database)
    fixture.backup(target)
    target.close()
    fixture.close()

    env = os.environ.copy()
    env.pop("FOLLOWUP_PROJECTION_SHADOW", None)
    denied = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--database",
            str(database),
            "--as-of",
            "2026-08-03 12:00:00",
            "--apply",
        ],
        cwd=SPECIALIST_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert denied.returncode != 0
    assert "requires FOLLOWUP_PROJECTION_SHADOW=1" in (
        denied.stdout + denied.stderr
    )

    env["FOLLOWUP_PROJECTION_SHADOW"] = "1"
    allowed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--database",
            str(database),
            "--as-of",
            "2026-08-03 12:00:00",
            "--apply",
        ],
        cwd=SPECIALIST_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(allowed.stdout)
    assert payload["shadow_only"] is True
    assert payload["source_truth_unchanged"] is True
    assert payload["projection_count"] == 4


def test_fo2_does_not_wire_projection_into_ui_or_scheduler():
    forbidden = (
        SPECIALIST_ROOT / "src" / "api",
        SPECIALIST_ROOT / "src" / "templates",
        SPECIALIST_ROOT / "src" / "services" / "scheduler.py",
    )
    violations = []
    for root in forbidden:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if path.is_file() and path.suffix.lower() in {".py", ".html", ".js"}:
                text = path.read_text(encoding="utf-8")
                if "FOLLOWUP_PROJECTION_SHADOW" in text or "followup_work_item_projection" in text:
                    violations.append(str(path.relative_to(SPECIALIST_ROOT)))
    assert violations == []
