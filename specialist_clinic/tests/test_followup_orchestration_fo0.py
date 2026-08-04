from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPECIALIST_ROOT.parent
SRC_ROOT = SPECIALIST_ROOT / "src"
PLAN_PATH = (
    SPECIALIST_ROOT / "docs" /
    "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md"
)
ROADMAP_PATH = (
    SPECIALIST_ROOT / "docs" /
    "FOLLOWUP_ORCHESTRATION_UX_V1_ROADMAP.md"
)
BASELINE_PATH = (
    SPECIALIST_ROOT / "docs" /
    "FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md"
)
CAPTURE_PATH = (
    SPECIALIST_ROOT / "scripts" /
    "capture_followup_fo0_baseline.py"
)

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
# FO-5 authorization does not authorize FO-7/FO-9 durable automation stores.
POST_FO5_SCHEMA_NAMES = (
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
                id INTEGER PRIMARY KEY, full_name TEXT, phone_number TEXT,
                is_active INTEGER NOT NULL
            );
            CREATE TABLE followup_tasks (
                id INTEGER PRIMARY KEY, status TEXT, source_engine TEXT,
                assigned_to TEXT, due_date TEXT
            );
            CREATE TABLE clinical_task_events (
                id INTEGER PRIMARY KEY, status TEXT, assigned_to TEXT,
                supersedes_event_id INTEGER
            );
            CREATE TABLE care_plan_commitment_events (
                id INTEGER PRIMARY KEY, status TEXT, assigned_to TEXT,
                supersedes_event_id INTEGER
            );
            CREATE TABLE engagement_approvals (
                id INTEGER PRIMARY KEY, status TEXT
            );
            CREATE TABLE engagement_dispatch (id INTEGER PRIMARY KEY);
            CREATE TABLE sms_messages (
                id INTEGER PRIMARY KEY, status TEXT, delivery_status TEXT
            );
            CREATE TABLE sms_campaigns (
                id INTEGER PRIMARY KEY, status TEXT, scheduled_at TEXT
            );
            CREATE TABLE appointments (
                id INTEGER PRIMARY KEY, status TEXT
            );
            CREATE TABLE followup_contact_events (
                id INTEGER PRIMARY KEY, task_id INTEGER, occurred_at TEXT,
                next_contact_at TEXT
            );
            CREATE TABLE operational_job_runs (
                job_key TEXT PRIMARY KEY, status TEXT
            );

            INSERT INTO patient_links VALUES
                (1,'نام محرمانه نمونه','09120000000',1),
                (2,'بیمار دوم','09121111111',1),
                (3,'غیرفعال',NULL,0);
            INSERT INTO followup_tasks VALUES
                (1,'open',NULL,NULL,'2026-08-01'),
                (2,'open','', 'staff-1','2026-08-10'),
                (3,'done','',NULL,'2026-07-01'),
                (4,'open','clinical_v2',NULL,'2026-08-02'),
                (5,'open','encounter_plan',NULL,'2026-08-02');
            INSERT INTO clinical_task_events VALUES
                (1,'OPEN',NULL,NULL),(2,'OPEN','nurse-1',NULL),
                (3,'COMPLETED','nurse-1',2);
            INSERT INTO care_plan_commitment_events VALUES
                (1,'OPEN','staff-2',NULL),(2,'OPEN',NULL,NULL),
                (3,'CANCELLED',NULL,2);
            INSERT INTO engagement_approvals VALUES
                (1,'pending'),(2,'failed'),(3,'approved');
            INSERT INTO engagement_dispatch VALUES (1),(2);
            INSERT INTO sms_messages VALUES
                (1,'sent','Delivered'),
                (2,'pending','SubmissionUnknown'),
                (3,'failed','Failed');
            INSERT INTO sms_campaigns VALUES
                (1,'scheduled','2026-08-02 10:00:00'),
                (2,'scheduled','2026-08-05 10:00:00');
            INSERT INTO appointments VALUES
                (1,'scheduled'),(2,'no_show'),(3,'cancelled');
            INSERT INTO followup_contact_events VALUES
                (1,1,'2026-08-01 09:00:00','2026-08-02 09:00:00'),
                (2,2,'2026-08-01 10:00:00','2026-08-05 10:00:00');
            INSERT INTO operational_job_runs VALUES
                ('job:failed','FAILED'),('job:running','RUNNING'),
                ('job:ok','COMPLETED');
            """
        )
        db.commit()
    finally:
        db.close()


def test_foux_flags_exist_and_default_off_in_clean_environment():
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


def test_fo6_and_later_schema_is_not_installed_by_fo5_authorization():
    schema_sources = [SRC_ROOT / "adapters" / "sqlite" / "schema.sql"]
    schema_sources.extend(
        path
        for path in (SRC_ROOT / "adapters" / "sqlite").glob("*.py")
        if path.is_file()
    )
    violations: list[str] = []
    for path in schema_sources:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for table in POST_FO5_SCHEMA_NAMES:
            declaration = re.compile(
                rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                rf"[\[\]`\"']*{re.escape(table)}\b",
                re.IGNORECASE,
            )
            if declaration.search(text):
                violations.append(
                    f"{path.relative_to(SPECIALIST_ROOT)}:{table}"
                )
    assert violations == []


def test_project_state_attests_fo4_acceptance_and_authorizes_bounded_fo5():
    state = json.loads(
        (REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8")
    )
    specialist = state["streams"]["specialist_clinic"]
    assert specialist["data_classification"] == (
        "TEST_ONLY_SYNTHETIC_OR_RESETTABLE"
    )
    assert specialist["real_patient_phi_expected"] is False

    stream = state["streams"]["followup_orchestration_ux_v1"]
    assert stream["program_code"] == "FOUX-V1"
    assert stream["plan_version"] == "1.7.0"
    assert stream["current_tranche"] == (
        "FO_5_LOCAL_OWNER_UX_ACCEPTANCE"
    )
    assert "FO_4_OWNER_ACCEPTED" in stream["status"]
    assert "FO_5_TECHNICALLY_VALIDATED_OWNER_UX_PENDING" in stream["status"]
    assert "FO_6_AND_LATER_BLOCKED" in stream["status"]

    fo3 = stream["fo3_evidence"]
    assert fo3["owner_acceptance"] is True
    assert fo3["critical_ux_defects"] == 0

    fo4 = stream["fo4_evidence"]
    assert fo4["tracking_issue"] == 94
    assert fo4["implementation_pr"] == 95
    assert fo4["runtime_ui_review_commit"] == (
        "cd243424ecbae98892e0dfde1780bb846554942f"
    )
    assert fo4["owner_acceptance_issue"] == 94
    assert fo4["local_ux_acceptance"] is True
    assert fo4["reviewer"] == "Emad211"
    assert fo4["reviewed_commit"] == (
        "cd243424ecbae98892e0dfde1780bb846554942f"
    )
    assert fo4["reviewed_on_test_data"] is True
    assert fo4["critical_ux_defects"] == 0
    assert fo4["status"] == "VALIDATED_WITH_OWNER_ACCEPTANCE"

    seeded = fo4["seeded_worklist_repair"]
    assert seeded["final_ci_run"] == 30851594179
    assert seeded["manual_test_followups_preserved"] is True
    assert seeded["duplicate_episode_link_event_count"] == 0
    sla = fo4["effective_sla_repair"]
    assert sla["final_ci_run"] == 30852909213
    assert sla["request_time_effective_filtering"] is True
    assert sla["read_time_write"] is False

    authorization = stream["fo5_authorization"]
    assert authorization["tracking_issue"] == 103
    assert authorization["governance_pr"] == 104
    assert authorization["scope"] == (
        "STRUCTURED_CONTACT_RETRY_ESCALATION_ONLY"
    )
    assert authorization["feature_flag"] == (
        "FOLLOWUP_STRUCTURED_CONTACT"
    )
    assert authorization["default_enabled"] is False
    assert authorization["status"] == "VALIDATED"
    assert stream["fo5_allowed"] is True
    assert stream["fo6_allowed"] is False
    assert stream["next_gate"] == "ISSUE_107_FO5_LOCAL_OWNER_UX_ACCEPTANCE_ON_94AA2C3E"
    assert stream["feature_flags"] == {
        name: False for name in EXPECTED_FLAGS
    }
    assert state["global_freeze"]["followup_orchestration_fo5"].startswith(
        "TECHNICALLY_VALIDATED_OWNER_UX_REVIEW_OR_FOCUSED_DEFECT_FIX_ONLY"
    )
    assert state["global_freeze"][
        "followup_orchestration_fo6_and_later"
    ].startswith("BLOCKED")


def test_canonical_docs_and_agent_guard_authorize_fo5_but_block_fo6():
    plan = PLAN_PATH.read_text(encoding="utf-8")
    roadmap = ROADMAP_PATH.read_text(encoding="utf-8")
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    agent = (SPECIALIST_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "نسخه:** `1.7.0`" in plan
    assert "FO_5_TECHNICALLY_VALIDATED_OWNER_UX_PENDING" in plan
    assert "FO_6_AND_LATER_BLOCKED" in plan
    assert "FO4_UX_ACCEPTED = true" in plan
    assert (
        "reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f"
        in plan
    )
    assert "Issue = #105 / PR #106" in plan
    assert "FOLLOWUP_STRUCTURED_CONTACT" in plan
    assert "SMS automation" in plan
    assert "FO-5 Local Owner UX Acceptance" in roadmap
    assert "TECHNICALLY_VALIDATED_OWNER_UX_PENDING" in roadmap
    assert "5.8 / 11 = 52.7%" in roadmap
    assert "FO-5 = TECHNICALLY VALIDATED / OWNER UX PENDING" in agent
    assert "FO-6 and later = BLOCKED" in agent
    assert "CURRENT ISSUE = #107" in agent
    assert "Status:** `VALIDATED`" in baseline


def test_read_only_baseline_capture_remains_non_mutating_and_phi_free(tmp_path):
    database = tmp_path / "specialist.db"
    _create_baseline_fixture(database)
    before = _file_hash(database)
    captured = _load_capture_module().capture(
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
