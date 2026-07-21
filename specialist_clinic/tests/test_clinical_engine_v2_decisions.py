"""PR-08 append-only presentation and clinician-decision contracts."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
tests_path = str(SPECIALIST_ROOT / "tests")
if tests_path not in sys.path:
    sys.path.insert(0, tests_path)

from test_clinical_engine_v2_compiler import valid_rule
from src.adapters.sqlite.clinical_engine_audit_repo import ClinicalEngineAuditRepository
from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository
from src.domain.clinical_engine import (
    PredicateState,
    RecommendationEventType,
    RuleOutcome,
    RunStatus,
)
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.decision_service import (
    ClinicalDecisionConflict,
    ClinicalDecisionService,
    ClinicalDecisionValidationError,
    LegacyDecisionImporter,
)
from src.services.clinical_engine.facade import ClinicalEngineReadOnlyFacade


@pytest.fixture()
def decision_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "decisions.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "decision-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id="TEST0001"):
    patient_id = int(db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, enrolled_by, enrolled_at, updated_at)
           VALUES (?, 'Decision Patient', 'pytest',
                   '2026-07-22 09:00:00', '2026-07-22 09:00:00')""",
        (national_id,),
    ).lastrowid)
    db.execute(
        "UPDATE settings SET value='on_selected' WHERE key='clinical_engine_v2_mode'"
    )
    db.commit()
    return patient_id


def _presentable_recommendation(db, patient_id):
    compiled = RuleCompiler().compile(valid_rule())
    rule_id = ClinicalEngineRulesRepository().create_rule_version(
        compiled, created_by="pytest"
    )
    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at="2026-07-22 10:00:00",
        engine_version="2.2.0-decisions",
        fact_snapshot={"facts": []},
    )
    evaluation_id = audit.append_evaluation(
        run_id=run_id,
        rule_version_id=rule_id,
        predicate_state=PredicateState.TRUE,
        outcome=RuleOutcome.FIRED,
        trace={"fact_ids": ["condition:dm"], "children": []},
        recommendation={
            "recommendation_key": "rec:test",
            "action_type": "educate",
            "text_fa": "آموزش بیمار",
            "title_fa": "آموزش",
            "suggestion_only": True,
            "requires_clinician_confirmation": False,
            "presentation": "NON_INTERRUPTIVE",
            "may_create_internal_task": False,
        },
    )
    event_id = audit.append_recommendation_event(
        run_id=run_id,
        evaluation_id=evaluation_id,
        recommendation_key="rec:test",
        action_type="educate",
        event_type=RecommendationEventType.CREATED,
        payload={"suggestion_only": True, "text_fa": "آموزش بیمار"},
    )
    audit.complete_run(run_id, status=RunStatus.COMPLETED)
    return run_id, event_id


def test_presentation_event_is_terminal_safe_and_idempotent(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    _, event_id = _presentable_recommendation(db, patient_id)

    first = ClinicalEngineAuditRepository().append_presentation_once(
        event_id, patient_link_id=patient_id
    )
    second = ClinicalEngineAuditRepository().append_presentation_once(
        event_id, patient_link_id=patient_id
    )

    assert first == second
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_recommendation_events "
        "WHERE event_type='PRESENTED'"
    ).fetchone()["c"] == 1


def test_event_timing_triggers_separate_creation_from_presentation(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    compiled = RuleCompiler().compile(valid_rule())
    rule_id = ClinicalEngineRulesRepository().create_rule_version(
        compiled, created_by="pytest"
    )
    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at="2026-07-22 10:00:00",
        engine_version="2.2.0-decisions",
        fact_snapshot={"facts": []},
    )
    evaluation_id = audit.append_evaluation(
        run_id=run_id,
        rule_version_id=rule_id,
        predicate_state=PredicateState.TRUE,
        outcome=RuleOutcome.FIRED,
        trace={"fact_ids": [], "children": []},
    )
    with pytest.raises(sqlite3.IntegrityError, match="terminal"):
        audit.append_recommendation_event(
            run_id=run_id,
            evaluation_id=evaluation_id,
            recommendation_key="rec:too-early",
            action_type="educate",
            event_type=RecommendationEventType.PRESENTED,
            payload={},
        )
    created_id = audit.append_recommendation_event(
        run_id=run_id,
        evaluation_id=evaluation_id,
        recommendation_key="rec:timing",
        action_type="educate",
        event_type=RecommendationEventType.CREATED,
        payload={"suggestion_only": True},
    )
    audit.complete_run(run_id, status=RunStatus.COMPLETED)
    with pytest.raises(sqlite3.IntegrityError, match="RUNNING"):
        audit.append_recommendation_event(
            run_id=run_id,
            evaluation_id=evaluation_id,
            recommendation_key="rec:too-late",
            action_type="educate",
            event_type=RecommendationEventType.CREATED,
            payload={},
        )
    assert audit.append_presentation_once(
        created_id, patient_link_id=patient_id
    ) > created_id


def test_gc19_acceptance_appends_decision_without_medication_mutation(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    _, event_id = _presentable_recommendation(db, patient_id)
    before = db.execute(
        "SELECT COUNT(*) AS c FROM patient_medications WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["c"]

    decision = ClinicalDecisionService().record(
        patient_link_id=patient_id,
        recommendation_event_id=event_id,
        decision="ACCEPTED",
        actor_user_id=1,
        actor_username="doctor",
        expected_current_event_id=None,
    )

    after = db.execute(
        "SELECT COUNT(*) AS c FROM patient_medications WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["c"]
    assert decision["decision"] == "ACCEPTED"
    assert decision["supersedes_event_id"] is None
    assert before == after == 0


def test_gc18_dismissal_requires_reason_and_projects_actor_time_reason(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    _, event_id = _presentable_recommendation(db, patient_id)
    service = ClinicalDecisionService()

    with pytest.raises(ClinicalDecisionValidationError, match="reason"):
        service.record(
            patient_link_id=patient_id,
            recommendation_event_id=event_id,
            decision="DISMISSED",
            actor_user_id=1,
            actor_username="doctor",
            expected_current_event_id=None,
        )
    recorded = service.record(
        patient_link_id=patient_id,
        recommendation_event_id=event_id,
        decision="DISMISSED",
        reason_code="NOT_APPLICABLE_NOW",
        reason_text="شرایط فعلی بیمار",
        actor_user_id=1,
        actor_username="doctor",
        expected_current_event_id=None,
    )
    projection = ClinicalEngineReadOnlyFacade().patient_detail(patient_id)
    item = projection["groups"][0]["items"][0]

    assert item["current_decision"]["id"] == recorded["id"]
    assert item["current_decision"]["actor_username"] == "doctor"
    assert item["current_decision"]["reason_text"] == "شرایط فعلی بیمار"
    assert item["current_decision"]["occurred_at"]


def test_correction_is_an_append_only_superseding_chain(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    _, event_id = _presentable_recommendation(db, patient_id)
    service = ClinicalDecisionService()
    first = service.record(
        patient_link_id=patient_id,
        recommendation_event_id=event_id,
        decision="DEFERRED",
        reason_code="MORE_DATA_NEEDED",
        actor_user_id=1,
        actor_username="doctor",
        expected_current_event_id=None,
    )
    corrected = service.record(
        patient_link_id=patient_id,
        recommendation_event_id=event_id,
        decision="ACCEPTED",
        actor_user_id=1,
        actor_username="doctor",
        expected_current_event_id=first["id"],
    )

    rows = db.execute(
        "SELECT * FROM clinical_decision_events "
        "WHERE recommendation_event_id=? ORDER BY id", (event_id,)
    ).fetchall()
    assert len(rows) == 2
    assert corrected["supersedes_event_id"] == first["id"]
    assert rows[0]["decision"] == "DEFERRED"
    assert rows[1]["decision"] == "ACCEPTED"


def test_stale_or_cross_patient_decision_is_rejected(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "TEST0001")
    other_id = _patient(db, "TEST0002")
    _, event_id = _presentable_recommendation(db, patient_id)
    service = ClinicalDecisionService()
    first = service.record(
        patient_link_id=patient_id,
        recommendation_event_id=event_id,
        decision="ACCEPTED",
        actor_user_id=1,
        actor_username="doctor",
        expected_current_event_id=None,
    )
    with pytest.raises(ClinicalDecisionConflict):
        service.record(
            patient_link_id=patient_id,
            recommendation_event_id=event_id,
            decision="DEFERRED",
            actor_user_id=1,
            actor_username="doctor",
            expected_current_event_id=None,
        )
    with pytest.raises(ClinicalDecisionValidationError):
        service.record(
            patient_link_id=other_id,
            recommendation_event_id=event_id,
            decision="ACCEPTED",
            actor_user_id=1,
            actor_username="doctor",
            expected_current_event_id=first["id"],
        )


def test_legacy_import_is_idempotent_and_preserves_disclaimer(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    legacy_id = int(db.execute(
        """INSERT INTO suggestion_log
           (patient_link_id, rule_code, suggestion_text, status, acted_by,
            acted_at, note)
           VALUES (?, 'LEGACY-1', 'پیشنهاد قدیمی', 'dismissed', 'legacy-doctor',
                   '2026-07-20 08:00:00', 'ثبت وضعیت؛ تاریخچه قبلی قابل بازیابی نیست')""",
        (patient_id,),
    ).lastrowid)
    db.commit()

    first = LegacyDecisionImporter().import_once()
    second = LegacyDecisionImporter().import_once()

    assert first == 1 and second == 0
    row = db.execute(
        "SELECT * FROM clinical_decision_events "
        "WHERE legacy_source_suggestion_log_id=?", (legacy_id,)
    ).fetchone()
    assert row["decision"] == "DISMISSED"
    assert "غیرقابل بازیابی" in row["reason_text"]


def test_legacy_importer_is_available_as_idempotent_cli(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    db.execute(
        """INSERT INTO suggestion_log
           (patient_link_id, rule_code, suggestion_text, status, acted_by,
            acted_at)
           VALUES (?, 'LEGACY-CLI', 'پیشنهاد قدیمی', 'accepted', 'doctor',
                   '2026-07-20 08:00:00')""",
        (patient_id,),
    )
    db.commit()

    runner = decision_app.test_cli_runner()
    first = runner.invoke(args=["import-legacy-clinical-decisions"])
    second = runner.invoke(args=["import-legacy-clinical-decisions"])

    assert first.exit_code == 0
    assert "Imported 1" in first.output
    assert second.exit_code == 0
    assert "Imported 0" in second.output


def test_thin_http_route_records_review_state_and_redirects_to_v2_panel(decision_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    _, event_id = _presentable_recommendation(db, patient_id)
    client = decision_app.test_client()
    login = client.post(
        "/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert login.status_code in {302, 303}

    response = client.post(
        f"/patients/{patient_id}/clinical-v2/decision",
        data={
            "recommendation_event_id": str(event_id),
            "expected_current_event_id": "",
            "decision": "ACCEPTED",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith("#clinical-engine-v2")
    row = db.execute(
        "SELECT * FROM clinical_decision_events WHERE recommendation_event_id=?",
        (event_id,),
    ).fetchone()
    assert row["decision"] == "ACCEPTED"
    assert db.execute(
        "SELECT COUNT(*) AS c FROM patient_medications WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["c"] == 0


def test_reviewed_main_no_longer_redirects_to_untrusted_referrer():
    route = (SPECIALIST_ROOT / "src" / "api" / "patients.py").read_text(
        encoding="utf-8"
    )
    assert "redirect(request.referrer" not in route
