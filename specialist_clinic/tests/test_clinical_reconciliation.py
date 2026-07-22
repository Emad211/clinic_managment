"""Clinical collection reconciliation and historical-as-of regression tests."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_reconciliation_repo import (
    ClinicalReconciliationRepository,
)
from src.adapters.sqlite.patients_repo import PatientRepository
from src.domain.clinical_engine import (
    FactStatus,
    FreshnessStatus,
    VerificationStatus,
)
from src.services.clinical_engine.fact_builder import FactBuilder
from src.services.clinical_reconciliation_service import (
    ClinicalReconciliationService,
)


AS_OF = datetime(2026, 7, 22, 12, 0, 0)


@pytest.fixture()
def reconciliation_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "reconciliation.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "reconciliation-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id: str) -> int:
    cursor = db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, gender, birthdate, enrolled_by, enrolled_at)
           VALUES (?, ?, 'female', '1980-01-02', 'pytest',
                   '2026-01-01 09:00:00')""",
        (national_id, f"Patient {national_id}"),
    )
    db.commit()
    return int(cursor.lastrowid)


def _catalog_medication(db, class_key: str = "metformin") -> dict:
    row = db.execute(
        """SELECT id, generic_fa, drug_class_key FROM drug_catalog
           WHERE is_active=1 AND drug_class_key=?
           ORDER BY id LIMIT 1""",
        (class_key,),
    ).fetchone()
    assert row is not None
    return dict(row)


def _fact(snapshot, key: str):
    matches = [fact for fact in snapshot.facts if fact.key == key]
    assert len(matches) == 1
    return matches[0]


def _record(
    patient_id: int,
    collection_key: str,
    *,
    completeness: str = "complete",
    at: datetime = AS_OF,
    note: str | None = None,
):
    return ClinicalReconciliationRepository().record(
        patient_link_id=patient_id,
        collection_key=collection_key,
        completeness=completeness,
        actor_username="doctor",
        actor_user_id=None,
        source="clinician",
        patient_confirmed=True,
        reconciled_at=at,
        note=note,
    )


def test_empty_database_is_unknown_until_absence_is_explicitly_reviewed(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "REC0001")

    before = FactBuilder().build(patient_id, as_of_at=AS_OF)
    for key in (
        "condition.codes",
        "medication.classes",
        "allergy.substances",
    ):
        fact = _fact(before, key)
        assert fact.status is FactStatus.UNKNOWN
        assert fact.verification is VerificationStatus.UNVERIFIED
        assert "UNRECONCILED_COLLECTION" in fact.warnings

    revision_before = int(
        db.execute(
            "SELECT clinical_data_revision FROM patient_links WHERE id=?",
            (patient_id,),
        ).fetchone()["clinical_data_revision"]
    )
    _record(patient_id, "medications")
    revision_after = int(
        db.execute(
            "SELECT clinical_data_revision FROM patient_links WHERE id=?",
            (patient_id,),
        ).fetchone()["clinical_data_revision"]
    )

    after = FactBuilder().build(patient_id, as_of_at=AS_OF)
    medications = _fact(after, "medication.classes")
    assert medications.status is FactStatus.ABSENT
    assert medications.value is None
    assert medications.verification is VerificationStatus.CONFIRMED
    assert medications.freshness is FreshnessStatus.FRESH
    assert revision_after == revision_before + 1


def test_complete_canonical_collection_becomes_stale_after_source_change(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "REC0002")
    catalog = _catalog_medication(db)
    repo = PatientRepository()
    repo.add_medication(
        patient_id,
        drug_name=catalog["generic_fa"],
        dose="500 mg",
        schedule="روزانه",
        start_date="2025-01-01",
        refill_due_date=None,
        notes=None,
        drug_class=catalog["drug_class_key"],
        drug_catalog_id=int(catalog["id"]),
        created_by="doctor",
    )
    _record(patient_id, "medications")

    confirmed = _fact(
        FactBuilder().build(patient_id, as_of_at=AS_OF),
        "medication.classes",
    )
    assert confirmed.status is FactStatus.PRESENT
    assert confirmed.value == ["metformin"]
    assert confirmed.verification is VerificationStatus.CONFIRMED
    assert confirmed.freshness is FreshnessStatus.FRESH

    repo.change_dose(
        repo.get_medications(patient_id)[0]["id"],
        "1000 mg",
        change_date="2026-07-22",
        created_by="doctor",
        patient_link_id=patient_id,
    )
    stale = _fact(
        FactBuilder().build(patient_id, as_of_at=AS_OF),
        "medication.classes",
    )
    assert stale.status is FactStatus.PRESENT
    assert stale.verification is VerificationStatus.UNVERIFIED
    assert stale.freshness is FreshnessStatus.STALE
    assert "COLLECTION_CHANGED_AFTER_RECONCILIATION" in stale.warnings


def test_complete_review_does_not_confirm_unmapped_medication_identity(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "REC0003")
    PatientRepository().add_medication(
        patient_id,
        drug_name="Metformin handwritten legacy row",
        dose="500 mg",
        schedule="روزانه",
        start_date="2025-01-01",
        refill_due_date=None,
        notes="عمداً خارج از drug catalog",
        drug_class="metformin",
        created_by="doctor",
    )
    _record(patient_id, "medications")

    projection = ClinicalReconciliationRepository().projection(
        patient_id,
        "medications",
        as_of_at=AS_OF,
    )
    medication_fact = _fact(
        FactBuilder().build(patient_id, as_of_at=AS_OF),
        "medication.classes",
    )

    assert projection.state == "mapping_incomplete"
    assert projection.mapping_complete is False
    assert projection.status is FactStatus.PRESENT
    assert projection.verification is VerificationStatus.PROVISIONAL
    assert projection.freshness is FreshnessStatus.FRESH
    assert projection.values == ("metformin",)
    assert "UNMAPPED_MEDICATION_CONCEPT" in projection.warnings
    assert "CANONICAL_MAPPING_INCOMPLETE" in projection.warnings
    assert medication_fact.status is FactStatus.PRESENT
    assert medication_fact.value == ["metformin"]
    assert medication_fact.verification is VerificationStatus.PROVISIONAL


def test_partial_review_never_claims_confirmed_collection(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "REC0004")
    db.execute(
        """INSERT INTO patient_conditions
           (patient_link_id, condition_id, onset_date, diagnosed_at)
           VALUES (?, 1, '2020-01-01', '2020-01-01')""",
        (patient_id,),
    )
    db.commit()
    _record(
        patient_id,
        "conditions",
        completeness="partial",
        note="سوابق بیمارستانی هنوز دریافت نشده است.",
    )

    condition_list = _fact(
        FactBuilder().build(patient_id, as_of_at=AS_OF),
        "condition.codes",
    )
    assert condition_list.status is FactStatus.PRESENT
    assert condition_list.value == ["diabetes"]
    assert condition_list.verification is VerificationStatus.PROVISIONAL
    assert "PARTIAL_RECONCILIATION" in condition_list.warnings


def test_known_item_presence_is_independent_of_collection_completeness(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "REC0005")
    db.execute(
        """INSERT INTO patient_conditions
           (patient_link_id, condition_id, onset_date, diagnosed_at)
           VALUES (?, 1, '2020-01-01', '2020-01-01')""",
        (patient_id,),
    )
    db.commit()

    snapshot = FactBuilder().build(patient_id, as_of_at=AS_OF)
    collection = _fact(snapshot, "condition.codes")
    specific = _fact(snapshot, "condition.diabetes")
    assert collection.verification is VerificationStatus.UNVERIFIED
    assert specific.status is FactStatus.PRESENT
    assert specific.verification is VerificationStatus.CONFIRMED
    assert "UNRECONCILED_COLLECTION" in specific.warnings


def test_reconciliation_events_are_append_only_and_scope_bound(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    first = _patient(db, "REC0006")
    second = _patient(db, "REC0007")
    event = _record(first, "allergies")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE clinical_reconciliation_events SET note='tampered' WHERE id=?",
            (event["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "DELETE FROM clinical_reconciliation_events WHERE id=?",
            (event["id"],),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="supersession"):
        db.execute(
            """INSERT INTO clinical_reconciliation_events
               (patient_link_id, collection_key, completeness, item_count,
                content_hash, source, actor_username, reconciled_at,
                supersedes_event_id)
               VALUES (?, 'allergies', 'complete', 0, ?, 'clinician',
                       'doctor', '2026-07-22 13:00:00', ?)""",
            (second, "0" * 64, event["id"]),
        )
    db.rollback()


def test_historical_medication_projection_uses_event_dose_and_effective_stop(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "REC0008")
    catalog = _catalog_medication(db)
    repo = PatientRepository()
    med_id = repo.add_medication(
        patient_id,
        drug_name=catalog["generic_fa"],
        dose="500 mg",
        schedule="روزانه",
        start_date="2024-01-01",
        refill_due_date=None,
        notes=None,
        drug_class=catalog["drug_class_key"],
        drug_catalog_id=int(catalog["id"]),
        created_by="doctor",
    )
    repo.change_dose(
        med_id,
        "1000 mg",
        change_date="2025-01-01",
        created_by="doctor",
        patient_link_id=patient_id,
    )
    repo.stop_medication(
        med_id,
        end_date="2026-06-01",
        created_by="doctor",
        patient_link_id=patient_id,
    )

    historical_at = datetime(2025, 6, 1, 12, 0, 0)
    historical_event = _record(
        patient_id,
        "medications",
        at=historical_at,
    )
    historical = ClinicalReconciliationRepository().projection(
        patient_id,
        "medications",
        as_of_at=historical_at,
    )
    assert historical.state == "confirmed_present"
    assert historical.items[0]["dose"] == "1000 mg"
    assert historical.items[0]["start_date"] == "2024-01-01"
    assert historical.items[0]["drug_catalog_id"] == catalog["id"]
    assert historical.reconciliation_event["id"] == historical_event["id"]

    after_stop = ClinicalReconciliationRepository().projection(
        patient_id,
        "medications",
        as_of_at=datetime(2026, 7, 1, 12, 0, 0),
    )
    assert after_stop.state == "stale"
    assert after_stop.status is FactStatus.UNKNOWN

    _record(
        patient_id,
        "medications",
        at=datetime(2026, 7, 1, 12, 0, 0),
    )
    confirmed_absence = ClinicalReconciliationRepository().projection(
        patient_id,
        "medications",
        as_of_at=datetime(2026, 7, 1, 12, 0, 0),
    )
    assert confirmed_absence.state == "confirmed_absent"
    assert confirmed_absence.status is FactStatus.ABSENT


def test_missing_interval_timestamp_is_disclosed_in_projection(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "REC0009")
    db.execute(
        """INSERT INTO allergies
           (patient_link_id, substance, reaction, severity, is_active,
            created_at)
           VALUES (?, 'Legacy allergen', 'unknown', 'unknown', 1, NULL)""",
        (patient_id,),
    )
    db.commit()

    projection = ClinicalReconciliationRepository().projection(
        patient_id,
        "allergies",
        as_of_at=AS_OF,
    )
    assert projection.status is FactStatus.PRESENT
    assert "HISTORICAL_INTERVAL_APPROXIMATION" in projection.warnings


def test_soft_resolution_preserves_history_and_checks_patient_ownership(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    first = _patient(db, "REC0010")
    second = _patient(db, "REC0011")
    repo = PatientRepository()
    condition_id = repo.add_condition(first, 1, onset_date="2020-01-01")
    allergy_id = repo.add_allergy(
        first,
        substance="Penicillin",
        reaction="rash",
        severity="moderate",
    )

    with pytest.raises(LookupError, match="does not belong"):
        repo.remove_condition(condition_id, patient_link_id=second)
    with pytest.raises(LookupError, match="does not belong"):
        repo.delete_allergy(allergy_id, patient_link_id=second)

    assert repo.remove_condition(
        condition_id,
        patient_link_id=first,
        resolved_at="2025-01-01",
    )
    assert repo.delete_allergy(
        allergy_id,
        patient_link_id=first,
        resolved_at="2025-01-01",
    )
    condition = db.execute(
        "SELECT is_active, resolved_at FROM patient_conditions WHERE id=?",
        (condition_id,),
    ).fetchone()
    allergy = db.execute(
        "SELECT is_active, resolved_at FROM allergies WHERE id=?",
        (allergy_id,),
    ).fetchone()
    assert dict(condition) == {
        "is_active": 0,
        "resolved_at": "2025-01-01",
    }
    assert dict(allergy) == {
        "is_active": 0,
        "resolved_at": "2025-01-01",
    }


def test_service_requires_attestation_and_reason_for_partial_review(
    reconciliation_app,
):
    from src.adapters.sqlite.core import get_db

    patient_id = _patient(get_db(), "REC0012")
    service = ClinicalReconciliationService(clock=lambda: AS_OF)
    with pytest.raises(ValueError, match="تأیید"):
        service.record(
            patient_link_id=patient_id,
            collection_key="allergies",
            completeness="complete",
            actor_username="doctor",
            actor_user_id=None,
            attested=False,
        )
    with pytest.raises(ValueError, match="مرور ناقص"):
        service.record(
            patient_link_id=patient_id,
            collection_key="allergies",
            completeness="partial",
            actor_username="doctor",
            actor_user_id=None,
            attested=True,
            note="",
        )
