from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPECIALIST_ROOT.parent
SRC_ROOT = SPECIALIST_ROOT / "src"
PLAN_PATH = (
    SPECIALIST_ROOT
    / "docs"
    / "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md"
)
BASELINE_PATH = (
    SPECIALIST_ROOT / "docs" / "FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md"
)
CAPTURE_PATH = SPECIALIST_ROOT / "scripts" / "capture_followup_fo0_baseline.py"

EXPECTED_FLAGS = (
    "FOLLOWUP_EPISODES_ENABLED",
    "FOLLOWUP_PROJECTION_SHADOW",
    "FOLLOWUP_UNIFIED_WORKLIST_READONLY",
    "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS",
    "FOLLOWUP_AUTO_ROUTING",
    "FOLLOWUP_STRUCTURED_CONTACT",
    "FOLLOWUP_SMS_AUTO_GUARDED",
    "FOLLOWUP_APPOINTMENT_SYNC",
    "FOLLOWUP_EVIDENCE_ASSIST",
    "FOLLOWUP_AUTOMATION_HEALTH",
)
FOUX_SCHEMA_NAMES = (
    "followup_episodes",
    "followup_episode_links",
    "followup_episode_events",
    "followup_work_item_projection",
    "automation_decision_events",
    "operational_outbox",
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_capture_module():
    spec = importlib.util.spec_from_file_location("fo0_capture", CAPTURE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_baseline_fixture(path: Path) -> None:
    db = sqlite3.connect(path)
    try:
        db.executescript(
            """
            CREATE TABLE patient_links (
                id INTEGER PRIMARY KEY,
                full_name TEXT,
                phone_number TEXT,
                is_active INTEGER NOT NULL
            );
            CREATE TABLE followup_tasks (
                id INTEGER PRIMARY KEY,
                status TEXT,
                source_engine TEXT,
                assigned_to TEXT,
                due_date TEXT
            );
            CREATE TABLE clinical_task_events (
                id INTEGER PRIMARY KEY,
                status TEXT,
                assigned_to TEXT,
                supersedes_event_id INTEGER
            );
            CREATE TABLE care_plan_commitment_events (
                id INTEGER PRIMARY KEY,
                status TEXT,
                assigned_to TEXT,
                supersedes_event_id INTEGER
            );
            CREATE TABLE engagement_approvals (
                id INTEGER PRIMARY KEY,
                status TEXT
            );
            CREATE TABLE engagement_dispatch (
                id INTEGER PRIMARY KEY
            );
            CREATE TABLE sms_messages (
                id INTEGER PRIMARY KEY,
                status TEXT,
                delivery_status TEXT
            );
            CREATE TABLE sms_campaigns (
                id INTEGER PRIMARY KEY,
                status TEXT,
                scheduled_at TEXT
            );
            CREATE TABLE appointments (
                id INTEGER PRIMARY KEY,
                status TEXT
            );
            CREATE TABLE followup_contact_events (
                id INTEGER PRIMARY KEY,
                task_id INTEGER,
                occurred_at TEXT,
                next_contact_at TEXT
            );
            CREATE TABLE operational_job_runs (
                job_key TEXT PRIMARY KEY,
                status TEXT
            );

            INSERT INTO patient_links VALUES
                (1, 'نام محرمانه نمونه', '09120000000', 1),
                (2, 'بیمار دوم', '09121111111', 1),
                (3, 'غیرفعال', NULL, 0);

            INSERT INTO followup_tasks VALUES
                (1, 'open', NULL, NULL, '2026-08-01'),
                (2, 'open', '', 'staff-1', '2026-08-10'),
                (3, 'done', '', NULL, '2026-07-01'),
                (4, 'open', 'clinical_v2', NULL, '2026-08-02'),
                (5, 'open', 'encounter_plan', NULL, '2026-08-02');

            INSERT INTO clinical_task_events VALUES
                (1, 'OPEN', NULL, NULL),
                (2, 'OPEN', 'nurse-1', NULL),
                (3, 'COMPLETED', 'nurse-1', 2);

            INSERT INTO care_plan_commitment_events VALUES
                (1, 'OPEN', 'staff-2', NULL),
                (2, 'OPEN', NULL, NULL),
                (3, 'CANCELLED', NULL, 2);

            INSERT INTO engagement_approvals VALUES
                (1, 'pending'),
                (2, 'failed'),
                (3, 'approved');
            INSERT INTO engagement_dispatch VALUES (1), (2);

            INSERT INTO sms_messages VALUES
                (1, 'sent', 'Delivered'),
                (2, 'pending', 'SubmissionUnknown'),
                (3, 'failed', 'Failed');

            INSERT INTO sms_campaigns VALUES
                (1, 'scheduled', '2026-08-02 10:00:00'),
                (2, 'scheduled', '2026-08-05 10:00:00');

            INSERT INTO appointments VALUES
                (1, 'scheduled'),
                (2, 'no_show'),
                (3, 'cancelled');

            INSERT INTO followup_contact_events VALUES
                (1, 1, '2026-08-01 09:00:00', '2026-08-02 09:00:00'),
                (2, 2, '2026-08-01 10:00:00', '2026-08-05 10:00:00');

            INSERT INTO operational_job_runs VALUES
                ('job:failed', 'FAILED'),
                ('job:running', 'RUNNING'),
                ('job:ok', 'COMPLETED');
            """
        )
        db.commit()
    finally:
        db.close()


def test_fo0_flags_exist_and_default_off_in_clean_environment():
    env = os.environ.copy()
    for name in EXPECTED_FLAGS:
        env.pop(name, None)
    code = """
import json
from src.config.settings import Config, FOLLOWUP_ORCHESTRATION_FLAGS
print(json.dumps({
    'names': list(FOLLOWUP_ORCHESTRATION_FLAGS),
    'values': {name: getattr(Config, name) for name in FOLLOWUP_ORCHESTRATION_FLAGS},
}, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SPECIALIST_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert tuple(payload["names"]) == EXPECTED_FLAGS
    assert payload["values"] == {name: False for name in EXPECTED_FLAGS}


def test_fo0_flags_have_no_runtime_consumer_yet():
    settings_path = SRC_ROOT / "config" / "settings.py"
    violations: list[str] = []
    for path in SRC_ROOT.rglob("*"):
        if not path.is_file() or path == settings_path:
            continue
        if path.suffix.lower() not in {".py", ".html", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        for flag in EXPECTED_FLAGS:
            if flag in text:
                violations.append(f"{path.relative_to(SPECIALIST_ROOT)}:{flag}")
    assert violations == []


def test_fo0_does_not_install_orchestration_schema():
    violations: list[str] = []
    for path in SRC_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".sql"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for table in FOUX_SCHEMA_NAMES:
            if table in text:
                violations.append(f"{path.relative_to(SPECIALIST_ROOT)}:{table}")
    assert violations == []


def test_project_state_registers_same_fo0_contract():
    state = json.loads((REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    stream = state["streams"]["followup_orchestration_ux_v1"]
    assert stream["program_code"] == "FOUX-V1"
    assert stream["canonical_plan"] == str(PLAN_PATH.relative_to(REPO_ROOT)).replace(
        "\\", "/"
    )
    assert stream["baseline_report"] == str(
        BASELINE_PATH.relative_to(REPO_ROOT)
    ).replace("\\", "/")
    assert stream["tracking_issue"] == 71
    assert stream["runtime_behavior_change"] is False
    assert stream["schema_change"] is False
    assert stream["database_mutation"] is False
    assert stream["fo1_allowed"] is False
    assert stream["live_operational_counts"] == "PENDING_OPERATOR_READ_ONLY_CAPTURE"
    assert stream["feature_flags"] == {name: False for name in EXPECTED_FLAGS}

    state_md = (REPO_ROOT / "PROJECT_STATE.md").read_text(encoding="utf-8")
    assert "Follow-up Orchestration & UX v1" in state_md
    assert str(PLAN_PATH.relative_to(REPO_ROOT)).replace("\\", "/") in state_md
    assert str(BASELINE_PATH.relative_to(REPO_ROOT)).replace("\\", "/") in state_md
    assert "FOUX-V1 FO-1 and later" in state_md
    assert "BLOCKED" in state_md


def test_canonical_docs_and_nearest_agent_guard_are_present():
    assert PLAN_PATH.is_file()
    assert BASELINE_PATH.is_file()
    agent_path = SPECIALIST_ROOT / "AGENTS.md"
    assert agent_path.is_file()

    plan = PLAN_PATH.read_text(encoding="utf-8")
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    agent = agent_path.read_text(encoding="utf-8")
    assert "FO-0 — Governance, Baseline & Registration" in plan
    assert "LIVE_OPERATIONAL_COUNTS = PENDING_DEPLOYMENT_CAPTURE" in baseline
    assert "FO-1 and later blocked" in agent
    for flag in EXPECTED_FLAGS:
        assert flag in baseline
        assert flag in agent


def test_read_only_baseline_capture_is_aggregate_and_non_mutating(tmp_path):
    database = tmp_path / "specialist.db"
    _create_baseline_fixture(database)
    before = _file_hash(database)

    module = _load_capture_module()
    captured = module.capture(
        database,
        captured_at=datetime(
            2026,
            8,
            3,
            1,
            44,
            tzinfo=timezone(timedelta(hours=3, minutes=30)),
        ),
    )

    assert _file_hash(database) == before
    assert captured["read_only"] is True
    assert captured["contains_phi"] is False
    assert captured["database_unchanged_after_capture"] is True
    assert captured["database"]["quick_check"] == "ok"

    metrics = captured["metrics"]
    assert metrics["active_patients"] == 2
    assert metrics["open_admin_tasks"] == 2
    assert metrics["unassigned_open_admin_tasks"] == 1
    assert metrics["overdue_open_admin_tasks"] == 1
    assert metrics["current_nonterminal_clinical_tasks"] == 1
    assert metrics["unassigned_current_clinical_tasks"] == 1
    assert metrics["current_nonterminal_plan_commitments"] == 1
    assert metrics["unassigned_current_plan_commitments"] == 0
    assert metrics["current_open_work_items_total"] == 4
    assert metrics["current_unassigned_work_items_total"] == 2
    assert captured["derived"]["unassigned_open_work_item_percent"] == 50.0
    assert metrics["pending_engagement_approvals"] == 1
    assert metrics["failed_or_unknown_engagement_approvals"] == 1
    assert metrics["engagement_dispatch_rows"] == 2
    assert metrics["sms_delivered"] == 1
    assert metrics["sms_inflight_or_unknown"] == 1
    assert metrics["sms_failed"] == 1
    assert metrics["due_scheduled_campaigns"] == 1
    assert metrics["scheduled_appointments"] == 1
    assert metrics["no_show_appointments"] == 1
    assert metrics["contact_events"] == 2
    assert metrics["callbacks_due_from_latest_contact"] == 1
    assert metrics["scheduler_failed_job_keys"] == 1
    assert metrics["scheduler_running_job_keys"] == 1

    rendered = json.dumps(captured, ensure_ascii=False)
    assert "نام محرمانه نمونه" not in rendered
    assert "09120000000" not in rendered


def test_capture_uses_sqlite_read_only_mode():
    source = CAPTURE_PATH.read_text(encoding="utf-8")
    assert "?mode=ro" in source
    assert "PRAGMA query_only=ON" in source
    assert "database_unchanged_after_capture" in source
    upper = source.upper()
    assert "INSERT INTO" not in upper
    assert "UPDATE " not in upper
    assert "DELETE FROM" not in upper
