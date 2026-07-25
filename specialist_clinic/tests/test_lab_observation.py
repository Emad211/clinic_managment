"""Adversarial tests for the canonical lab/vital observation channel.

``vital_readings.type`` and ``lab_results.test_key`` are two capture channels for one
canonical key vocabulary.  The supported contract covers ordering, provenance,
missing-key visibility and Clinical Engine v2 snapshot production; retired v1 follow-up
helpers are not part of it.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))


@pytest.fixture()
def lab_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "lab-observation.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "lab-observation-test",
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
                enrolled_at)
               VALUES (?, ?, 'female', '1980-01-01', 'pytest',
                       '2026-01-01 09:00:00')""",
            (national_id, f"Lab Patient {national_id}"),
        ).lastrowid
    )
    db.commit()
    return patient_id


def _vital(patient_id: int, value: float, at: str):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source,
            recorded_by)
           VALUES (?, 'hba1c', ?, '%', ?, 'clinic', 'nurse')""",
        (patient_id, value, at),
    )
    db.commit()


def _lab(
    patient_id: int,
    value: float,
    at: str,
    *,
    test_key: str | None = "hba1c",
):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        """INSERT INTO lab_results
           (patient_link_id, test_name, test_key, value, unit, taken_at,
            recorded_by)
           VALUES (?, 'HbA1c', ?, ?, '%', ?, 'laboratory')""",
        (patient_id, test_key, value, at),
    )
    db.commit()


def test_lab_only_value_is_latest_with_laboratory_provenance(lab_app):
    from src.adapters.sqlite.vitals_repo import VitalsRepository
    from src.services.clinical_engine.fact_builder import FactBuilder

    patient_id = _patient("LAB001")
    _lab(patient_id, 7.2, "2026-06-15 08:00:00")

    latest = VitalsRepository().latest_by_type(patient_id)
    snapshot = FactBuilder().build(
        patient_id,
        as_of_at=datetime(2026, 7, 22, 12, 0, 0),
    )
    fact = next(
        item
        for item in snapshot.facts
        if item.key == "observation.hba1c"
    )

    assert latest["hba1c"]["value"] == pytest.approx(7.2)
    assert latest["hba1c"]["source"] == "lab"
    assert fact.value == pytest.approx(7.2)
    assert fact.source.system == "laboratory"
    assert fact.verification.value == "CONFIRMED"


def test_latest_timestamp_wins_across_channels(lab_app):
    from src.adapters.sqlite.vitals_repo import VitalsRepository

    patient_id = _patient("LAB002")
    _vital(patient_id, 8.5, "2026-01-01 08:00:00")
    _lab(patient_id, 7.2, "2026-06-15 08:00:00")
    latest = VitalsRepository().latest_by_type(patient_id)
    assert latest["hba1c"]["value"] == pytest.approx(7.2)
    assert latest["hba1c"]["source"] == "lab"

    _vital(patient_id, 6.9, "2026-07-01 08:00:00")
    latest = VitalsRepository().latest_by_type(patient_id)
    assert latest["hba1c"]["value"] == pytest.approx(6.9)
    assert latest["hba1c"]["source"] != "lab"


def test_equal_timestamp_has_stable_two_channel_series(lab_app):
    from src.adapters.sqlite.vitals_repo import VitalsRepository
    from src.services.clinical_engine.fact_builder import FactBuilder

    patient_id = _patient("LAB003")
    timestamp = "2026-06-15 08:00:00"
    _vital(patient_id, 8.0, timestamp)
    _lab(patient_id, 7.0, timestamp)

    series = VitalsRepository().get_readings_canonical(
        patient_id,
        "hba1c",
        limit=200,
    )
    snapshot = FactBuilder().build(
        patient_id,
        as_of_at=datetime(2026, 7, 22, 12, 0, 0),
    )
    facts = [
        fact
        for fact in snapshot.facts
        if fact.key == "observation.hba1c"
    ]

    assert len(series) == 2
    assert [row["value"] for row in series] == [8.0, 7.0]
    assert [fact.value for fact in facts] == [8.0, 7.0]
    assert facts[0].source.system == "clinician"
    assert facts[1].source.system == "laboratory"


def test_lab_without_canonical_key_is_retained_but_not_consumed_as_fact(lab_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.vitals_repo import VitalsRepository
    from src.services.clinical_engine.fact_builder import FactBuilder

    patient_id = _patient("LAB004")
    _lab(
        patient_id,
        9.1,
        "2026-06-15 08:00:00",
        test_key=None,
    )

    row = get_db().execute(
        "SELECT * FROM lab_results WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()
    latest = VitalsRepository().latest_by_type(patient_id)
    snapshot = FactBuilder().build(
        patient_id,
        as_of_at=datetime(2026, 7, 22, 12, 0, 0),
    )

    assert row["value"] == pytest.approx(9.1)
    assert row["test_key"] is None
    assert "hba1c" not in latest
    assert not any(
        fact.key == "observation.hba1c"
        for fact in snapshot.facts
    )


def test_future_lab_is_excluded_by_fixed_as_of_snapshot(lab_app):
    from src.services.clinical_engine.fact_builder import FactBuilder

    patient_id = _patient("LAB005")
    _lab(patient_id, 7.0, "2026-06-15 08:00:00")
    _lab(patient_id, 99.0, "2027-01-01 08:00:00")

    snapshot = FactBuilder().build(
        patient_id,
        as_of_at=datetime(2026, 7, 22, 12, 0, 0),
    )
    facts = [
        fact
        for fact in snapshot.facts
        if fact.key == "observation.hba1c"
    ]
    present = [fact for fact in facts if fact.status.value == "PRESENT"]
    unusable = [fact for fact in facts if fact.status.value == "UNKNOWN"]

    assert [fact.value for fact in present] == [7.0]
    assert len(unusable) == 1
    assert "OUTLIER" in unusable[0].warnings


def test_add_lab_repository_persists_test_key_and_reference_range(lab_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.vitals_repo import VitalsRepository

    patient_id = _patient("LAB006")
    VitalsRepository().add_lab(
        patient_id,
        test_name="eGFR",
        test_key="egfr",
        value=44,
        unit="mL/min/1.73m2",
        ref_low=60,
        taken_at="2026-06-15 08:00:00",
        recorded_by="lab-user",
    )
    row = get_db().execute(
        "SELECT * FROM lab_results WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()

    assert row["test_key"] == "egfr"
    assert row["value"] == pytest.approx(44)
    assert row["ref_low"] == pytest.approx(60)
    assert row["recorded_by"] == "lab-user"
