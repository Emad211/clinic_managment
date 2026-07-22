"""Shared-catalog invalidation and non-clinical update regression tests."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_engine_runtime_schema import ensure_runtime_schema
from src.services.clinical_engine.fact_builder import FactBuilder


AS_OF = datetime(2026, 7, 22, 12, 0, 0)


@pytest.fixture()
def catalog_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "catalog-revision.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "catalog-revision-test",
    })
    context = app.app_context()
    context.push()
    ensure_runtime_schema(core.get_db())
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id: str) -> int:
    patient_id = int(db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, gender, birthdate, address, enrolled_by,
            enrolled_at, updated_at)
           VALUES (?, ?, 'female', '1988-08-01', 'تهران', 'pytest',
                   '2026-01-01 09:00:00', '2026-01-01 09:00:00')""",
        (national_id, f"Patient {national_id}"),
    ).lastrowid)
    db.commit()
    return patient_id


def _revision(db, patient_id: int) -> int:
    return int(db.execute(
        "SELECT clinical_data_revision FROM patient_links WHERE id=?",
        (patient_id,),
    ).fetchone()["clinical_data_revision"])


def test_contact_edit_does_not_change_clinical_snapshot_or_revision(catalog_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db, "CAT0001")
    before = FactBuilder().build(patient_id, as_of_at=AS_OF)

    db.execute(
        """UPDATE patient_links
           SET address='کرج', phone_number='09120000000',
               updated_at='2026-07-22 11:00:00'
           WHERE id=?""",
        (patient_id,),
    )
    db.commit()
    after = FactBuilder().build(patient_id, as_of_at=AS_OF)

    assert _revision(db, patient_id) == 0
    assert after.clinical_data_revision == before.clinical_data_revision == 0
    assert after.content_hash == before.content_hash


def test_flag_catalog_insert_update_delete_invalidates_every_patient(catalog_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    first = _patient(db, "CAT0002")
    second = _patient(db, "CAT0003")

    flag_id = int(db.execute(
        """INSERT INTO flag_catalog
           (flag_key, label, flag_type, category, is_active)
           VALUES ('runtime_catalog_flag', 'پرچم آزمون runtime', 'bool', 'other', 1)"""
    ).lastrowid)
    db.commit()
    assert (_revision(db, first), _revision(db, second)) == (1, 1)

    db.execute(
        "UPDATE flag_catalog SET flag_type='text' WHERE id=?",
        (flag_id,),
    )
    db.commit()
    assert (_revision(db, first), _revision(db, second)) == (2, 2)

    db.execute("DELETE FROM flag_catalog WHERE id=?", (flag_id,))
    db.commit()
    assert (_revision(db, first), _revision(db, second)) == (3, 3)


def test_condition_code_change_invalidates_only_linked_active_patients(catalog_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    linked = _patient(db, "CAT0004")
    unrelated = _patient(db, "CAT0005")
    db.execute(
        """INSERT INTO patient_conditions
           (patient_link_id, condition_id, onset_date, is_active)
           VALUES (?, 1, '2020-01-01', 1)""",
        (linked,),
    )
    db.commit()
    linked_before = _revision(db, linked)
    unrelated_before = _revision(db, unrelated)

    db.execute("UPDATE conditions SET code='diabetes_runtime_test' WHERE id=1")
    db.commit()

    assert _revision(db, linked) == linked_before + 1
    assert _revision(db, unrelated) == unrelated_before
