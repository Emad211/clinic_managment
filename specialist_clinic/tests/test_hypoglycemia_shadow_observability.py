from __future__ import annotations

from datetime import datetime
import json

import pytest

from test_clinical_engine_v2_followups import _patient


@pytest.fixture()
def observability_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "hypoglycemia-observability.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "hypoglycemia-observability-test",
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
        clock=lambda: datetime(2026, 8, 1, 10, 0, 0),
    )


def _observability(db):
    from src.services.hypoglycemia_shadow_observability import (
        HypoglycemiaShadowObservability,
    )

    return HypoglycemiaShadowObservability(
        db,
        clock=lambda: datetime(2026, 8, 1, 10, 30, 0),
    )


def _candidate(service, patient_id, source_record_id, **overrides):
    payload = {
        "patient_link_id": patient_id,
        "source_system": "synthetic_observability",
        "source_record_id": source_record_id,
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


def _confirm(service, candidate, **overrides):
    payload = {
        "expected_current_version_id": candidate["current"]["id"],
        "decision": "CONFIRMED",
        "actor_username": "doctor",
    }
    payload.update(overrides)
    return service.adjudicate(candidate["event_id"], **payload)


def test_empty_snapshot_is_read_only_and_does_not_install_storage(observability_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    table_count_before = db.execute(
        """SELECT COUNT(*) FROM sqlite_master
           WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
    ).fetchone()[0]
    changes_before = db.total_changes

    snapshot = _observability(db).snapshot()

    assert snapshot["storage_state"] == "NOT_INSTALLED"
    assert snapshot["integrity_state"] == "OK"
    assert snapshot["current_event_total"] == 0
    assert snapshot["current_review_total"] == 0
    assert snapshot["contains_phi"] is False
    assert db.total_changes == changes_before
    assert db.execute(
        """SELECT COUNT(*) FROM sqlite_master
           WHERE type='table' AND name LIKE 'hypoglycemia_shadow_%'"""
    ).fetchone()[0] == table_count_before


def test_snapshot_aggregates_current_heads_without_phi_or_writes(observability_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    service = _service(db)

    p1 = _patient(db, national_id="HYPOMON001")
    p2 = _patient(db, national_id="HYPOMON002")
    p3 = _patient(db, national_id="HYPOMON003")
    p4 = _patient(db, national_id="HYPOMON004")
    p5 = _patient(db, national_id="HYPOMON005")

    service.create_candidate(
        patient_link_id=p1,
        source_system="synthetic_observability",
        source_record_id="OBS-001",
        actor_username="fixture-loader",
        reporter_type="PATIENT",
        occurred_at=None,
        event_level="UNKNOWN",
        verification="UNVERIFIED",
    )
    _candidate(service, p2, "OBS-002")

    confirmed_without_review = _confirm(
        service, _candidate(service, p3, "OBS-003")
    )
    assert confirmed_without_review["current"]["status"] == "CONFIRMED"

    level3 = _candidate(
        service,
        p4,
        "OBS-004",
        reporter_type="CAREGIVER",
        event_level="LEVEL_3",
        glucose_value=None,
        glucose_unit=None,
        external_assistance="YES",
        altered_function="YES",
    )
    confirmed_level3 = _confirm(service, level3)
    review = service.open_review(
        event_id=confirmed_level3["event_id"],
        expected_event_version_id=confirmed_level3["current"]["id"],
        owner_username="doctor",
        actor_username="doctor",
    )
    service.record_disposition(
        review["review_id"],
        expected_current_review_event_id=review["current"]["id"],
        disposition_type="NO_CHANGE",
        rationale="تصمیم پزشک بدون تغییر درمان ثبت شد.",
        actor_username="doctor",
    )

    conflict = _candidate(service, p5, "OBS-005")
    service.adjudicate(
        conflict["event_id"],
        expected_current_version_id=conflict["current"]["id"],
        decision="CONFLICT",
        actor_username="doctor",
        note="دو منبع با هم سازگار نبودند.",
    )

    changes_before = db.total_changes
    snapshot = _observability(db).snapshot()
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert db.total_changes == changes_before
    assert snapshot["storage_state"] == "READY"
    assert snapshot["integrity_state"] == "OK"
    assert snapshot["current_event_total"] == 5
    assert snapshot["event_counts"] == {
        "CANDIDATE": 2,
        "CONFIRMED": 2,
        "CONFLICT": 1,
        "REJECTED": 0,
        "ENTERED_IN_ERROR": 0,
    }
    assert snapshot["event_level_counts"] == {
        "LEVEL_2": 3,
        "LEVEL_3": 1,
        "UNKNOWN": 1,
    }
    assert snapshot["current_review_total"] == 1
    assert snapshot["review_counts"]["DISPOSITION_RECORDED"] == 1
    assert snapshot["disposition_counts"]["NO_CHANGE"] == 1
    assert snapshot["backlog"] == {
        "candidate_missing_occurrence_time": 1,
        "candidate_below_confirmed_verification": 2,
        "confirmed_without_active_review": 1,
    }
    assert snapshot["safety_anomalies"] == {
        "review_source_no_longer_current_confirmed": 0,
    }
    assert "patient_link_id" not in serialized
    assert "source_record_id" not in serialized
    assert "HYPOMON" not in serialized
    assert "hypo-event-" not in serialized
    assert "hypo-review-" not in serialized


def test_invalidated_review_source_is_visible_as_safety_anomaly(observability_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, national_id="HYPOMON006")
    service = _service(db)
    confirmed = _confirm(service, _candidate(service, patient_id, "OBS-006"))
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

    snapshot = _observability(db).snapshot()

    assert review["current"]["event_type"] == "OPENED"
    assert snapshot["integrity_state"] == "ATTENTION_REQUIRED"
    assert snapshot["event_counts"]["ENTERED_IN_ERROR"] == 1
    assert snapshot["review_counts"]["OPENED"] == 1
    assert snapshot["safety_anomalies"][
        "review_source_no_longer_current_confirmed"
    ] == 1


def test_partial_storage_is_reported_without_querying_or_repairing_it(
    observability_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        "CREATE TABLE hypoglycemia_shadow_event_versions (id INTEGER PRIMARY KEY)"
    )
    db.commit()
    changes_before = db.total_changes

    snapshot = _observability(db).snapshot()

    assert snapshot["storage_state"] == "INCOMPLETE"
    assert snapshot["integrity_state"] == "ATTENTION_REQUIRED"
    assert snapshot["current_event_total"] == 0
    assert db.total_changes == changes_before
    assert db.execute(
        """SELECT COUNT(*) FROM sqlite_master
           WHERE type='table' AND name='hypoglycemia_shadow_review_events'"""
    ).fetchone()[0] == 0
