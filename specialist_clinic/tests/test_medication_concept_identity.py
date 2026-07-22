"""Canonical medication identity regression tests."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))


@pytest.fixture()
def concept_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "medication-concepts.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "medication-concept-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db) -> int:
    cursor = db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, enrolled_by, enrolled_at)
           VALUES ('CONCEPT01', 'Concept Patient', 'pytest',
                   '2026-07-22 09:00:00')"""
    )
    db.commit()
    return int(cursor.lastrowid)


def test_unique_exact_name_and_class_resolve_to_catalog_concept(concept_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.patients_repo import PatientRepository

    db = get_db()
    patient_id = _patient(db)
    catalog = db.execute(
        """SELECT id, generic_fa, drug_class_key FROM drug_catalog
           WHERE is_active=1 AND drug_class_key IS NOT NULL
           ORDER BY id LIMIT 1"""
    ).fetchone()
    assert catalog is not None

    medication_id = PatientRepository().add_medication(
        patient_id,
        drug_name=catalog["generic_fa"],
        dose="دوز آزمون",
        schedule="روزانه",
        start_date="2026-07-22",
        refill_due_date=None,
        notes=None,
        drug_class=catalog["drug_class_key"],
        created_by="doctor",
    )
    medication = db.execute(
        "SELECT * FROM patient_medications WHERE id=?",
        (medication_id,),
    ).fetchone()
    assert medication["drug_catalog_id"] == catalog["id"]


def test_explicit_catalog_id_canonicalizes_name_and_class(concept_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.patients_repo import PatientRepository

    db = get_db()
    patient_id = _patient(db)
    catalog = db.execute(
        """SELECT id, generic_fa, drug_class_key FROM drug_catalog
           WHERE is_active=1 AND drug_class_key IS NOT NULL
           ORDER BY id LIMIT 1"""
    ).fetchone()
    medication_id = PatientRepository().add_medication(
        patient_id,
        drug_name="نام اشتباه فرم",
        dose=None,
        schedule=None,
        start_date="2026-07-22",
        refill_due_date=None,
        notes=None,
        drug_class="wrong-class",
        drug_catalog_id=int(catalog["id"]),
        created_by="doctor",
    )
    medication = db.execute(
        "SELECT drug_name, drug_class, drug_catalog_id "
        "FROM patient_medications WHERE id=?",
        (medication_id,),
    ).fetchone()
    assert dict(medication) == {
        "drug_name": catalog["generic_fa"],
        "drug_class": catalog["drug_class_key"],
        "drug_catalog_id": catalog["id"],
    }


def test_database_rejects_unknown_or_inactive_medication_concept(concept_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    with pytest.raises(sqlite3.IntegrityError, match="active drug catalog"):
        db.execute(
            """INSERT INTO patient_medications
               (patient_link_id, drug_name, drug_class, drug_catalog_id,
                start_date, is_active)
               VALUES (?, 'Unknown', 'unknown', 999999999, '2026-07-22', 1)""",
            (patient_id,),
        )
    db.rollback()
