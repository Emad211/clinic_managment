"""Canonical observation consistency across supported current consumers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
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
    # Descriptive analytics intentionally scopes HbA1c indicators to a diabetes
    # problem list. The canonical channel test therefore supplies that real context
    # instead of expecting disease-specific analytics for an unclassified patient.
    db.execute(
        """INSERT INTO patient_conditions
           (patient_link_id, condition_id, onset_date, diagnosed_at)
           VALUES (?, 1, '2020-01-01', '2020-01-01')""",
        (patient_id,),
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
        (patient_id, f"lab-{key}", key, value, unit, taken_at),
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


def test_lab_only_hba1c_agrees_across_current_consumers(canonical_app):
    from src.adapters.sqlite.vitals_repo import VitalsRepository
    from src.services.analytics_service import AnalyticsService
    from src.services.clinical_engine.fact_builder import FactBuilder

    patient_id = _patient("CANON001")
    _lab(patient_id, "hba1c", 8.5, "2026-06-01 08:00:00")

    repository = VitalsRepository()
    latest = repository.latest_by_type(patient_id)
    analytics = AnalyticsService().patient_analytics(patient_id)
    snapshot = FactBuilder().build(
        patient_id,
        as_of_at=datetime(2026, 7, 22, 12, 0, 0),
    )

    assert latest["hba1c"]["value"] == pytest.approx(8.5)
    assert latest["hba1c"]["source"] == "lab"
    tile = next(
        item
        for item in analytics["indicators"]
        if item["key"] == "hba1c"
    )
    assert tile["latest"] == pytest.approx(8.5)
    assert "level" not in tile
    assert analytics["projection_policy"] == "DESCRIPTIVE_ONLY"
    assert analytics["charts"]["hba1c"]["values"] == [8.5]
    fact = next(
        item
        for item in snapshot.facts
        if item.key == "observation.hba1c"
    )
    assert fact.value == pytest.approx(8.5)
    assert fact.source.system == "laboratory"


def test_series_unions_vital_and_lab_in_ascending_order(canonical_app):
    from src.adapters.sqlite.vitals_repo import VitalsRepository

    patient_id = _patient("CANON002")
    _vital(
        patient_id,
        "hba1c",
        7.5,
        "2026-01-10 08:00:00",
        unit="%",
    )
    _lab(patient_id, "hba1c", 8.5, "2026-06-10 08:00:00")

    series = VitalsRepository().get_readings_canonical(
        patient_id,
        "hba1c",
        limit=200,
    )
    assert [row["value"] for row in series] == [7.5, 8.5]
    assert series[0]["source"] != "lab"
    assert series[1]["source"] == "lab"


def test_vital_only_and_empty_keys_keep_repository_contract(canonical_app):
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
    assert [
        row["value"]
        for row in repository.get_readings_canonical(
            patient_id,
            "bp_systolic",
            limit=200,
        )
    ] == [128, 132]
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
    _lab(patient_id, "hba1c", 8.5, "2026-02-01 08:00:00")
    _lab(patient_id, "hba1c", 7.2, "2026-06-01 08:00:00")

    result = AnalyticsService().medication_effect(
        patient_id,
        medication_id,
        "hba1c",
        window_days=90,
    )
    assert result["ok"] is True
    assert result["pre"] == pytest.approx(8.5)
    assert result["post"] == pytest.approx(7.2)
