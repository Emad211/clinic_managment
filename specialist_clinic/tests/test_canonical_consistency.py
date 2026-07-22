"""Canonical observation consistency across supported current consumers.

A lab-only observation must have the same value, timestamp and ordering in:

- ``VitalsRepository`` canonical series/latest projection
- descriptive ``VitalsService`` and ``AnalyticsService``
- Clinical Engine v2 ``FactSnapshot``

The retired v1 rule/follow-up engines are intentionally not part of this contract.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPECIALIST_ROOT = REPOSITORY_ROOT / "specialist_clinic"
REAL_ACCOUNTING_DB = REPOSITORY_ROOT / "webapp" / "clinic_new.db"
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))


@pytest.fixture()
def canonical_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "canonical.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "canonical-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(national_id: str) -> int:
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, gender, birthdate, enrolled_by,
                enrolled_at, updated_at)
               VALUES (?, ?, 'female', '1980-01-01', 'pytest',
                       '2026-01-01 09:00:00', '2026-01-01 09:00:00')""",
            (national_id, f"Canonical {national_id}"),
        ).lastrowid
    )
    db.commit()
    return patient_id


def _lab(
    patient_id: int,
    key: str,
    value: float,
    taken_at: str,
    *,
    unit: str = "%",
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        """INSERT INTO lab_results
           (patient_link_id, test_name, test_key, value, unit, taken_at,
            recorded_by)
           VALUES (?, ?, ?, ?, ?, ?, 'lab')""",
        (
            patient_id,
            f"lab-{key}",
            key,
            value,
            unit,
            taken_at,
        ),
    )
    db.commit()


def _vital(
    patient_id: int,
    key: str,
    value: float,
    measured_at: str,
    *,
    unit: str,
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source,
            recorded_by)
           VALUES (?, ?, ?, ?, ?, 'clinic', 'nurse')""",
        (patient_id, key, value, unit, measured_at),
    )
    db.commit()


def _hba1c_danger() -> float:
    from src.adapters.sqlite.core import get_db

    row = get_db().execute(
        "SELECT danger FROM clinical_indicators WHERE key='hba1c'"
    ).fetchone()
    return float(row["danger"] if row and row["danger"] is not None else 8)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_lab_only_hba1c_agrees_across_current_consumers(canonical_app):
    from src.adapters.sqlite.vitals_repo import VitalsRepository
    from src.services.analytics_service import AnalyticsService
    from src.services.clinical_engine.fact_builder import FactBuilder
    from src.services.vitals_service import VitalsService
    from datetime import datetime

    patient_id = _patient("CANON001")
    value = _hba1c_danger() + 0.5
    _lab(
        patient_id,
        "hba1c",
        value,
        "2026-06-01 08:00:00",
    )

    repository = VitalsRepository()
    latest = repository.latest_by_type(patient_id)
    control = VitalsService(repo=repository).control_status(patient_id)
    analytics = AnalyticsService().patient_analytics(patient_id)
    snapshot = FactBuilder().build(
        patient_id,
        as_of_at=datetime(2026, 7, 22, 12, 0, 0),
    )

    assert latest["hba1c"]["value"] == pytest.approx(value)
    assert latest["hba1c"]["source"] == "lab"
    assert control["status"] == "uncontrolled"
    tile = next(
        item
        for item in analytics["indicators"]
        if item["key"] == "hba1c"
    )
    assert tile["latest"] == pytest.approx(value)
    assert tile["level"] == "danger"
    assert value in analytics["charts"]["hba1c"]["values"]
    fact = next(
        item
        for item in snapshot.facts
        if item.key == "observation.hba1c"
    )
    assert fact.value == pytest.approx(value)
    assert fact.source.system == "laboratory"
    assert fact.effective_at.isoformat().startswith("2026-06-01T08:00:00")


def test_canonical_series_unions_vital_and_lab_in_ascending_order(
    canonical_app,
):
    from src.adapters.sqlite.vitals_repo import VitalsRepository

    patient_id = _patient("CANON002")
    _vital(
        patient_id,
        "hba1c",
        7.5,
        "2026-01-10 08:00:00",
        unit="%",
    )
    _lab(
        patient_id,
        "hba1c",
        8.5,
        "2026-06-10 08:00:00",
    )

    series = VitalsRepository().get_readings_canonical(
        patient_id,
        "hba1c",
        limit=200,
    )
    assert [row["value"] for row in series] == [7.5, 8.5]
    assert series[0]["source"] != "lab"
    assert series[1]["source"] == "lab"


def test_vital_only_and_empty_keys_keep_previous_repository_contract(
    canonical_app,
):
    from src.adapters.sqlite.vitals_repo import VitalsRepository

    patient_id = _patient("CANON003")
    _vital(
        patient_id,
        "bp_systolic",
        128,
        "2026-05-01 08:00:00",
        unit="mmHg",
    )
    _vital(
        patient_id,
        "bp_systolic",
        132,
        "2026-06-01 08:00:00",
        unit="mmHg",
    )
    repository = VitalsRepository()
    series = repository.get_readings_canonical(
        patient_id,
        "bp_systolic",
        limit=200,
    )

    assert [row["value"] for row in series] == [128, 132]
    assert all(row["source"] != "lab" for row in series)
    assert repository.get_readings_canonical(
        patient_id,
        "ldl",
        limit=200,
    ) == []


def test_medication_effect_uses_lab_only_pre_and_post_values(canonical_app):
    from src.adapters.sqlite.core import get_db
    from src.services.analytics_service import AnalyticsService

    patient_id = _patient("CANON004")
    db = get_db()
    medication_id = int(
        db.execute(
            """INSERT INTO patient_medications
               (patient_link_id, drug_name, dose, start_date, is_active)
               VALUES (?, 'متفورمین', '500mg', '2026-04-01', 1)""",
            (patient_id,),
        ).lastrowid
    )
    db.commit()
    _lab(
        patient_id,
        "hba1c",
        8.5,
        "2026-02-01 08:00:00",
    )
    _lab(
        patient_id,
        "hba1c",
        7.2,
        "2026-06-01 08:00:00",
    )

    result = AnalyticsService().medication_effect(
        patient_id,
        medication_id,
        "hba1c",
        window_days=90,
    )
    assert result["ok"] is True
    assert result["pre"] == pytest.approx(8.5)
    assert result["post"] == pytest.approx(7.2)


@pytest.mark.skipif(
    not REAL_ACCOUNTING_DB.exists(),
    reason="committed accounting seed DB is absent",
)
def test_canonical_reads_never_mutate_accounting_database(canonical_app):
    from src.adapters.sqlite.vitals_repo import VitalsRepository

    before = _sha256(REAL_ACCOUNTING_DB)
    patient_id = _patient("CANON005")
    _lab(
        patient_id,
        "hba1c",
        7.4,
        "2026-06-01 08:00:00",
    )
    VitalsRepository().get_readings_canonical(
        patient_id,
        "hba1c",
    )
    VitalsRepository().latest_by_type(patient_id)
    assert _sha256(REAL_ACCOUNTING_DB) == before
