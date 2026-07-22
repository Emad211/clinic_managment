"""Verification rank must follow concept and interval certainty for item facts."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_reconciliation_repo import (
    ClinicalReconciliationRepository,
)
from src.adapters.sqlite.patients_repo import PatientRepository
from src.domain.clinical_engine import VerificationStatus
from src.services.clinical_engine.fact_builder import FactBuilder


AS_OF = datetime(2026, 7, 22, 12, 0, 0)


@pytest.fixture()
def verification_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "fact-verification.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "fact-verification-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def test_unmapped_medication_class_is_never_a_confirmed_item_fact(
    verification_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by, enrolled_at)
               VALUES ('VERIFY01', 'Verification Patient', 'pytest',
                       '2026-01-01 09:00:00')"""
        ).lastrowid
    )
    db.commit()
    PatientRepository().add_medication(
        patient_id,
        drug_name="Unmapped handwritten metformin",
        dose="500 mg",
        schedule="روزانه",
        start_date="2025-01-01",
        refill_due_date=None,
        notes=None,
        drug_class="metformin",
        created_by="doctor",
    )
    ClinicalReconciliationRepository().record(
        patient_link_id=patient_id,
        collection_key="medications",
        completeness="complete",
        actor_username="doctor",
        actor_user_id=None,
        source="clinician",
        patient_confirmed=True,
        reconciled_at=AS_OF,
    )

    snapshot = FactBuilder().build(patient_id, as_of_at=AS_OF)
    aggregate = next(
        fact for fact in snapshot.facts
        if fact.key == "medication.classes"
    )
    specific = next(
        fact for fact in snapshot.facts
        if fact.key == "medication.metformin"
    )

    assert aggregate.verification is VerificationStatus.PROVISIONAL
    assert specific.verification is VerificationStatus.PROVISIONAL
    assert "UNMAPPED_MEDICATION_CONCEPT" in specific.warnings


def test_historical_interval_approximation_downgrades_specific_item(
    verification_app,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by, enrolled_at)
               VALUES ('VERIFY02', 'Historical Patient', 'pytest',
                       '2026-01-01 09:00:00')"""
        ).lastrowid
    )
    db.execute(
        """INSERT INTO patient_conditions
           (patient_link_id, condition_id, onset_date, diagnosed_at,
            is_active)
           VALUES (?, 1, NULL, NULL, 1)""",
        (patient_id,),
    )
    db.commit()

    snapshot = FactBuilder().build(patient_id, as_of_at=AS_OF)
    diabetes = next(
        fact for fact in snapshot.facts
        if fact.key == "condition.diabetes"
    )

    assert diabetes.verification is VerificationStatus.PROVISIONAL
    assert "HISTORICAL_INTERVAL_APPROXIMATION" in diabetes.warnings
