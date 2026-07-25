"""Exact runtime freshness and stale-output regression tests."""
from __future__ import annotations

from datetime import datetime
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
from src.adapters.sqlite.clinical_engine_audit_repo import (
    ClinicalEngineAuditRepository,
)
from src.adapters.sqlite.clinical_engine_runtime_repo import (
    ClinicalEngineRuntimeRepository,
)
from src.adapters.sqlite.clinical_engine_runtime_schema import (
    ensure_runtime_schema,
)
from src.domain.clinical_engine import (
    ClinicalDecision,
    RunStatus,
    VerificationStatus,
)
from src.services.clinical_engine.fact_builder import (
    ENGINE_VERSION,
    FactBuilder,
)


AS_OF = datetime(2026, 7, 22, 12, 0, 0)


@pytest.fixture()
def runtime_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "runtime-freshness.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "runtime-freshness-test",
        }
    )
    context = app.app_context()
    context.push()
    ensure_runtime_schema(core.get_db())
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id="TEST0001") -> int:
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, gender, birthdate, enrolled_by,
                enrolled_at, updated_at)
               VALUES (?, 'Runtime Patient', 'female', '1988-08-01',
                       'pytest', '2026-01-01 09:00:00',
                       '2026-01-01 09:00:00')""",
            (national_id,),
        ).lastrowid
    )
    db.commit()
    return patient_id


def _revision(db, patient_id: int) -> int:
    return int(
        db.execute(
            "SELECT clinical_data_revision FROM patient_links WHERE id=?",
            (patient_id,),
        ).fetchone()["clinical_data_revision"]
    )


def _run_with_recommendation(
    patient_id: int,
    ruleset_id: int,
    *,
    revision: int,
    engine_version: str = ENGINE_VERSION,
    recommendation_key: str = "rec:runtime:test",
    include_revision: bool = True,
) -> tuple[str, int]:
    snapshot = current_snapshot(patient_id, revision=revision)
    if not include_revision:
        snapshot.pop("clinical_data_revision")
    audit = ClinicalEngineAuditRepository()
    run_id = audit.start_run(
        patient_link_id=patient_id,
        as_of_at="2026-07-22 10:00:00",
        engine_version=engine_version,
        ruleset_id=ruleset_id,
        fact_snapshot=snapshot,
    )
    event_id = audit.append_recommendation_event(
        run_id=run_id,
        recommendation_key=recommendation_key,
        action_type="educate",
        event_type="CREATED",
        payload={
            "suggestion_only": True,
            "action_type": "educate",
            "text_fa": "پیشنهاد آزمایشی",
        },
    )
    audit.complete_run(run_id, status=RunStatus.COMPLETED)
    return run_id, event_id


def test_every_clinical_source_mutation_advances_patient_revision(runtime_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    assert _revision(db, patient_id) == 0

    reading_id = int(
        db.execute(
            """INSERT INTO vital_readings
               (patient_link_id, type, value, unit, measured_at, source)
               VALUES (?, 'bp_systolic', 150, 'mmHg',
                       '2026-07-22 09:00:00', 'clinic')""",
            (patient_id,),
        ).lastrowid
    )
    db.commit()
    assert _revision(db, patient_id) == 1

    db.execute(
        "UPDATE vital_readings SET value=151 WHERE id=?",
        (reading_id,),
    )
    db.commit()
    assert _revision(db, patient_id) == 2

    db.execute(
        "DELETE FROM vital_readings WHERE id=?",
        (reading_id,),
    )
    db.commit()
    assert _revision(db, patient_id) == 3

    db.execute(
        "UPDATE patient_links SET birthdate='1988-08-02' WHERE id=?",
        (patient_id,),
    )
    db.commit()
    assert _revision(db, patient_id) == 4


def test_snapshot_binds_revision_and_preserves_patient_provenance(runtime_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source,
            recorded_by)
           VALUES (?, 'bp_systolic', 181, 'mmHg',
                   '2026-07-22 09:00:00', 'self', 'patient')""",
        (patient_id,),
    )
    db.commit()

    snapshot = FactBuilder().build(patient_id, as_of_at=AS_OF)
    pressure = next(
        fact
        for fact in snapshot.facts
        if fact.key == "observation.bp_systolic"
    )

    assert snapshot.clinical_data_revision == _revision(db, patient_id) == 1
    assert pressure.source.system == "patient"
    assert pressure.verification is VerificationStatus.PROVISIONAL
    assert "PATIENT_REPORTED" in pressure.warnings


def test_old_engine_and_missing_revision_can_never_be_current(runtime_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    ruleset_id = install_sealed_rollout()
    current_run, _ = _run_with_recommendation(
        patient_id,
        ruleset_id,
        revision=0,
    )
    _run_with_recommendation(
        patient_id,
        ruleset_id,
        revision=0,
        engine_version="2.3.0-runtime-freshness",
        recommendation_key="old-engine",
    )
    _run_with_recommendation(
        patient_id,
        ruleset_id,
        revision=0,
        recommendation_key="missing-revision",
        include_revision=False,
    )

    projected = ClinicalEngineRuntimeRepository().latest_current_run(
        patient_id,
        engine_version=ENGINE_VERSION,
        ruleset_id=ruleset_id,
        clinical_data_revision=0,
    )

    assert projected is not None
    assert projected["run_id"] == current_run
    assert projected["engine_version"] == ENGINE_VERSION
    assert projected["clinical_data_revision"] == 0


def test_patient_change_invalidates_run_and_blocks_presentation(runtime_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    ruleset_id = install_sealed_rollout()
    _run_id, event_id = _run_with_recommendation(
        patient_id,
        ruleset_id,
        revision=0,
    )
    runtime = ClinicalEngineRuntimeRepository()
    assert runtime.latest_current_run(
        patient_id,
        engine_version=ENGINE_VERSION,
        ruleset_id=ruleset_id,
        clinical_data_revision=0,
    ) is not None

    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, measured_at, source)
           VALUES (?, 'hba1c', 8.2, '2026-07-22 11:00:00', 'clinic')""",
        (patient_id,),
    )
    db.commit()
    assert _revision(db, patient_id) == 1
    assert runtime.latest_current_run(
        patient_id,
        engine_version=ENGINE_VERSION,
        ruleset_id=ruleset_id,
        clinical_data_revision=1,
    ) is None

    with pytest.raises(RuntimeError, match="STALE_RECOMMENDATION"):
        ClinicalEngineActionRepository().append_presentation_once(
            event_id,
            patient_link_id=patient_id,
            mode="on_selected",
            engine_version=ENGINE_VERSION,
            ruleset_id=ruleset_id,
            clinical_data_revision=0,
        )
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_recommendation_events "
        "WHERE event_type='PRESENTED'"
    ).fetchone()["count"] == 0


def test_patient_change_blocks_decision_in_same_write_lock(runtime_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    ruleset_id = install_sealed_rollout()
    _run_id, event_id = _run_with_recommendation(
        patient_id,
        ruleset_id,
        revision=0,
    )
    db.execute(
        """INSERT INTO allergies
           (patient_link_id, substance, reaction)
           VALUES (?, 'penicillin', 'rash')""",
        (patient_id,),
    )
    db.commit()

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


def test_raw_visible_mode_without_seal_is_off_even_during_testing(runtime_app):
    from src.adapters.sqlite.clinical_engine_fact_repo import (
        ClinicalEngineFactRepository,
    )
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        "UPDATE settings SET value='on_selected' "
        "WHERE key='clinical_engine_v2_mode'"
    )
    db.commit()
    assert ClinicalEngineFactRepository().get_mode() == "off"
