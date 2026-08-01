from __future__ import annotations

from datetime import datetime
import sqlite3

import pytest

from test_clinical_engine_v2_followups import _patient


@pytest.fixture()
def shadow_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "hypoglycemia-shadow.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "hypoglycemia-shadow-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _service(db):
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowService

    return HypoglycemiaShadowService(
        db,
        clock=lambda: datetime(2026, 8, 1, 9, 30, 0),
    )


def _candidate(service, patient_id, **overrides):
    payload = {
        "patient_link_id": patient_id,
        "source_system": "synthetic_fixture",
        "source_record_id": "FX-6.19-001",
        "actor_username": "fixture-loader",
        "reporter_type": "DEVICE",
        "occurred_at": "2026-08-01 08:45:00",
        "event_level": "LEVEL_2",
        "glucose_value": 51,
        "glucose_unit": "mg/dL",
        "verification": "PROVISIONAL",
    }
    payload.update(overrides)
    return service.create_candidate(**payload)


def test_candidate_is_idempotent_and_has_no_automatic_side_effect(shadow_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, national_id="HYPOSHADOW001")
    service = _service(db)

    first = _candidate(service, patient_id)
    repeated = _candidate(service, patient_id)

    assert repeated["event_id"] == first["event_id"]
    assert first["current"]["status"] == "CANDIDATE"
    assert db.execute(
        "SELECT COUNT(*) FROM hypoglycemia_shadow_review_events"
    ).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM followup_tasks").fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM clinical_recommendation_events"
    ).fetchone()[0] == 0


def test_source_identity_cannot_cross_patients(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowConflict

    db = get_db()
    first_patient = _patient(db, national_id="HYPOSHADOW002")
    second_patient = _patient(db, national_id="HYPOSHADOW003")
    service = _service(db)
    _candidate(service, first_patient)

    with pytest.raises(HypoglycemiaShadowConflict, match="another patient"):
        _candidate(service, second_patient)


def test_level2_confirmation_requires_glucose_below_54(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowValidationError

    db = get_db()
    patient_id = _patient(db, national_id="HYPOSHADOW004")
    service = _service(db)
    candidate = _candidate(
        service,
        patient_id,
        source_record_id="FX-6.19-002",
        glucose_value=70,
    )

    with pytest.raises(HypoglycemiaShadowValidationError, match="below 54"):
        service.adjudicate(
            candidate["event_id"],
            expected_current_version_id=candidate["current"]["id"],
            decision="CONFIRMED",
            actor_username="doctor",
        )
    assert service.get_event(candidate["event_id"])["current"]["status"] == "CANDIDATE"


def test_level3_uses_assistance_and_altered_function_not_glucose(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowValidationError

    db = get_db()
    patient_id = _patient(db, national_id="HYPOSHADOW005")
    service = _service(db)
    candidate = _candidate(
        service,
        patient_id,
        source_record_id="FX-6.19-003",
        reporter_type="CAREGIVER",
        event_level="LEVEL_3",
        glucose_value=None,
        glucose_unit=None,
        external_assistance="YES",
        altered_function="UNKNOWN",
    )

    with pytest.raises(HypoglycemiaShadowValidationError, match="altered"):
        service.adjudicate(
            candidate["event_id"],
            expected_current_version_id=candidate["current"]["id"],
            decision="CONFIRMED",
            actor_username="doctor",
        )

    confirmed = service.adjudicate(
        candidate["event_id"],
        expected_current_version_id=candidate["current"]["id"],
        decision="CONFIRMED",
        actor_username="doctor",
        altered_function="YES",
    )
    assert confirmed["current"]["status"] == "CONFIRMED"
    assert confirmed["current"]["glucose_value"] is None


def test_event_history_is_append_only_and_stale_heads_fail(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowConflict

    db = get_db()
    patient_id = _patient(db, national_id="HYPOSHADOW006")
    service = _service(db)
    candidate = _candidate(
        service,
        patient_id,
        source_record_id="FX-6.19-004",
    )
    confirmed = service.adjudicate(
        candidate["event_id"],
        expected_current_version_id=candidate["current"]["id"],
        decision="CONFIRMED",
        actor_username="doctor",
    )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE hypoglycemia_shadow_event_versions SET note='mutated' WHERE id=?",
            (confirmed["current"]["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute(
            "DELETE FROM hypoglycemia_shadow_event_versions WHERE id=?",
            (confirmed["current"]["id"],),
        )
    db.rollback()
    with pytest.raises(HypoglycemiaShadowConflict, match="head changed"):
        service.adjudicate(
            candidate["event_id"],
            expected_current_version_id=candidate["current"]["id"],
            decision="ENTERED_IN_ERROR",
            actor_username="doctor",
        )


def test_review_requires_current_confirmed_event_and_is_idempotent(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowValidationError

    db = get_db()
    patient_id = _patient(db, national_id="HYPOSHADOW007")
    service = _service(db)
    candidate = _candidate(
        service,
        patient_id,
        source_record_id="FX-6.19-005",
    )

    with pytest.raises(HypoglycemiaShadowValidationError, match="confirmed"):
        service.open_review(
            event_id=candidate["event_id"],
            expected_event_version_id=candidate["current"]["id"],
            owner_username="doctor",
            actor_username="doctor",
        )

    confirmed = service.adjudicate(
        candidate["event_id"],
        expected_current_version_id=candidate["current"]["id"],
        decision="CONFIRMED",
        actor_username="doctor",
    )
    first = service.open_review(
        event_id=confirmed["event_id"],
        expected_event_version_id=confirmed["current"]["id"],
        owner_username="doctor",
        actor_username="doctor",
    )
    repeated = service.open_review(
        event_id=confirmed["event_id"],
        expected_event_version_id=confirmed["current"]["id"],
        owner_username="doctor",
        actor_username="doctor",
    )

    assert repeated["review_id"] == first["review_id"]
    assert first["current"]["event_type"] == "OPENED"


def test_disposition_records_clinician_decision_without_executing_it(shadow_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, national_id="HYPOSHADOW008")
    service = _service(db)
    candidate = _candidate(
        service,
        patient_id,
        source_record_id="FX-6.19-006",
    )
    confirmed = service.adjudicate(
        candidate["event_id"],
        expected_current_version_id=candidate["current"]["id"],
        decision="CONFIRMED",
        actor_username="doctor",
    )
    review = service.open_review(
        event_id=confirmed["event_id"],
        expected_event_version_id=confirmed["current"]["id"],
        owner_username="doctor",
        actor_username="doctor",
    )
    medication_count = db.execute(
        "SELECT COUNT(*) FROM patient_medications WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0]
    followup_count = db.execute(
        "SELECT COUNT(*) FROM followup_tasks WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0]
    recommendation_count = db.execute(
        "SELECT COUNT(*) FROM clinical_recommendation_events"
    ).fetchone()[0]

    result = service.record_disposition(
        review["review_id"],
        expected_current_review_event_id=review["current"]["id"],
        disposition_type="MEDICATION_CHANGE_RECORDED",
        rationale="تصمیم مستقل پزشک پس از مرور پرونده ثبت شد.",
        actor_username="doctor",
    )

    assert result["current"]["disposition_type"] == "MEDICATION_CHANGE_RECORDED"
    assert db.execute(
        "SELECT COUNT(*) FROM patient_medications WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == medication_count
    assert db.execute(
        "SELECT COUNT(*) FROM followup_tasks WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == followup_count
    assert db.execute(
        "SELECT COUNT(*) FROM clinical_recommendation_events"
    ).fetchone()[0] == recommendation_count


def test_entered_in_error_event_cannot_open_review(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowValidationError

    db = get_db()
    patient_id = _patient(db, national_id="HYPOSHADOW009")
    service = _service(db)
    candidate = _candidate(
        service,
        patient_id,
        source_record_id="FX-6.19-007",
    )
    invalidated = service.adjudicate(
        candidate["event_id"],
        expected_current_version_id=candidate["current"]["id"],
        decision="ENTERED_IN_ERROR",
        actor_username="doctor",
        note="منبع اشتباه بود.",
    )

    with pytest.raises(HypoglycemiaShadowValidationError, match="confirmed"):
        service.open_review(
            event_id=invalidated["event_id"],
            expected_event_version_id=invalidated["current"]["id"],
            owner_username="doctor",
            actor_username="doctor",
        )


def test_review_disposition_is_blocked_after_source_event_is_invalidated(shadow_app):
    from src.adapters.sqlite.core import get_db
    from src.services.hypoglycemia_shadow import HypoglycemiaShadowValidationError

    db = get_db()
    patient_id = _patient(db, national_id="HYPOSHADOW010")
    service = _service(db)
    candidate = _candidate(
        service,
        patient_id,
        source_record_id="FX-6.19-008",
    )
    confirmed = service.adjudicate(
        candidate["event_id"],
        expected_current_version_id=candidate["current"]["id"],
        decision="CONFIRMED",
        actor_username="doctor",
    )
    review = service.open_review(
        event_id=confirmed["event_id"],
        expected_event_version_id=confirmed["current"]["id"],
        owner_username="doctor",
        actor_username="doctor",
    )
    service.adjudicate(
        confirmed["event_id"],
        expected_current_version_id=confirmed["current"]["id"],
        decision="ENTERED_IN_ERROR",
        actor_username="doctor",
        note="شاهد منبع ابطال شد.",
    )

    with pytest.raises(HypoglycemiaShadowValidationError, match="no longer"):
        service.record_disposition(
            review["review_id"],
            expected_current_review_event_id=review["current"]["id"],
            disposition_type="NO_CHANGE",
            rationale="نباید پس از ابطال رخداد ثبت شود.",
            actor_username="doctor",
        )
