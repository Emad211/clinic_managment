"""Atomic rollout-state guards for presentation and clinician decisions."""
from __future__ import annotations

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
from src.adapters.sqlite.clinical_engine_action_repo import (
    ClinicalEngineActionRepository,
)
from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.clinical_engine_audit_repo import (
    ClinicalEngineAuditRepository,
)
from src.domain.clinical_engine import ClinicalDecision, RunStatus
from src.services.clinical_engine.fact_builder import ENGINE_VERSION


@pytest.fixture()
def action_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "action-contract.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "action-contract-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _prepare_contract(db):
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, gender, birthdate, enrolled_by)
               VALUES ('TEST0001', 'Action Patient', 'female',
                       '1988-08-01', 'pytest')"""
        ).lastrowid
    )
    db.commit()
    ruleset_id = install_sealed_rollout()

    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at="2026-07-22 10:00:00",
        engine_version=ENGINE_VERSION,
        ruleset_id=ruleset_id,
        fact_snapshot=current_snapshot(patient_id),
    )
    event_id = audit.append_recommendation_event(
        run_id=run_id,
        recommendation_key="rec:action-contract",
        action_type="educate",
        event_type="CREATED",
        payload={
            "suggestion_only": True,
            "action_type": "educate",
            "text_fa": "پیشنهاد آزمایشی",
        },
    )
    audit.complete_run(run_id, status=RunStatus.COMPLETED)
    return (
        patient_id,
        ruleset_id,
        event_id,
        ClinicalEngineActivationRepository(),
    )


def _presentation_count(db) -> int:
    return int(
        db.execute(
            """SELECT COUNT(*) AS count
               FROM clinical_recommendation_events
               WHERE event_type='PRESENTED'"""
        ).fetchone()["count"]
    )


def test_valid_effective_rollout_allows_presentation_and_decision(action_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id, ruleset_id, event_id, _state = _prepare_contract(db)
    actions = ClinicalEngineActionRepository()

    actions.append_presentation_once(
        event_id,
        patient_link_id=patient_id,
        mode="on_selected",
        engine_version=ENGINE_VERSION,
        ruleset_id=ruleset_id,
        clinical_data_revision=0,
    )
    decision = actions.append_current_decision(
        recommendation_event_id=event_id,
        patient_link_id=patient_id,
        decision=ClinicalDecision.ACCEPTED,
        actor_username="physician",
        actor_user_id=None,
        expected_current_event_id=None,
        mode="on_selected",
        engine_version=ENGINE_VERSION,
        ruleset_id=ruleset_id,
        clinical_data_revision=0,
    )

    assert _presentation_count(db) == 1
    assert decision["decision"] == "ACCEPTED"


def test_rollback_before_write_blocks_presentation(action_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id, ruleset_id, event_id, state = _prepare_contract(db)
    state.set_raw_mode("off")
    state.delete("seal")

    with pytest.raises(RuntimeError, match="STALE_RECOMMENDATION"):
        ClinicalEngineActionRepository().append_presentation_once(
            event_id,
            patient_link_id=patient_id,
            mode="on_selected",
            engine_version=ENGINE_VERSION,
            ruleset_id=ruleset_id,
            clinical_data_revision=0,
        )
    assert _presentation_count(db) == 0


def test_approval_revocation_before_write_blocks_decision(action_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id, ruleset_id, event_id, state = _prepare_contract(db)
    state.delete("approval_technical")

    with pytest.raises(RuntimeError, match="STALE_RECOMMENDATION"):
        ClinicalEngineActionRepository().append_current_decision(
            recommendation_event_id=event_id,
            patient_link_id=patient_id,
            decision=ClinicalDecision.ACCEPTED,
            actor_username="physician",
            actor_user_id=None,
            expected_current_event_id=None,
            mode="on_selected",
            engine_version=ENGINE_VERSION,
            ruleset_id=ruleset_id,
            clinical_data_revision=0,
        )
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_decision_events"
    ).fetchone()["count"] == 0
