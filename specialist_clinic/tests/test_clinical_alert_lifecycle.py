from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = str(ROOT / "tests")
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from src.adapters.sqlite.clinical_alert_repo import (
    ClinicalAlertConflict,
    ClinicalAlertRepository,
    ClinicalAlertValidationError,
)
from src.adapters.sqlite.clinical_alert_schema import ensure_clinical_alert_storage
from src.adapters.sqlite.clinical_engine_audit_repo import ClinicalEngineAuditRepository
from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository
from src.adapters.sqlite.clinical_followup_repo import ClinicalFollowupRepository
from src.domain.clinical_engine import (
    ClinicalDecision,
    PredicateState,
    RecommendationEventType,
    RuleOutcome,
    RunStatus,
)
from src.services.clinical_alert_service import ClinicalAlertService
from src.services.clinical_engine.compiler import RuleCompiler
from test_clinical_engine_v2_compiler import valid_rule


@pytest.fixture()
def alert_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "alerts.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "alert-test",
        }
    )
    ctx = app.app_context()
    ctx.push()
    ensure_clinical_alert_storage(core.get_db())
    yield app
    ctx.pop()
    core._initialized = False


def _patient(db, suffix: str) -> int:
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, enrolled_by)
               VALUES (?, ?, '09120000000', 'pytest')""",
            (f"ALERT{suffix}", f"Alert Patient {suffix}"),
        ).lastrowid
    )
    db.commit()
    return patient_id


def _source(alert_app, suffix: str = "001", severity: str = "CRITICAL") -> dict:
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, suffix)
    raw = deepcopy(valid_rule())
    raw.update(
        {
            "rule_code": f"TEST-REDFLAG-{suffix}",
            "title": "هشدار فوری آزمون",
            "phase": "PREFLIGHT",
            "action_type": "redflag",
            "severity": severity,
            "semantic_key": f"test:redflag:{suffix}",
        }
    )
    raw["recommendation"].update(
        {
            "text_fa": "نیازمند مشاهده و تصمیم فوری پزشک است.",
            "requires_clinician_confirmation": False,
            "may_create_internal_task": False,
            "params": {"do_not_auto_message": True, "do_not_auto_refer": True},
        }
    )
    compiled = RuleCompiler().compile(raw)
    rule_id = ClinicalEngineRulesRepository().create_rule_version(
        compiled,
        created_by="pytest",
    )
    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at="2026-07-26 10:00:00",
        engine_version="a3-test",
        fact_snapshot={"facts": []},
        created_by="pytest",
    )
    recommendation = {
        "recommendation_key": f"rec:{raw['rule_code']}:1",
        "action_type": "redflag",
        "text_fa": raw["recommendation"]["text_fa"],
        "title_fa": raw["title"],
        "suggestion_only": True,
        "requires_clinician_confirmation": False,
        "presentation": "INTERRUPTIVE",
        "may_create_internal_task": False,
        "params": raw["recommendation"]["params"],
    }
    evaluation_id = audit.append_evaluation(
        run_id=run_id,
        rule_version_id=rule_id,
        predicate_state=PredicateState.TRUE,
        outcome=RuleOutcome.FIRED,
        trace={"node_id": "redflag", "fact_ids": ["observation:1"]},
        recommendation=recommendation,
    )
    event_id = audit.append_recommendation_event(
        run_id=run_id,
        evaluation_id=evaluation_id,
        recommendation_key=recommendation["recommendation_key"],
        action_type="redflag",
        event_type=RecommendationEventType.CREATED,
        payload=recommendation,
    )
    audit.complete_run(run_id, status=RunStatus.COMPLETED, summary={"fired": 1})
    return {
        "patient_id": patient_id,
        "run_id": run_id,
        "event_id": event_id,
        "rule_code": raw["rule_code"],
        "recommendation": recommendation,
    }


def _create_alert(source: dict, *, severity="CRITICAL", suffix="") -> int:
    alert_id, created = ClinicalAlertRepository().create_once(
        patient_link_id=source["patient_id"],
        source_run_id=source["run_id"],
        source_recommendation_event_id=source["event_id"],
        rule_code=source["rule_code"],
        action_type="redflag",
        severity=severity,
        title_fa="هشدار فوری آزمون" + suffix,
        message_fa="نیازمند مشاهده و تصمیم فوری پزشک است.",
        created_by="pytest",
        created_at="2026-07-26 10:00:00",
    )
    assert created is True
    return alert_id


def test_alert_creation_is_idempotent_and_has_no_external_side_effect(alert_app):
    from src.adapters.sqlite.core import get_db

    source = _source(alert_app)
    repo = ClinicalAlertRepository()
    alert_id = _create_alert(source)
    same_id, created = repo.create_once(
        patient_link_id=source["patient_id"],
        source_run_id=source["run_id"],
        source_recommendation_event_id=source["event_id"],
        rule_code=source["rule_code"],
        action_type="redflag",
        severity="CRITICAL",
        title_fa="هر متن تکراری نباید root جدید بسازد",
        message_fa="تکرار",
        created_by="pytest",
        created_at="2026-07-26 10:01:00",
    )
    assert same_id == alert_id
    assert created is False
    current = repo.current(alert_id)
    assert current["current_status"] == "OPEN"
    assert current["acknowledgement_due_at"] == "2026-07-26 10:15:00"

    db = get_db()
    assert db.execute("SELECT COUNT(*) FROM clinical_alerts").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM clinical_alert_events").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM sms_messages").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM followup_tasks").fetchone()[0] == 0


def test_open_alert_escalates_but_acknowledged_alert_does_not(alert_app):
    first = _source(alert_app, "002")
    first_id = _create_alert(first)
    second = _source(alert_app, "003")
    second_id = _create_alert(second)
    repo = ClinicalAlertRepository()

    second_head = repo.current(second_id)["current_event_id"]
    repo.append_event(
        second_id,
        event_type="ACKNOWLEDGED",
        expected_current_event_id=second_head,
        actor_username="nurse",
        assigned_to="nurse",
        recorded_at="2026-07-26 10:05:00",
    )
    escalated = repo.escalate_due(now="2026-07-26 10:16:00")
    assert escalated == [first_id]
    assert repo.current(first_id)["current_status"] == "ESCALATED"
    assert repo.current(second_id)["current_status"] == "ACKNOWLEDGED"


def test_resolution_requires_latest_same_recommendation_decision(alert_app):
    source = _source(alert_app, "004")
    alert_id = _create_alert(source)
    repo = ClinicalAlertRepository()
    acknowledged = repo.append_event(
        alert_id,
        event_type="ACKNOWLEDGED",
        expected_current_event_id=repo.current(alert_id)["current_event_id"],
        actor_username="nurse",
        assigned_to="nurse",
        recorded_at="2026-07-26 10:05:00",
    )
    audit = ClinicalEngineAuditRepository()
    decision_id = audit.append_decision(
        recommendation_event_id=source["event_id"],
        patient_link_id=source["patient_id"],
        decision=ClinicalDecision.ACCEPTED,
        actor_username="doctor",
        reason_text="بیمار ارزیابی و برنامه اقدام ثبت شد.",
    )
    service = ClinicalAlertService(repository=repo)
    resolved = service.resolve(
        alert_id,
        expected_current_event_id=int(acknowledged["id"]),
        decision_event_id=decision_id,
        actor_username="doctor",
        actor_user_id=None,
        note="تصمیم پزشک و مسیر اقدام در پرونده ثبت شد.",
    )
    assert resolved["status"] == "RESOLVED"

    with pytest.raises(ClinicalAlertValidationError, match="terminal"):
        repo.append_event(
            alert_id,
            event_type="ACKNOWLEDGED",
            expected_current_event_id=int(resolved["id"]),
            actor_username="nurse",
        )


def test_foreign_or_stale_decision_cannot_resolve_alert(alert_app):
    first = _source(alert_app, "005")
    alert_id = _create_alert(first)
    repo = ClinicalAlertRepository()
    ack = repo.append_event(
        alert_id,
        event_type="ACKNOWLEDGED",
        expected_current_event_id=repo.current(alert_id)["current_event_id"],
        actor_username="nurse",
        assigned_to="nurse",
        recorded_at="2026-07-26 10:05:00",
    )
    second = _source(alert_app, "006")
    foreign = ClinicalEngineAuditRepository().append_decision(
        recommendation_event_id=second["event_id"],
        patient_link_id=second["patient_id"],
        decision=ClinicalDecision.ACCEPTED,
        actor_username="doctor",
    )
    with pytest.raises(ClinicalAlertValidationError, match="latest clinician decision"):
        ClinicalAlertService(repository=repo).resolve(
            alert_id,
            expected_current_event_id=int(ack["id"]),
            decision_event_id=foreign,
            actor_username="doctor",
            actor_user_id=None,
            note="نامعتبر",
        )


def test_alert_rows_and_events_are_append_only(alert_app):
    from src.adapters.sqlite.core import get_db

    source = _source(alert_app, "007")
    alert_id = _create_alert(source)
    db = get_db()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE clinical_alerts SET title_fa='changed' WHERE id=?", (alert_id,))
    db.rollback()
    event_id = ClinicalAlertRepository().current(alert_id)["current_event_id"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE clinical_alert_events SET note='changed' WHERE id=?", (event_id,))
    db.rollback()


def test_fake_runtime_projects_only_internal_alert_without_side_effect_calls():
    class Facts:
        def get_mode(self):
            return "on"

        def is_selected_patient(self, _patient_id):
            return True

    class Runtime:
        def ensure_current_run(self, *_args, **_kwargs):
            return object(), {
                "run_id": "run-alert",
                "run_status": "COMPLETED",
                "as_of_at": "2026-07-26 10:00:00",
                "evaluations": [
                    {
                        "rule_code": "RF-1",
                        "rule_title": "هشدار",
                        "action_type": "redflag",
                        "severity": "CRITICAL",
                        "outcome": "FIRED",
                        "recommendation": {
                            "action_type": "redflag",
                            "title_fa": "هشدار",
                            "text_fa": "ارزیابی انسانی لازم است",
                            "suggestion_only": True,
                            "may_create_internal_task": False,
                        },
                        "recommendation_event": {"id": 91},
                    }
                ],
            }

    class Repo:
        def __init__(self):
            self.calls = []

        def create_once(self, **payload):
            self.calls.append(payload)
            return 55, True

    repo = Repo()
    result = ClinicalAlertService(
        facts=Facts(), runtime=Runtime(), repository=repo
    ).generate_patient(8)
    assert result == {"enabled": True, "created": 1, "alert_ids": [55], "issues": []}
    assert repo.calls[0]["action_type"] == "redflag"
    assert "phone_number" not in repo.calls[0]


def test_confirmation_required_task_uses_latest_accepted_decision(alert_app):
    from src.adapters.sqlite.core import get_db

    source = _source(alert_app, "008")
    audit = ClinicalEngineAuditRepository()
    accepted = audit.append_decision(
        recommendation_event_id=source["event_id"],
        patient_link_id=source["patient_id"],
        decision=ClinicalDecision.ACCEPTED,
        actor_username="doctor",
    )
    candidate = {
        "source_recommendation_event_id": source["event_id"],
        "source_decision_event_id": accepted,
        "requires_clinician_confirmation": True,
    }
    assert ClinicalFollowupRepository._assert_decision_source(get_db(), candidate) == accepted

    dismissed = audit.append_decision(
        recommendation_event_id=source["event_id"],
        patient_link_id=source["patient_id"],
        decision=ClinicalDecision.DISMISSED,
        actor_username="doctor",
        supersedes_event_id=accepted,
    )
    assert dismissed > accepted
    with pytest.raises(RuntimeError, match="CLINICIAN_DECISION_NOT_ACCEPTED"):
        ClinicalFollowupRepository._assert_decision_source(get_db(), candidate)
