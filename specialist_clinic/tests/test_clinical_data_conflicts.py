"""Focused safety contract for explicit source conflicts and completeness."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.adapters.sqlite.clinical_data_conflict_repo import (
    ClinicalDataConflictRepository,
    ClinicalDataConflictStale,
)
from src.adapters.sqlite.clinical_reconciliation_repo import (
    ClinicalReconciliationRepository,
)
from src.domain.clinical_engine import (
    ClinicalDataConflictError,
    ConflictStatus,
    FactStatus,
    VerificationStatus,
)
from src.services.clinical_engine.fact_builder import FactBuilder


AS_OF = datetime(2026, 7, 24, 12, 0, 0)


@pytest.fixture()
def conflict_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "conflicts.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "conflict-test",
        }
    )
    ctx = app.app_context()
    ctx.push()
    yield app
    ctx.pop()
    core._initialized = False


def _patient(db, national_id="CONFLICT001") -> int:
    cursor = db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, enrolled_by, enrolled_at)
           VALUES (?, 'بیمار تعارض', 'pytest', '2026-07-20 09:00:00')""",
        (national_id,),
    )
    db.commit()
    return int(cursor.lastrowid)


def _condition(db):
    row = db.execute(
        "SELECT id, code FROM conditions WHERE code IS NOT NULL ORDER BY id LIMIT 1"
    ).fetchone()
    assert row
    return dict(row)


def _fact(snapshot, key):
    return next(fact for fact in snapshot.facts if fact.key == key)


def _condition_conflict(db, patient_id: int):
    condition = _condition(db)
    for source, stage in (("clinician", "stage-a"), ("patient", "stage-b")):
        db.execute(
            """INSERT INTO patient_conditions
               (patient_link_id, condition_id, stage, onset_date, diagnosed_at,
                source_system, source_record_id, source_assertion, verification,
                recorded_by)
               VALUES (?, ?, ?, '2020-01-01', '2026-07-20 10:00:00',
                       ?, ?, 'PRESENT', 'CONFIRMED', ?)""",
            (
                patient_id,
                condition["id"],
                stage,
                source,
                f"{source}-condition",
                source,
            ),
        )
    db.commit()
    return condition


def test_fresh_database_has_append_only_conflict_storage(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"allergy_catalog", "clinical_data_conflict_events"} <= tables
    for table in ("patient_conditions", "patient_medications", "allergies"):
        columns = {
            row["name"]
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        assert {
            "source_system",
            "source_record_id",
            "source_assertion",
            "verification",
            "recorded_by",
        } <= columns
    allergy_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(allergies)").fetchall()
    }
    assert "allergy_concept_id" in allergy_columns
    reconciliation_columns = {
        row["name"]
        for row in db.execute(
            "PRAGMA table_info(clinical_reconciliation_events)"
        ).fetchall()
    }
    assert {
        "conflict_snapshot_hash",
        "conflict_count",
        "unresolved_conflict_count",
        "mapping_complete",
        "reviewed_sources_json",
    } <= reconciliation_columns


def test_unresolved_condition_conflict_suppresses_usable_facts(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    condition = _condition_conflict(db, patient_id)

    projection = ClinicalReconciliationRepository().projection(
        patient_id, "conditions", as_of_at=AS_OF
    )
    fact_snapshot = FactBuilder().build(patient_id, as_of_at=AS_OF)
    aggregate = _fact(fact_snapshot, "condition.codes")

    assert projection.state == "conflict_unresolved"
    assert projection.conflict_count == 1
    assert projection.unresolved_conflict_count == 1
    assert projection.item_count == 0
    assert aggregate.status is FactStatus.UNKNOWN
    assert aggregate.verification is VerificationStatus.UNVERIFIED
    assert aggregate.conflict is ConflictStatus.PRESENT
    assert "UNRESOLVED_CLINICAL_CONFLICT" in aggregate.warnings
    assert not [
        fact
        for fact in fact_snapshot.facts
        if fact.key == f"condition.{condition['code']}"
    ]
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_data_conflict_events"
    ).fetchone()["c"] == 0  # projection/GET semantics never write


def test_select_resolution_is_exact_and_source_change_reopens_conflict(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CONFLICT002")
    condition = _condition_conflict(db, patient_id)
    conflicts = ClinicalDataConflictRepository(db, clock=lambda: AS_OF)
    initial = conflicts.projection(patient_id, "conditions", as_of_at=AS_OF)
    group = initial.groups[0]
    chosen = group["candidates"][0]["candidate_key"]

    event = conflicts.resolve(
        patient_link_id=patient_id,
        collection_key="conditions",
        conflict_group_key=group["group_key"],
        method="SELECT_CANDIDATE",
        actor_username="doctor",
        actor_user_id=None,
        expected_candidate_set_hash=group["candidate_set_hash"],
        expected_current_event_id=None,
        selected_candidate_keys=[chosen],
        note="source checked",
    )
    assert event["status"] == "RESOLVED"

    reconciled = ClinicalReconciliationRepository(db).record(
        patient_link_id=patient_id,
        collection_key="conditions",
        completeness="complete",
        actor_username="doctor",
        reconciled_at=AS_OF,
    )
    assert reconciled["unresolved_conflict_count"] == 0
    snapshot = FactBuilder().build(patient_id, as_of_at=AS_OF)
    aggregate = _fact(snapshot, "condition.codes")
    assert aggregate.status is FactStatus.PRESENT
    assert aggregate.value == [condition["code"]]
    assert aggregate.verification is VerificationStatus.CONFIRMED
    specific = [
        fact for fact in snapshot.facts
        if fact.key == f"condition.{condition['code']}"
    ]
    assert len(specific) == 1

    # A new candidate changes the exact source set. The previous resolution and
    # reconciliation are stale without any hidden last-write/source precedence.
    db.execute(
        """INSERT INTO patient_conditions
           (patient_link_id, condition_id, stage, onset_date, diagnosed_at,
            source_system, source_record_id, source_assertion, verification)
           VALUES (?, ?, 'stage-c', '2020-01-01', '2026-07-23 10:00:00',
                   'hospital', 'hospital-condition', 'PRESENT', 'CONFIRMED')""",
        (patient_id, condition["id"]),
    )
    db.commit()
    stale = ClinicalReconciliationRepository(db).projection(
        patient_id, "conditions", as_of_at=AS_OF
    )
    assert stale.state == "conflict_unresolved"
    assert "STALE_CONFLICT_RESOLUTION" in stale.warnings


def test_resolution_rejects_stale_candidate_hash_without_partial_writes(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CONFLICT003")
    _condition_conflict(db, patient_id)
    repo = ClinicalDataConflictRepository(db, clock=lambda: AS_OF)
    group = repo.projection(patient_id, "conditions", as_of_at=AS_OF).groups[0]

    db.execute(
        "UPDATE patient_conditions SET stage='changed' WHERE patient_link_id=? AND source_system='patient'",
        (patient_id,),
    )
    db.commit()
    with pytest.raises(ClinicalDataConflictStale, match="candidate sources changed"):
        repo.resolve(
            patient_link_id=patient_id,
            collection_key="conditions",
            conflict_group_key=group["group_key"],
            method="MARK_UNKNOWN",
            actor_username="doctor",
            actor_user_id=None,
            expected_candidate_set_hash=group["candidate_set_hash"],
            expected_current_event_id=None,
        )
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_data_conflict_events"
    ).fetchone()["c"] == 0


def test_mark_unknown_and_confirmed_absent_have_distinct_fact_semantics(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    first = _patient(db, "CONFLICT004")
    second = _patient(db, "CONFLICT005")
    _condition_conflict(db, first)
    _condition_conflict(db, second)

    for patient_id, method in (
        (first, "MARK_UNKNOWN"),
        (second, "CONFIRMED_ABSENT"),
    ):
        repo = ClinicalDataConflictRepository(db, clock=lambda: AS_OF)
        group = repo.projection(patient_id, "conditions", as_of_at=AS_OF).groups[0]
        repo.resolve(
            patient_link_id=patient_id,
            collection_key="conditions",
            conflict_group_key=group["group_key"],
            method=method,
            actor_username="doctor",
            actor_user_id=None,
            expected_candidate_set_hash=group["candidate_set_hash"],
            expected_current_event_id=None,
        )
        if method == "CONFIRMED_ABSENT":
            ClinicalReconciliationRepository(db).record(
                patient_link_id=patient_id,
                collection_key="conditions",
                completeness="complete",
                actor_username="doctor",
                reconciled_at=AS_OF,
            )

    unknown = _fact(FactBuilder().build(first, as_of_at=AS_OF), "condition.codes")
    absent = _fact(FactBuilder().build(second, as_of_at=AS_OF), "condition.codes")
    assert unknown.status is FactStatus.UNKNOWN
    assert unknown.conflict is ConflictStatus.UNKNOWN
    assert absent.status is FactStatus.ABSENT
    assert absent.conflict is ConflictStatus.NONE
    assert absent.verification is VerificationStatus.CONFIRMED


def test_merge_accepts_only_complementary_allergy_candidates(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CONFLICT006")
    concept = db.execute(
        "SELECT id FROM allergy_catalog WHERE concept_key='penicillin'"
    ).fetchone()
    assert concept
    db.execute(
        """INSERT INTO allergies
           (patient_link_id, substance, reaction, severity, is_active,
            allergy_concept_id, source_system, source_record_id,
            source_assertion, verification, created_at)
           VALUES (?, 'Penicillin', 'rash', NULL, 1, ?, 'patient', 'p-allergy',
                   'PRESENT', 'PROVISIONAL', '2026-07-20 09:00:00')""",
        (patient_id, concept["id"]),
    )
    db.execute(
        """INSERT INTO allergies
           (patient_link_id, substance, reaction, severity, is_active,
            allergy_concept_id, source_system, source_record_id,
            source_assertion, verification, created_at)
           VALUES (?, 'Penicillin', NULL, 'severe', 1, ?, 'clinician', 'c-allergy',
                   'PRESENT', 'CONFIRMED', '2026-07-20 10:00:00')""",
        (patient_id, concept["id"]),
    )
    db.commit()
    repo = ClinicalDataConflictRepository(db, clock=lambda: AS_OF)
    group = repo.projection(patient_id, "allergies", as_of_at=AS_OF).groups[0]
    keys = [candidate["candidate_key"] for candidate in group["candidates"]]
    repo.resolve(
        patient_link_id=patient_id,
        collection_key="allergies",
        conflict_group_key=group["group_key"],
        method="MERGE_CANDIDATES",
        actor_username="doctor",
        actor_user_id=None,
        expected_candidate_set_hash=group["candidate_set_hash"],
        expected_current_event_id=None,
        selected_candidate_keys=keys,
    )
    ClinicalReconciliationRepository(db).record(
        patient_link_id=patient_id,
        collection_key="allergies",
        completeness="complete",
        actor_username="doctor",
        reconciled_at=AS_OF,
    )
    projection = ClinicalReconciliationRepository(db).projection(
        patient_id, "allergies", as_of_at=AS_OF
    )
    assert projection.state == "confirmed_present"
    assert projection.values == ("penicillin",)
    assert projection.items[0]["reaction"] == "rash"
    assert projection.items[0]["severity"] == "severe"


def test_conflict_events_are_append_only(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CONFLICT007")
    _condition_conflict(db, patient_id)
    repo = ClinicalDataConflictRepository(db, clock=lambda: AS_OF)
    group = repo.projection(patient_id, "conditions", as_of_at=AS_OF).groups[0]
    event = repo.resolve(
        patient_link_id=patient_id,
        collection_key="conditions",
        conflict_group_key=group["group_key"],
        method="MARK_UNKNOWN",
        actor_username="doctor",
        actor_user_id=None,
        expected_candidate_set_hash=group["candidate_set_hash"],
        expected_current_event_id=None,
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE clinical_data_conflict_events SET note='changed' WHERE id=?",
            (event["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute(
            "DELETE FROM clinical_data_conflict_events WHERE id=?",
            (event["id"],),
        )
    db.rollback()


def _login(client, username="admin", password="admin"):
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code in {302, 303}


def test_workspace_exposes_provenance_and_manager_can_resolve(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CONFLICTUI1")
    _condition_conflict(db, patient_id)
    projection = ClinicalDataConflictRepository(db, clock=lambda: AS_OF).projection(
        patient_id, "conditions", as_of_at=AS_OF
    )
    group = projection.groups[0]
    chosen = group["candidates"][0]["candidate_key"]

    client = conflict_app.test_client()
    _login(client)
    page = client.get(f"/patients/{patient_id}/reconciliation")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "تعارض بالینی حل‌نشده" in html
    assert "clinician / clinician-condition" in html
    assert "patient / patient-condition" in html
    assert "ثبت resolution append-only" in html
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_data_conflict_events"
    ).fetchone()["c"] == 0

    tampered = client.post(
        f"/patients/{patient_id}/reconciliation/conditions/conflicts/resolve",
        data={
            "conflict_group_key": group["group_key"],
            "expected_candidate_set_hash": group["candidate_set_hash"],
            "expected_current_event_id": "not-an-integer",
            "resolution_method": "SELECT_CANDIDATE",
            "candidate_keys": [chosen],
        },
        follow_redirects=True,
    )
    assert tampered.status_code == 200
    assert "شناسهٔ وضعیت جاری معتبر نیست" in tampered.get_data(as_text=True)
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_data_conflict_events"
    ).fetchone()["c"] == 0

    resolved = client.post(
        f"/patients/{patient_id}/reconciliation/conditions/conflicts/resolve",
        data={
            "conflict_group_key": group["group_key"],
            "expected_candidate_set_hash": group["candidate_set_hash"],
            "expected_current_event_id": "",
            "resolution_method": "SELECT_CANDIDATE",
            "candidate_keys": [chosen],
            "note": "source compared in visit",
        },
        follow_redirects=True,
    )
    assert resolved.status_code == 200
    html = resolved.get_data(as_text=True)
    assert "resolution تعارض ثبت شد" in html
    assert "منبع منتخب" in html
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_data_conflict_events"
    ).fetchone()["c"] == 2


def test_staff_cannot_resolve_conflict(conflict_app):
    from src.adapters.sqlite.core import get_db
    from src.services.auth_service import AuthService

    db = get_db()
    patient_id = _patient(db, "CONFLICTUI2")
    _condition_conflict(db, patient_id)
    group = ClinicalDataConflictRepository(db, clock=lambda: AS_OF).projection(
        patient_id, "conditions", as_of_at=AS_OF
    ).groups[0]
    assert AuthService().register_user(
        "conflict-staff", "safe-password", "staff", "کارمند"
    )

    client = conflict_app.test_client()
    _login(client, "conflict-staff", "safe-password")
    response = client.post(
        f"/patients/{patient_id}/reconciliation/conditions/conflicts/resolve",
        data={
            "conflict_group_key": group["group_key"],
            "expected_candidate_set_hash": group["candidate_set_hash"],
            "resolution_method": "MARK_UNKNOWN",
        },
    )
    assert response.status_code in {302, 303}
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_data_conflict_events"
    ).fetchone()["c"] == 0


def test_complete_review_is_blocked_while_conflict_is_unresolved(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CONFLICT008")
    _condition_conflict(db, patient_id)
    with pytest.raises(ValueError, match="unresolved clinical conflicts"):
        ClinicalReconciliationRepository(db).record(
            patient_link_id=patient_id,
            collection_key="conditions",
            completeness="complete",
            actor_username="doctor",
            reconciled_at=AS_OF,
        )
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_reconciliation_events"
    ).fetchone()["c"] == 0


def test_medication_dose_disagreement_is_not_resolved_by_last_row_wins(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CONFLICT009")
    catalog = db.execute(
        """SELECT id, generic_fa, drug_class_key FROM drug_catalog
           WHERE is_active=1 AND drug_class_key IS NOT NULL
           ORDER BY id LIMIT 1"""
    ).fetchone()
    assert catalog
    for source, dose in (("patient", "500 mg"), ("clinician", "1000 mg")):
        cursor = db.execute(
            """INSERT INTO patient_medications
               (patient_link_id, drug_name, dose, schedule, start_date, is_active,
                drug_class, drug_catalog_id, source_system, source_record_id,
                source_assertion, verification, created_at)
               VALUES (?, ?, ?, 'روزانه', '2025-01-01', 1, ?, ?, ?, ?,
                       'PRESENT', 'CONFIRMED', '2026-07-20 10:00:00')""",
            (
                patient_id,
                catalog["generic_fa"],
                dose,
                catalog["drug_class_key"],
                catalog["id"],
                source,
                f"{source}-medication",
            ),
        )
        db.execute(
            """INSERT INTO medication_events
               (patient_link_id, medication_id, drug_name, event_type, dose,
                event_date, created_at, created_by)
               VALUES (?, ?, ?, 'start', ?, '2025-01-01',
                       '2026-07-20 10:00:00', ?)""",
            (
                patient_id,
                cursor.lastrowid,
                catalog["generic_fa"],
                dose,
                source,
            ),
        )
    db.commit()

    projection = ClinicalReconciliationRepository(db).projection(
        patient_id, "medications", as_of_at=AS_OF
    )
    fact = _fact(FactBuilder().build(patient_id, as_of_at=AS_OF), "medication.classes")
    assert projection.state == "conflict_unresolved"
    assert projection.items == ()
    assert fact.status is FactStatus.UNKNOWN
    assert not [
        item for item in FactBuilder().build(patient_id, as_of_at=AS_OF).facts
        if item.key == f"medication.{catalog['drug_class_key']}"
    ]


def test_present_absent_source_assertions_require_explicit_resolution(conflict_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CONFLICT010")
    condition = _condition(db)
    for source, assertion in (("clinician", "PRESENT"), ("external", "ABSENT")):
        db.execute(
            """INSERT INTO patient_conditions
               (patient_link_id, condition_id, onset_date, diagnosed_at, is_active,
                source_system, source_record_id, source_assertion, verification)
               VALUES (?, ?, '2020-01-01', '2026-07-20 10:00:00', 1,
                       ?, ?, ?, 'CONFIRMED')""",
            (
                patient_id,
                condition["id"],
                source,
                f"{source}-assertion",
                assertion,
            ),
        )
    db.commit()
    group = ClinicalDataConflictRepository(db, clock=lambda: AS_OF).projection(
        patient_id, "conditions", as_of_at=AS_OF
    ).groups[0]
    assert "ASSERTION_DISAGREEMENT" in group["reasons"]
    assert {candidate["assertion"] for candidate in group["candidates"]} == {
        "PRESENT",
        "ABSENT",
    }
    absent = next(
        candidate["candidate_key"]
        for candidate in group["candidates"]
        if candidate["assertion"] == "ABSENT"
    )
    with pytest.raises(
        ClinicalDataConflictError,
        match="requires a PRESENT candidate",
    ):
        ClinicalDataConflictRepository(db, clock=lambda: AS_OF).resolve(
            patient_link_id=patient_id,
            collection_key="conditions",
            conflict_group_key=group["group_key"],
            method="SELECT_CANDIDATE",
            actor_username="doctor",
            actor_user_id=None,
            expected_candidate_set_hash=group["candidate_set_hash"],
            expected_current_event_id=None,
            selected_candidate_keys=(absent,),
        )
    assert db.execute(
        "SELECT COUNT(*) AS c FROM clinical_data_conflict_events"
    ).fetchone()["c"] == 0


def test_exact_allergy_alias_maps_to_canonical_concept(conflict_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.patients_repo import PatientRepository

    db = get_db()
    patient_id = _patient(db, "CONFLICT011")
    allergy_id = PatientRepository().add_allergy(
        patient_id,
        substance="Penicillin",
        reaction="rash",
        severity="moderate",
        recorded_by="doctor",
    )
    db.execute(
        "UPDATE allergies SET created_at='2026-07-20 10:00:00' WHERE id=?",
        (allergy_id,),
    )
    db.commit()
    row = db.execute(
        """SELECT allergy.allergy_concept_id, catalog.concept_key
           FROM allergies allergy
           JOIN allergy_catalog catalog ON catalog.id=allergy.allergy_concept_id
           WHERE allergy.id=?""",
        (allergy_id,),
    ).fetchone()
    assert dict(row) == {
        "allergy_concept_id": row["allergy_concept_id"],
        "concept_key": "penicillin",
    }
    ClinicalReconciliationRepository(db).record(
        patient_link_id=patient_id,
        collection_key="allergies",
        completeness="complete",
        actor_username="doctor",
        reconciled_at=AS_OF,
    )
    fact = _fact(FactBuilder().build(patient_id, as_of_at=AS_OF), "allergy.substances")
    assert fact.value == ["penicillin"]
    assert fact.verification is VerificationStatus.CONFIRMED


def test_repository_preserves_distinct_source_records_for_one_concept(conflict_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.patients_repo import PatientRepository

    db = get_db()
    patient_id = _patient(db, "CONFLICT012")
    condition = _condition(db)
    repository = PatientRepository()
    first = repository.add_condition(
        patient_id,
        condition["id"],
        stage="stage-a",
        onset_date="2020-01-01",
        source_system="clinician",
        source_record_id="problem-list-1",
        recorded_by="doctor",
    )
    second = repository.add_condition(
        patient_id,
        condition["id"],
        stage="stage-b",
        onset_date="2020-01-01",
        source_system="patient",
        source_record_id="patient-report-1",
        recorded_by="doctor",
    )
    assert first != second
    projection = ClinicalDataConflictRepository(db, clock=lambda: AS_OF).projection(
        patient_id,
        "conditions",
        as_of_at=AS_OF,
    )
    assert projection.unresolved_count == 1
    assert {
        candidate["source_system"]
        for candidate in projection.groups[0]["candidates"]
    } == {"clinician", "patient"}
