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
POST_FO4_SCHEMA_NAMES = (
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


def test_fo5_and_later_schema_is_not_installed_during_fo4_review_gate():
    schema_sources = [SRC_ROOT / "adapters" / "sqlite" / "schema.sql"]
    schema_sources.extend(
        path for path in (SRC_ROOT / "adapters" / "sqlite").glob("*.py") if path.is_file()
    )
    violations: list[str] = []
    for path in schema_sources:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for table in POST_FO4_SCHEMA_NAMES:
            declaration = re.compile(
                rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\[\]`\"']*{re.escape(table)}\b",
                re.IGNORECASE,
            )
            if declaration.search(text):
                violations.append(f"{path.relative_to(SPECIALIST_ROOT)}:{table}")
    assert violations == []


def test_project_state_attests_fo4_and_blocks_fo5_pending_owner_review():
    state = json.loads((REPO_ROOT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    specialist = state["streams"]["specialist_clinic"]
    assert specialist["data_classification"] == "TEST_ONLY_SYNTHETIC_OR_RESETTABLE"
    assert specialist["real_patient_phi_expected"] is False

    sms = state["streams"]["sms_consent_ux"]
    assert sms["tracking_issue"] == 92
    assert sms["implementation_pr"] == 93
    assert sms["merge_commit"] == "2f78d8b6087df9999ebf953ddbc6bce9e0789379"
    assert sms["final_ci_run"] == 30842741569
    assert sms["specialist_tests_passed"] == 765
    assert sms["accounting_tests_passed"] == 54
    assert sms["consent_defaults_changed"] is False
    assert sms["send_policy_changed"] is False
    assert sms["append_only_history_preserved"] is True
    assert sms["stale_guard_preserved"] is True
    assert sms["status"] == "COMPLETED"

    stream = state["streams"]["followup_orchestration_ux_v1"]
    assert stream["program_code"] == "FOUX-V1"
    assert stream["plan_version"] == "1.5.2"
    assert stream["current_tranche"] == "FO_4_LOCAL_OWNER_UX_ACCEPTANCE"
    assert stream["status"] == (
        "FO_0_VALIDATED_FO_1_VALIDATED_FO_2_VALIDATED_"
        "FO_3_OWNER_ACCEPTED_FO_4_TECHNICALLY_VALIDATED_"
        "LOCAL_UX_PENDING_FO_5_AND_LATER_BLOCKED"
    )

    fo3 = stream["fo3_evidence"]
    assert fo3["owner_acceptance_issue"] == 83
    assert fo3["owner_acceptance"] is True
    assert fo3["reviewer"] == "Emad211"
    assert fo3["reviewed_commit"] == (
        "020803868e1c2755f7669d52da92cb8050a46018"
    )
    assert fo3["reviewed_on_test_data"] is True
    assert fo3["critical_ux_defects"] == 0
    assert fo3["status"] == "VALIDATED_WITH_OWNER_ACCEPTANCE"

    authorization = stream["fo4_authorization"]
    assert authorization["tracking_issue"] == 90
    assert authorization["governance_pr"] == 91
    assert authorization["scope"] == "CLAIM_ASSIGNMENT_ROUTING_SLA_ONLY"
    assert authorization["status"] == "VALIDATED"

    fo4 = stream["fo4_evidence"]
    assert fo4["tracking_issue"] == 94
    assert fo4["implementation_pr"] == 95
    assert fo4["final_head"] == "ec98140fc262f26089e5a05b3e24a2b9647882ff"
    assert fo4["merge_commit"] == "27ccb992f2cb43c78bfe98549c3f0414b88fd1d8"
    assert fo4["final_ci_run"] == 30844075841
    assert fo4["specialist_tests_passed"] == 773
    assert fo4["accounting_tests_passed"] == 54
    assert fo4["append_only_ownership_events"] is True
    assert fo4["atomic_claim_one_winner"] is True
    assert fo4["exact_replay_idempotent"] is True
    assert fo4["stale_form_fails_closed"] is True
    assert fo4["role_permission_compatibility"] is True
    assert fo4["manager_assign_reassign_audited"] is True
    assert fo4["non_owner_release_rejected"] is True
    assert fo4["terminal_actions_rejected_early"] is True
    assert fo4["projection_rebuild_preserves_ownership"] is True
    assert fo4["effective_role_filtering"] is True
    assert fo4["bounded_batch_ownership_overlay"] is True
    assert fo4["feature_off_post_routes_404"] is True
    assert fo4["source_truth_digest_unchanged"] is True
    assert fo4["local_ux_acceptance"] == "PENDING"
    assert fo4["status"] == "TECHNICALLY_VALIDATED"
    assert fo4["runtime_ui_review_commit"] == (
        "cd243424ecbae98892e0dfde1780bb846554942f"
    )
    seeded = fo4["seeded_worklist_repair"]
    assert seeded["tracking_issue"] == 97
    assert seeded["implementation_pr"] == 98
    assert seeded["final_ci_run"] == 30851594179
    assert seeded["specialist_tests_passed"] == 781
    assert seeded["accounting_tests_passed"] == 54
    assert seeded["request_time_rebuild"] is False
    assert seeded["manual_test_followups_preserved"] is True
    assert seeded["duplicate_episode_link_event_count"] == 0
    assert seeded["status"] == "COMPLETED"

    sla = fo4["effective_sla_repair"]
    assert sla["tracking_issue"] == 99
    assert sla["implementation_pr"] == 100
    assert sla["final_ci_run"] == 30852909213
    assert sla["specialist_tests_passed"] == 784
    assert sla["accounting_tests_passed"] == 54
    assert sla["canonical_states"] == [
        "FUTURE", "DUE_TODAY", "OVERDUE", "DUE_UNKNOWN",
        "WAITING", "BLOCKED", "TERMINAL",
    ]
    assert sla["request_time_effective_filtering"] is True
    assert sla["read_time_write"] is False
    assert sla["status"] == "COMPLETED"

    assert stream["fo3_allowed"] is True
    assert stream["fo4_allowed"] is True
    assert stream["fo5_allowed"] is False
    assert stream["next_gate"] == (
        "ISSUE_94_FO4_LOCAL_OWNER_UX_ACCEPTANCE_ON_CD243424"
    )
    assert stream["feature_flags"] == {name: False for name in EXPECTED_FLAGS}
    assert state["global_freeze"]["followup_orchestration_fo4"].startswith(
        "ALLOWED_LOCAL_OWNER_UX_REVIEW"
    )
    assert state["global_freeze"]["followup_orchestration_fo5_and_later"].startswith(
        "BLOCKED"
    )


def test_canonical_docs_and_agent_guard_require_fo4_owner_review():
    plan = PLAN_PATH.read_text(encoding="utf-8")
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    agent = (SPECIALIST_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "نسخه:** `1.5.2`" in plan
    assert "FO_4_TECHNICALLY_VALIDATED_LOCAL_UX_ACCEPTANCE_PENDING" in plan
    assert "FO_5_AND_LATER_BLOCKED" in plan
    assert "Implementation Issue #94 / PR #95" in plan
    assert "Final CI 30844075841" in plan
    assert "773 Specialist + 54 Accounting" in plan
    assert "Issue #97 / PR #98" in plan
    assert "CI 30851594179" in plan
    assert "781 Specialist + 54 Accounting" in plan
    assert "Issue #99 / PR #100" in plan
    assert "CI 30852909213" in plan
    assert "784 Specialist + 54 Accounting" in plan
    assert "PROJECTION_EMPTY_WITH_SOURCE_DATA" in plan
    assert "DUE_UNKNOWN" in plan
    assert "reviewed_commit = cd243424ecbae98892e0dfde1780bb846554942f" in plan
    assert "FO4_UX_ACCEPTED = true|false" in plan
    assert "FO-5 AND LATER = BLOCKED" in plan
    assert "Status:** `VALIDATED`" in baseline

    assert "FO-4 = TECHNICALLY VALIDATED" in agent
    assert "FO-4 LOCAL UX ACCEPTANCE = PENDING" in agent
    assert "FO-5 and later = BLOCKED" in agent
    assert "CURRENT ISSUE = #94" in agent
    assert "Final CI 30844075841" in agent
    assert "773 Specialist + 54 Accounting" in agent
    assert "Issue #97 / PR #98" in agent
    assert "781 Specialist + 54 Accounting" in agent
    assert "Issue #99 / PR #100" in agent
    assert "784 Specialist + 54 Accounting" in agent
    assert "prepare_seeded_followup_view.py" in agent
    assert "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS" in agent
    assert "FOLLOWUP_AUTO_ROUTING" in agent
    assert "cd243424ecbae98892e0dfde1780bb846554942f" in agent


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
