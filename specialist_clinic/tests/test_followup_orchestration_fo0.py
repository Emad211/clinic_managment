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
PLAN_PATH = SPECIALIST_ROOT / "docs" / "FOLLOWUP_ORCHESTRATION_UX_V1_IMPLEMENTATION_PLAN.md"
BASELINE_PATH = SPECIALIST_ROOT / "docs" / "FOLLOWUP_ORCHESTRATION_UX_V1_BASELINE.md"
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
POST_FO3_SCHEMA_NAMES = (
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
            CREATE TABLE engagement_approvals (id INTEGER PRIMARY KEY, status TEXT);
            CREATE TABLE engagement_dispatch (id INTEGER PRIMARY KEY);
            CREATE TABLE sms_messages (
                id INTEGER PRIMARY KEY, status TEXT, delivery_status TEXT
            );
            CREATE TABLE sms_campaigns (
                id INTEGER PRIMARY KEY, status TEXT, scheduled_at TEXT
            );
            CREATE TABLE appointments (id INTEGER PRIMARY KEY, status TEXT);
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
                (1,'sent','Delivered'),(2,'pending','SubmissionUnknown'),
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


def test_fo4_and_later_schema_is_not_installed_before_post_fix_ux_acceptance():
    schema_sources = [SRC_ROOT / "adapters" / "sqlite" / "schema.sql"]
    schema_sources.extend(
        path for path in (SRC_ROOT / "adapters" / "sqlite").glob("*.py") if path.is_file()
    )
    violations: list[str] = []
    for path in schema_sources:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for table in POST_FO3_SCHEMA_NAMES:
            declaration = re.compile(
                rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\[\]`\"']*{re.escape(table)}\b",
                re.IGNORECASE,
            )
            if declaration.search(text):
                violations.append(f"{path.relative_to(SPECIALIST_ROOT)}:{table}")
    assert violations == []


def test_project_state_attests_repair_and_blocks_fo4_pending_owner_review():
    state = json.loads((REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    specialist = state["streams"]["specialist_clinic"]
    assert specialist["data_classification"] == "TEST_ONLY_SYNTHETIC_OR_RESETTABLE"
    assert specialist["real_patient_phi_expected"] is False

    stream = state["streams"]["followup_orchestration_ux_v1"]
    assert stream["program_code"] == "FOUX-V1"
    assert stream["plan_version"] == "1.4.3"
    assert stream["current_tranche"] == "FO_3_POST_FIX_LOCAL_UX_ACCEPTANCE"
    assert stream["status"] == (
        "FO_0_VALIDATED_FO_1_VALIDATED_FO_2_VALIDATED_"
        "FO_3_RUNTIME_REPAIR_TECHNICALLY_VALIDATED_"
        "POST_FIX_LOCAL_UX_ACCEPTANCE_PENDING"
    )
    assert stream["fo3_evidence"]["implementation_pr"] == 81
    assert stream["fo3_evidence"]["local_ux_acceptance"] == "PENDING_POST_FIX_REVIEW"

    incident = stream["fo3_runtime_incident"]
    assert incident["incident_code"] == "FO3_UI_500"
    assert incident["tracking_issue"] == 84
    assert incident["implementation_pr"] == 85
    assert incident["root_cause_confirmed"] is True
    assert incident["root_cause_ci_run"] == 30808217800
    assert incident["root_cause_code"] == "JINJA_DICT_METHOD_COLLISION_ON_ITEMS_KEY"
    assert incident["focused_fix_final_head"] == (
        "8809252b2ca25fb55f200d783016d30ec10134d7"
    )
    assert incident["focused_fix_merge_commit"] == (
        "8f851c90da5a81f4b7ffce43eaa5bf6010d58fa2"
    )
    assert incident["focused_fix_final_ci_run"] == 30809363219
    assert incident["focused_fix_specialist_tests_passed"] == 761
    assert incident["focused_fix_accounting_tests_passed"] == 54
    assert incident["real_list_render_passed"] is True
    assert incident["real_timeline_render_passed"] is True
    assert incident["legacy_cache_repair_passed"] is True
    assert incident["source_truth_digest_unchanged"] is True
    assert incident["episode_digest_unchanged"] is True
    assert incident["status"] == "RESOLVED_TECHNICALLY"

    assert stream["implemented_contracts"]["projection_storage_schema_version"] == "1.1"
    assert stream["fo3_allowed"] is True
    assert stream["fo4_allowed"] is False
    assert stream["next_gate"] == "ISSUE_83_POST_FIX_LOCAL_UX_ACCEPTANCE_ON_8F851C90"
    assert stream["feature_flags"] == {name: False for name in EXPECTED_FLAGS}
    assert state["global_freeze"]["followup_orchestration_fo3"].startswith(
        "ALLOWED_POST_FIX_LOCAL_UX_REVIEW"
    )
    assert state["global_freeze"]["followup_orchestration_fo4_and_later"].startswith(
        "BLOCKED"
    )


def test_canonical_docs_and_agent_guard_are_current():
    plan = PLAN_PATH.read_text(encoding="utf-8")
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    agent = (SPECIALIST_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "نسخه:** `1.4.3`" in plan
    assert "FO_3_RUNTIME_REPAIR_TECHNICALLY_VALIDATED" in plan
    assert "FO_3_POST_FIX_LOCAL_UX_ACCEPTANCE_PENDING" in plan
    assert "Final CI 30809363219" in plan
    assert "761 Specialist + 54 Accounting" in plan
    assert "FO-4 AND LATER = BLOCKED" in plan
    assert "Status:** `VALIDATED`" in baseline

    assert "FO-3 RUNTIME REPAIR = TECHNICALLY VALIDATED" in agent
    assert "FO-3 POST-FIX LOCAL UX ACCEPTANCE = PENDING" in agent
    assert "CURRENT REVIEW ISSUE = #83" in agent
    assert "model['items']" in agent
    assert "timeline['items']" in agent
    assert "FO-4 and later = BLOCKED" in agent


def test_read_only_baseline_capture_remains_non_mutating_and_phi_free(tmp_path):
    database = tmp_path / "specialist.db"
    _create_baseline_fixture(database)
    before = _file_hash(database)
    captured = _load_capture_module().capture(
        database,
        captured_at=datetime(
            2026, 8, 3, 1, 44,
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
