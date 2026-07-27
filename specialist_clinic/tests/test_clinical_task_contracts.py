from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import sqlite3

import pytest

from test_clinical_engine_v2_compiler import valid_rule
from test_clinical_engine_v2_followups import _patient, _run
from src.domain.clinical_engine import (
    EvaluationResult,
    PredicateResult,
    PredicateState,
    RuleOutcome,
)
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.composer import (
    RecommendationComposer,
    recommendation_payload,
)


STRICT_PARAMS = {
    "due_in_days": 7,
    "due_period": "2026-H2",
    "task_contract": {
        "urgency": "PRIORITY",
        "allowed_outcome_types": ["LAB_COMPLETED"],
        "required_fact_keys": ["lab.hba1c"],
        "minimum_verification": "CONFIRMED",
        "canonical_ingestion": "REQUIRED",
        "requires_acknowledgement": True,
    },
}


@pytest.fixture()
def task_contract_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "task-contract.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "task-contract-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _task_rule(params: dict | None = None) -> dict:
    rule = valid_rule()
    rule["rule_code"] = "TEST-TASK-CONTRACT"
    rule["action_type"] = "create_followup"
    rule["semantic_key"] = "followup:strict-hba1c"
    rule["recommendation"].update(
        {
            "may_create_internal_task": True,
            "requires_clinician_confirmation": False,
            "params": deepcopy(params if params is not None else STRICT_PARAMS),
        }
    )
    return rule


def _create_strict_task(db, *, national_id="TEST0001") -> tuple[int, int]:
    from src.services.followup_engine import ClinicalV2FollowupService

    patient_id = _patient(db, national_id=national_id)
    _run(
        patient_id,
        action="create_followup",
        semantic_key="followup:strict-hba1c",
        recommendation_overrides={"params": deepcopy(STRICT_PARAMS)},
        as_of="2026-07-22 10:00:00",
    )
    result = ClinicalV2FollowupService().generate_patient(patient_id)
    assert result["issues"] == []
    assert result["created"] == 1
    return patient_id, int(result["task_ids"][0])


def test_compiler_rejects_missing_or_ambiguous_task_contract():
    compiler = RuleCompiler()
    missing = _task_rule({})
    codes = {diagnostic.code for diagnostic in compiler.validate(missing)}
    assert "MISSING_TASK_CONTRACT" in codes
    assert "INVALID_TASK_DUE_CONTRACT" in codes

    ambiguous = _task_rule(deepcopy(STRICT_PARAMS))
    ambiguous["recommendation"]["params"]["due_in_hours"] = 2
    codes = {diagnostic.code for diagnostic in compiler.validate(ambiguous)}
    assert "INVALID_TASK_DUE_CONTRACT" in codes


def test_composer_preserves_task_contract_params_in_audit_payload():
    compiled = RuleCompiler().compile(_task_rule())
    result = EvaluationResult(
        rule_code=compiled.definition.rule_code,
        rule_version=compiled.definition.version,
        outcome=RuleOutcome.FIRED,
        predicate=PredicateResult(
            node_id="task-condition",
            state=PredicateState.TRUE,
        ),
        phase=compiled.definition.phase,
    )
    recommendation = RecommendationComposer().compose(compiled, result)
    payload = recommendation_payload(
        recommendation,
        title_fa=compiled.definition.title,
        semantic_key=compiled.definition.semantic_key,
    )

    assert payload["params"] == STRICT_PARAMS
    assert payload["params"]["task_contract"]["canonical_ingestion"] == "REQUIRED"


def test_task_contract_is_persisted_with_real_due_and_is_immutable(task_contract_app):
    from src.adapters.sqlite.clinical_care_loop_repo import ClinicalCareLoopRepository
    from src.adapters.sqlite.clinical_task_contract_repo import (
        ClinicalTaskContractRepository,
    )
    from src.adapters.sqlite.core import get_db

    db = get_db()
    _patient_id, task_id = _create_strict_task(db)
    task = dict(db.execute("SELECT * FROM followup_tasks WHERE id=?", (task_id,)).fetchone())
    contract = ClinicalTaskContractRepository().get(task_id)
    current = ClinicalCareLoopRepository().current_task(task_id)

    assert task["due_date"] == "2026-07-29"
    assert contract["due_at"] == "2026-07-29 10:00:00"
    assert contract["urgency"] == "PRIORITY"
    assert contract["allowed_outcome_types"] == ["LAB_COMPLETED"]
    assert contract["required_fact_keys"] == ["lab.hba1c"]
    assert contract["minimum_verification"] == "CONFIRMED"
    assert contract["canonical_ingestion"] == "REQUIRED"
    assert current["task_contract"]["content_hash"] == contract["content_hash"]

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE clinical_task_contracts SET urgency='ROUTINE' WHERE task_id=?",
            (task_id,),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute("DELETE FROM clinical_task_contracts WHERE task_id=?", (task_id,))
    db.rollback()


def test_contract_rejects_provisional_wrong_fact_and_missing_value(task_contract_app):
    from src.adapters.sqlite.clinical_task_contract_repo import ClinicalTaskContractError
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_care_loop_service import ClinicalCareLoopService

    db = get_db()
    _patient_id, task_id = _create_strict_task(db)
    service = ClinicalCareLoopService(
        clock=lambda: datetime(2026, 7, 27, 10, 5, 0)
    )

    with pytest.raises(ClinicalTaskContractError, match="verification"):
        service.record_outcome(
            task_id,
            outcome_type="LAB_COMPLETED",
            fact_key="lab.hba1c",
            value="7.1",
            unit="%",
            verification="PROVISIONAL",
            actor_username="doctor",
            actor_user_id=1,
        )
    with pytest.raises(ClinicalTaskContractError, match="fact_key"):
        service.record_outcome(
            task_id,
            outcome_type="LAB_COMPLETED",
            fact_key="lab.ldl",
            value="90",
            unit="mg/dL",
            verification="CONFIRMED",
            actor_username="doctor",
            actor_user_id=1,
        )
    with pytest.raises(ClinicalTaskContractError, match="fact_key and value"):
        service.record_outcome(
            task_id,
            outcome_type="LAB_COMPLETED",
            fact_key="lab.hba1c",
            value="",
            unit="%",
            verification="CONFIRMED",
            actor_username="doctor",
            actor_user_id=1,
        )

    assert db.execute("SELECT COUNT(*) FROM clinical_outcome_events").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM lab_results").fetchone()[0] == 0


def test_confirmed_lab_outcome_is_ingested_idempotently_and_closes(task_contract_app):
    from src.adapters.sqlite.clinical_care_loop_repo import ClinicalCareLoopRepository
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_care_loop_service import ClinicalCareLoopService

    db = get_db()
    patient_id, task_id = _create_strict_task(db)
    root = ClinicalCareLoopRepository().current_task(task_id)
    recorded_at = datetime.fromisoformat(root["current_recorded_at"]) + timedelta(seconds=1)
    service = ClinicalCareLoopService(clock=lambda: recorded_at)
    first = service.record_outcome(
        task_id,
        outcome_type="LAB_COMPLETED",
        fact_key="lab.hba1c",
        value="7.1",
        unit="%",
        verification="CONFIRMED",
        actor_username="doctor",
        actor_user_id=1,
        observed_at="2026-07-22 10:00:00",
        source_system="clinician",
        source_record_id="confirmed-hba1c-result-001",
        note="نتیجه از آزمایشگاه مشاهده شد",
    )
    repeated = service.record_outcome(
        task_id,
        outcome_type="LAB_COMPLETED",
        fact_key="lab.hba1c",
        value="7.1",
        unit="%",
        verification="CONFIRMED",
        actor_username="doctor",
        actor_user_id=1,
        observed_at="2026-07-22 10:00:00",
        source_system="clinician",
        source_record_id="confirmed-hba1c-result-001",
        note="نتیجه از آزمایشگاه مشاهده شد",
    )

    assert repeated["id"] == first["id"]
    assert first["canonical_link"]["record_type"] == "LAB"
    lab = db.execute(
        "SELECT * FROM lab_results WHERE id=?",
        (first["canonical_link"]["record_id"],),
    ).fetchone()
    assert lab["patient_link_id"] == patient_id
    assert lab["test_key"] == "hba1c"
    assert float(lab["value"]) == 7.1
    assert db.execute("SELECT COUNT(*) FROM lab_results").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM clinical_outcome_events").fetchone()[0] == 1

    current = ClinicalCareLoopRepository().current_task(task_id)
    completed = service.transition(
        task_id,
        transition="complete",
        expected_current_event_id=current["current_event_id"],
        actor_username="doctor",
        actor_user_id=1,
        outcome_event_id=int(first["id"]),
        note="قرارداد تکمیل شد",
    )
    assert completed["status"] == "COMPLETED"
    final = ClinicalCareLoopRepository().current_task(task_id)
    assert final["current_status"] == "COMPLETED"
    assert final["canonical_links"][0]["outcome_event_id"] == first["id"]


def test_canonical_ingestion_failure_rolls_back_outcome_and_lab(task_contract_app):
    from src.adapters.sqlite.core import get_db
    from src.services.clinical_care_loop_service import ClinicalCareLoopService

    db = get_db()
    _patient_id, task_id = _create_strict_task(db)
    db.execute(
        """CREATE TRIGGER fail_canonical_link
           BEFORE INSERT ON clinical_outcome_canonical_links
           BEGIN SELECT RAISE(ABORT, 'simulated canonical link failure'); END"""
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="canonical link failure"):
        ClinicalCareLoopService().record_outcome(
            task_id,
            outcome_type="LAB_COMPLETED",
            fact_key="lab.hba1c",
            value="7.2",
            unit="%",
            verification="CONFIRMED",
            actor_username="doctor",
            actor_user_id=1,
            source_record_id="rollback-hba1c-result-001",
        )
    assert db.execute("SELECT COUNT(*) FROM clinical_outcome_events").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM lab_results").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM clinical_outcome_canonical_links").fetchone()[0] == 0


def test_mixed_clinical_booking_joins_caller_transaction(task_contract_app):
    from src.adapters.sqlite.clinical_care_loop_repo import ClinicalCareLoopRepository
    from src.adapters.sqlite.core import get_db
    from src.services.followup_booking_service import FollowupBookingService

    db = get_db()
    patient_id, task_id = _create_strict_task(db)
    result = FollowupBookingService(
        clock=lambda: datetime(2026, 7, 22, 11, 0, 0)
    ).book(
        patient_link_id=patient_id,
        task_ids=[task_id],
        scheduled_at="2026-07-30 09:00:00",
        actor_username="admin",
        actor_user_id=1,
        idempotency_key="mixed-clinical-booking-a2-001",
    )

    assert result["clinical_scheduled"] == 1
    assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM followup_contact_events").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM followup_booking_requests").fetchone()[0] == 1
    current = ClinicalCareLoopRepository().current_task(task_id)
    assert current["current_status"] == "SCHEDULED"
    assert current["current_appointment_id"] == result["appointment_id"]


def test_legacy_direct_task_gets_review_required_contract(task_contract_app):
    from test_clinical_closed_care_loop import _patient as legacy_patient
    from test_clinical_closed_care_loop import _task as legacy_task
    from src.adapters.sqlite.clinical_care_loop_repo import ClinicalCareLoopRepository
    from src.adapters.sqlite.core import get_db

    db = get_db()
    task_id = legacy_task(db, legacy_patient(db, "LEGACY-CONTRACT-1"))
    current = ClinicalCareLoopRepository().current_task(task_id)
    assert current["task_contract"]["contract_origin"] == (
        "LEGACY_BACKFILL_REVIEW_REQUIRED"
    )
    assert current["task_contract"]["canonical_ingestion"] == "OPTIONAL"
