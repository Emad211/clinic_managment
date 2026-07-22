"""Clinical v2 follow-up projection, period identity and fail-loud contracts."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
TESTS_ROOT = str(SPECIALIST_ROOT / "tests")
if TESTS_ROOT not in sys.path:
    sys.path.insert(0, TESTS_ROOT)

from clinical_engine_current_test_support import (
    current_snapshot,
    install_sealed_rollout,
)
from test_clinical_engine_v2_compiler import valid_rule
from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.clinical_engine_audit_repo import (
    ClinicalEngineAuditRepository,
)
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
)
from src.domain.clinical_engine import (
    PredicateState,
    RuleOutcome,
    RunStatus,
)
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.fact_builder import ENGINE_VERSION


@pytest.fixture()
def followup_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "followups.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "followup-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id="TEST0001") -> int:
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by, enrolled_at, updated_at)
               VALUES (?, 'Follow-up Patient', 'pytest',
                       '2026-07-22 09:00:00', '2026-07-22 09:00:00')""",
            (national_id,),
        ).lastrowid
    )
    db.commit()
    install_sealed_rollout()
    return patient_id


def _rule(action="create_followup", semantic_key="followup:a1c"):
    raw = deepcopy(valid_rule())
    raw["rule_code"] = f"TEST-{action.upper()}"
    raw["action_type"] = action
    raw["semantic_key"] = semantic_key
    raw["recommendation"].update(
        {
            "text_fa": "پیگیری بالینی سررسیده است.",
            "requires_clinician_confirmation": False,
            "may_create_internal_task": True,
        }
    )
    return raw


def _ruleset_id() -> int:
    return int(
        ClinicalEngineActivationRepository().get_json("seal")[
            "ruleset_id"
        ]
    )


def _run(
    patient_id: int,
    *,
    outcome="FIRED",
    action="create_followup",
    semantic_key="followup:a1c",
    fact_ids=("lab:31",),
    suppression=None,
    error=None,
    recommendation_overrides=None,
    as_of="2026-07-22 10:00:00",
    run_status=None,
):
    compiled = RuleCompiler().compile(_rule(action, semantic_key))
    rule_id = ClinicalEngineRulesRepository().create_rule_version(
        compiled,
        created_by="pytest",
    )
    snapshot = current_snapshot(patient_id)
    snapshot["facts"] = [
        {"fact_id": value} for value in fact_ids
    ]
    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at=as_of,
        engine_version=ENGINE_VERSION,
        ruleset_id=_ruleset_id(),
        fact_snapshot=snapshot,
    )
    recommendation = None
    if outcome == "FIRED":
        recommendation = {
            "recommendation_key": (
                f"rec:{compiled.definition.rule_code}:2.0.0"
            ),
            "action_type": action,
            "text_fa": "پیگیری بالینی سررسیده است.",
            "title_fa": compiled.definition.title,
            "semantic_key": semantic_key,
            "suggestion_only": True,
            "requires_clinician_confirmation": False,
            "presentation": "NON_INTERRUPTIVE",
            "may_create_internal_task": True,
            "params": {},
        }
        recommendation.update(recommendation_overrides or {})
    predicate = (
        PredicateState.TRUE
        if outcome == "FIRED"
        else PredicateState.UNKNOWN
        if outcome == "NEEDS_DATA"
        else PredicateState.ERROR
        if outcome == "ERROR"
        else PredicateState.FALSE
    )
    evaluation_id = audit.append_evaluation(
        run_id=run_id,
        rule_version_id=rule_id,
        predicate_state=predicate,
        outcome=RuleOutcome(outcome),
        trace={
            "node_id": "due",
            "fact_ids": list(fact_ids),
            "children": [],
        },
        data_issues=(
            [{"code": "NOT_ASKED"}]
            if outcome == "NEEDS_DATA"
            else None
        ),
        recommendation=recommendation,
        suppression=suppression,
        error=error,
    )
    if recommendation:
        audit.append_recommendation_event(
            run_id=run_id,
            evaluation_id=evaluation_id,
            recommendation_key=recommendation[
                "recommendation_key"
            ],
            action_type=action,
            event_type="CREATED",
            payload=recommendation,
        )
    audit.complete_run(
        run_id,
        status=(
            run_status
            or (
                RunStatus.COMPLETED_WITH_ERRORS
                if outcome == "ERROR"
                else RunStatus.COMPLETED
            )
        ),
    )
    return run_id


def test_suppressed_and_needs_data_rules_create_no_task(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    _run(
        patient_id,
        outcome="SUPPRESSED",
        suppression={
            "reason_code": "RECENTLY_COMPLETED",
            "message_fa": "فعلاً سررسید نیست",
        },
    )
    assert ClinicalV2FollowupService().generate_patient(patient_id) == {
        "enabled": True,
        "created": 0,
        "task_ids": [],
        "issues": [],
    }

    _run(
        patient_id,
        outcome="NEEDS_DATA",
        action="vaccine",
        semantic_key="vaccine:influenza",
        fact_ids=("flag:1:vaccine-history",),
        as_of="2026-07-23 10:00:00",
    )
    result = ClinicalV2FollowupService().generate_patient(patient_id)
    assert result["created"] == 0
    assert result["issues"][0]["code"] == "RULE_NEEDS_DATA"
    assert db.execute(
        "SELECT COUNT(*) AS count FROM followup_tasks"
    ).fetchone()["count"] == 0


def test_fired_rule_creates_one_auditable_idempotent_task(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    run_id = _run(patient_id)
    service = ClinicalV2FollowupService()

    first = service.generate_patient(patient_id)
    second = service.generate_patient(patient_id)

    row = dict(db.execute("SELECT * FROM followup_tasks").fetchone())
    assert first["created"] == 1
    assert second["created"] == 0
    assert row["reason"] == "monitoring"
    assert row["source_engine"] == "clinical_v2"
    assert row["source_run_id"] == run_id
    assert row["source_recommendation_event_id"] is not None
    assert row["clinical_semantic_key"] == "followup:a1c"
    assert len(row["clinical_task_key"]) == 64


def test_open_semantic_task_blocks_duplicate_from_new_evidence(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    service = ClinicalV2FollowupService()
    _run(
        patient_id,
        fact_ids=("lab:31",),
        as_of="2026-07-22 10:00:00",
    )
    assert service.generate_patient(patient_id)["created"] == 1
    _run(
        patient_id,
        fact_ids=("lab:32",),
        as_of="2026-07-23 10:00:00",
    )

    assert service.generate_patient(patient_id)["created"] == 0
    assert db.execute(
        "SELECT COUNT(*) AS count FROM followup_tasks"
    ).fetchone()["count"] == 1


def test_closed_task_can_recur_in_a_new_due_period(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    service = ClinicalV2FollowupService()
    _run(
        patient_id,
        fact_ids=("lab:31",),
        recommendation_overrides={
            "params": {"due_period": "2026-H1"}
        },
    )
    assert service.generate_patient(patient_id)["created"] == 1
    db.execute(
        """UPDATE followup_tasks
           SET status='done', resolved_at='2026-07-22 12:00:00'"""
    )
    db.commit()
    _run(
        patient_id,
        fact_ids=("lab:32",),
        as_of="2026-07-23 10:00:00",
        recommendation_overrides={
            "params": {"due_period": "2026-H2"}
        },
    )

    assert service.generate_patient(patient_id)["created"] == 1
    rows = db.execute(
        "SELECT clinical_task_key FROM followup_tasks ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["clinical_task_key"] != rows[1][
        "clinical_task_key"
    ]


def test_safety_failed_run_cannot_create_internal_task(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    _run(patient_id, run_status=RunStatus.SAFETY_FAILED)

    result = ClinicalV2FollowupService().generate_patient(patient_id)
    assert result["created"] == 0
    assert result["issues"] == [
        {"code": "SAFETY_NOT_CLEARED", "rule_code": None}
    ]


def test_concurrent_generation_still_creates_exactly_one_task(followup_app):
    from concurrent.futures import ThreadPoolExecutor

    from src.adapters.sqlite.clinical_followup_repo import (
        ClinicalFollowupRepository,
    )
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    _run(patient_id)
    task = ClinicalV2FollowupService().project_patient(patient_id)[
        "tasks"
    ][0]

    def create_once():
        with followup_app.app_context():
            return ClinicalFollowupRepository().create_clinical_task_once(
                task
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create_once(), range(2)))

    assert sum(int(created) for _, created in results) == 1
    assert db.execute(
        "SELECT COUNT(*) AS count FROM followup_tasks "
        "WHERE source_engine='clinical_v2'"
    ).fetchone()["count"] == 1


def test_persistence_failure_is_never_silently_swallowed(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    class BrokenRepository:
        def create_clinical_task_once(self, _task):
            raise RuntimeError("disk full")

    db = get_db()
    patient_id = _patient(db)
    _run(patient_id)
    service = ClinicalV2FollowupService(repo=BrokenRepository())
    with pytest.raises(RuntimeError, match="disk full"):
        service.generate_patient(patient_id)


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"may_create_internal_task": False}, "TASK_POLICY_REJECTED"),
        (
            {"requires_clinician_confirmation": True},
            "TASK_POLICY_REJECTED",
        ),
        ({"semantic_key": ""}, "TASK_IDENTITY_MISSING"),
    ],
)
def test_invalid_task_policy_fails_loud_without_mutation(
    followup_app,
    overrides,
    code,
):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    _run(patient_id, recommendation_overrides=overrides)

    result = ClinicalV2FollowupService().generate_patient(patient_id)
    assert result["created"] == 0
    assert result["issues"][0]["code"] == code
    assert db.execute(
        "SELECT COUNT(*) AS count FROM followup_tasks"
    ).fetchone()["count"] == 0


def test_task_without_traceable_evidence_fails_loud(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    _run(patient_id, fact_ids=())

    result = ClinicalV2FollowupService().generate_patient(patient_id)
    assert result["created"] == 0
    assert result["issues"][0]["code"] == "TASK_EVIDENCE_MISSING"


def test_clinical_task_does_not_collapse_administrative_refill(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.followups_repo import FollowupRepository
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    FollowupRepository().create(
        patient_id,
        reason="refill",
        detail="تمدید نسخه",
    )
    _run(patient_id)

    assert ClinicalV2FollowupService().generate_patient(patient_id)[
        "created"
    ] == 1
    rows = db.execute(
        "SELECT reason, source_engine FROM followup_tasks ORDER BY id"
    ).fetchall()
    assert [
        (row["reason"], row["source_engine"]) for row in rows
    ] == [("refill", None), ("monitoring", "clinical_v2")]


def test_revoked_seal_blocks_task_write_after_projection(followup_app):
    from src.adapters.sqlite.clinical_followup_repo import (
        ClinicalFollowupRepository,
    )
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    _run(patient_id)
    task = ClinicalV2FollowupService().project_patient(patient_id)[
        "tasks"
    ][0]
    ClinicalEngineActivationRepository().delete("seal")

    with pytest.raises(
        RuntimeError,
        match="STALE_CLINICAL_TASK_SOURCE",
    ):
        ClinicalFollowupRepository().create_clinical_task_once(task)
    assert db.execute(
        "SELECT COUNT(*) AS count FROM followup_tasks"
    ).fetchone()["count"] == 0


def test_patient_generate_route_surfaces_v2_issue_without_task(followup_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    _run(
        patient_id,
        outcome="NEEDS_DATA",
        action="vaccine",
        semantic_key="vaccine:influenza",
    )
    client = followup_app.test_client()
    assert client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    ).status_code in {302, 303}

    response = client.post(
        f"/patients/{patient_id}/followups/generate",
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    with client.session_transaction() as session:
        messages = [
            message for _, message in session.get("_flashes", [])
        ]
    assert any("دادهٔ ناکافی" in message for message in messages)
    assert db.execute(
        "SELECT COUNT(*) AS count FROM followup_tasks "
        "WHERE source_engine='clinical_v2'"
    ).fetchone()["count"] == 0


def test_worklist_visibly_distinguishes_v2_clinical_task(followup_app):
    from src.adapters.sqlite.core import get_db
    from src.services.followup_engine import ClinicalV2FollowupService

    db = get_db()
    patient_id = _patient(db)
    _run(patient_id)
    assert ClinicalV2FollowupService().generate_patient(patient_id)[
        "created"
    ] == 1
    client = followup_app.test_client()
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    )

    response = client.get("/followups/")
    assert response.status_code == 200
    assert "بالینی v2" in response.get_data(as_text=True)


def test_existing_database_gets_clinical_task_columns_and_indexes(tmp_path):
    import sqlite3

    from src.adapters.sqlite import core
    from src.app import create_app

    db_path = tmp_path / "existing.db"
    core._initialized = False
    bootstrap = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(db_path),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "bootstrap-test",
        }
    )
    with bootstrap.app_context():
        from src.adapters.sqlite.core import get_db

        get_db()
    core._initialized = False

    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        PRAGMA foreign_keys=OFF;
        ALTER TABLE followup_tasks RENAME TO followup_tasks_old;
        CREATE TABLE followup_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            due_date TEXT,
            reason TEXT,
            detail TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            assigned_to TEXT,
            call_log TEXT,
            source_rule TEXT,
            source_event TEXT,
            appointment_id INTEGER,
            fulfillment TEXT DEFAULT 'in_person',
            created_at TIMESTAMP,
            resolved_at TIMESTAMP
        );
        DROP TABLE followup_tasks_old;
        PRAGMA foreign_keys=ON;
        """
    )
    raw.commit()
    raw.close()
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(db_path),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "migration-test",
        }
    )
    with app.app_context():
        from src.adapters.sqlite.core import get_db

        db = get_db()
        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(followup_tasks)"
            )
        }
        indexes = {
            row["name"]
            for row in db.execute(
                "PRAGMA index_list(followup_tasks)"
            )
        }
    core._initialized = False

    assert {
        "clinical_task_key",
        "clinical_semantic_key",
        "source_engine",
        "source_run_id",
        "source_recommendation_event_id",
    } <= columns
    assert {
        "idx_followup_clinical_task_key",
        "idx_followup_open_clinical_semantic",
    } <= indexes
