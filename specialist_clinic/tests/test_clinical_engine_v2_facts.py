"""Deterministic canonical facts and exact shadow/selected execution."""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import sys

import pytest
from jsonschema import Draft202012Validator, FormatChecker


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
TESTS_ROOT = str(SPECIALIST_ROOT / "tests")
if TESTS_ROOT not in sys.path:
    sys.path.insert(0, TESTS_ROOT)

from clinical_engine_current_test_support import install_sealed_rollout
from src.adapters.sqlite.clinical_engine_fact_repo import (
    ClinicalEngineFactRepository,
)
from src.domain.clinical_engine import FactStatus
from src.services.clinical_engine.fact_builder import (
    ENGINE_VERSION,
    FactBuilder,
    ShadowFactCapture,
    snapshot_payload,
)
from src.services.clinical_engine.legacy_adapter import (
    age_on,
    normalize_birthdate,
)
from src.services.clinical_engine.reconciled_adapter import (
    ReconciledFactBundleAdapter,
)


AS_OF = datetime(2026, 7, 21, 12, 0, 0)


@pytest.fixture()
def facts_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "facts.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "facts-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _insert_patient(
    db,
    national_id="FACT0001",
    birthdate="1988-08-01",
):
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, gender, birthdate, enrolled_by,
                enrolled_at, updated_at)
               VALUES (?, 'Fact Patient', 'female', ?, 'pytest', ?, ?)""",
            (
                national_id,
                birthdate,
                "2026-01-01 09:00:00",
                "2026-01-01 09:00:00",
            ),
        ).lastrowid
    )
    db.commit()
    return patient_id


def _bundle(
    *,
    birthdate="1988-08-01",
    observations=None,
    unavailable=None,
):
    normalized_observations = []
    for row in observations or []:
        item = dict(row)
        item.setdefault(
            "source_detail",
            "laboratory"
            if item.get("channel") == "lab"
            else "clinic",
        )
        normalized_observations.append(item)
    return {
        "patient": {
            "id": 7,
            "birthdate": birthdate,
            "gender": "female",
            "enrolled_at": "2026-01-01 09:00:00",
            "updated_at": "2026-01-01 09:00:00",
            "clinical_data_revision": 0,
        },
        "conditions": [],
        "medications": [],
        "medication_events": [],
        "allergies": [],
        "reconciliations": [],
        "conflicts": [],
        "flags": [],
        "flag_catalog": [],
        "observations": normalized_observations,
        "unavailable": unavailable or {},
    }


class _BundleRepository:
    def __init__(self, bundle):
        self.bundle = bundle

    def load_bundle(self, patient_link_id):
        assert patient_link_id == 7
        return self.bundle


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1367/05/10", date(1988, 8, 1)),
        ("۱۳۶۷/۰۵/۱۰", date(1988, 8, 1)),
        ("1988-08-01", date(1988, 8, 1)),
        ("1988/8/1", date(1988, 8, 1)),
        ("1367", None),
        ("not-a-date", None),
    ],
)
def test_birthdate_normalization_requires_complete_valid_date(raw, expected):
    assert normalize_birthdate(raw) == expected


def test_age_uses_full_boundary_and_rejects_impossible_dates():
    birth = date(1988, 8, 1)
    assert age_on(birth, date(2026, 7, 31)) == 37
    assert age_on(birth, date(2026, 8, 1)) == 38
    assert age_on(date(2027, 1, 1), date(2026, 8, 1)) is None
    assert age_on(date(1800, 1, 1), date(2026, 8, 1)) is None


def test_hash_and_observation_union_ignore_input_row_order():
    rows = [
        {
            "channel": "vital",
            "record_id": 99,
            "key": "hba1c",
            "value": 8.2,
            "unit": "%",
            "effective_at": "2026-07-01 10:00:00",
            "recorded_by": "nurse",
            "ref_low": None,
            "ref_high": None,
            "source_detail": "clinic",
        },
        {
            "channel": "lab",
            "record_id": 3,
            "key": "hba1c",
            "value": 7.1,
            "unit": "%",
            "effective_at": "2026-07-01 10:00:00",
            "recorded_by": "lab",
            "ref_low": 4.0,
            "ref_high": 5.6,
            "source_detail": "laboratory",
        },
    ]
    first = FactBuilder(
        _BundleRepository(_bundle(observations=rows))
    ).build(7, as_of_at=AS_OF)
    second = FactBuilder(
        _BundleRepository(
            _bundle(observations=list(reversed(rows)))
        )
    ).build(7, as_of_at=AS_OF)

    assert first.content_hash == second.content_hash
    assert snapshot_payload(first) == snapshot_payload(second)
    hba1c = [
        fact
        for fact in first.facts
        if fact.key == "observation.hba1c"
    ]
    assert [fact.fact_id for fact in hba1c] == ["vital:99", "lab:3"]
    assert [fact.value for fact in hba1c] == [8.2, 7.1]
    assert hba1c[-1].reference_range["high"] == 5.6
    assert all(
        fact.freshness.value == "UNKNOWN" for fact in hba1c
    )


def test_every_serialized_fact_conforms_to_published_schema():
    schema_path = (
        SPECIALIST_ROOT
        / "src"
        / "domain"
        / "clinical_engine"
        / "schemas"
        / "clinical-fact.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )
    bundle = _bundle()
    bundle["allergies"] = [
        {
            "id": 5,
            "substance": "پنی‌سیلین",
            "created_at": "2025-01-01",
            "is_active": 1,
        }
    ]
    snapshot = FactBuilder(_BundleRepository(bundle)).build(
        7,
        as_of_at=AS_OF,
    )
    for fact in snapshot_payload(snapshot)["facts"]:
        assert list(validator.iter_errors(fact)) == []


def test_empty_unreconciled_and_unavailable_are_distinct():
    facts = ReconciledFactBundleAdapter().adapt(
        _bundle(unavailable={"medications": "OperationalError"}),
        as_of_at=AS_OF,
    )
    medications = next(
        fact for fact in facts if fact.key == "medication.classes"
    )
    allergies = next(
        fact for fact in facts if fact.key == "allergy.substances"
    )
    assert medications.status is FactStatus.UNKNOWN
    assert medications.value is None
    assert "SOURCE_UNAVAILABLE" in medications.warnings
    assert allergies.status is FactStatus.UNKNOWN
    assert allergies.value is None
    assert "UNRECONCILED_COLLECTION" in allergies.warnings
    assert next(
        fact for fact in facts if fact.key == "observation.keys"
    ).value == []
    assert next(
        fact for fact in facts if fact.key == "flag.values"
    ).value == []


@pytest.mark.parametrize(
    "effective_at",
    ["broken-date", "2027-01-01 10:00:00"],
)
def test_malformed_or_future_observation_is_explicitly_unusable(
    effective_at,
):
    row = {
        "channel": "vital",
        "record_id": 8,
        "key": "fbs",
        "value": 220,
        "unit": "mg/dL",
        "effective_at": effective_at,
        "recorded_by": "nurse",
        "ref_low": None,
        "ref_high": None,
        "source_detail": "clinic",
    }
    facts = ReconciledFactBundleAdapter().adapt(
        _bundle(observations=[row]),
        as_of_at=AS_OF,
    )
    fact = next(item for item in facts if item.fact_id == "vital:8")
    assert fact.status is FactStatus.UNKNOWN
    assert fact.value is None
    assert fact.verification.value == "UNVERIFIED"
    assert "OUTLIER" in fact.warnings


def test_unclassified_active_medication_is_never_verified_empty():
    bundle = _bundle()
    bundle["medications"] = [
        {
            "id": 4,
            "drug_name": "داروی قدیمی",
            "drug_class": None,
            "drug_catalog_id": None,
            "created_at": "2025-01-01",
            "is_active": 1,
        }
    ]
    facts = ReconciledFactBundleAdapter().adapt(
        bundle,
        as_of_at=AS_OF,
    )
    classes = next(
        fact for fact in facts if fact.key == "medication.classes"
    )
    assert classes.status is FactStatus.UNKNOWN
    assert classes.value is None
    assert "CANONICAL_MAPPING_INCOMPLETE" in classes.warnings
    assert "UNMAPPED_MEDICATION_CONCEPT" in classes.warnings


def test_null_lab_value_is_not_present():
    row = {
        "channel": "lab",
        "record_id": 9,
        "key": "egfr",
        "value": None,
        "unit": "mL/min/1.73m2",
        "effective_at": "2026-06-01",
        "recorded_by": "lab",
        "ref_low": None,
        "ref_high": None,
        "source_detail": "laboratory",
    }
    facts = ReconciledFactBundleAdapter().adapt(
        _bundle(observations=[row]),
        as_of_at=AS_OF,
    )
    fact = next(item for item in facts if item.fact_id == "lab:9")
    assert fact.status is FactStatus.UNKNOWN
    assert fact.value is None


def test_repository_union_preserves_both_channels_with_stable_order(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _insert_patient(db)
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source,
            recorded_by)
           VALUES (?, 'egfr', 52, 'mL/min/1.73m2',
                   '2026-06-01 08:00:00', 'clinic', 'nurse')""",
        (patient_id,),
    )
    db.execute(
        """INSERT INTO lab_results
           (patient_link_id, test_name, test_key, value, unit, taken_at,
            recorded_by)
           VALUES (?, 'eGFR', 'egfr', 44, 'mL/min/1.73m2',
                   '2026-06-01 08:00:00', 'lab')""",
        (patient_id,),
    )
    db.commit()

    snapshot = FactBuilder().build(patient_id, as_of_at=AS_OF)
    egfr = [
        fact
        for fact in snapshot.facts
        if fact.key == "observation.egfr"
    ]
    assert [fact.value for fact in egfr] == [52, 44]
    assert egfr[0].fact_id.startswith("vital:")
    assert egfr[1].fact_id.startswith("lab:")


def test_off_writes_nothing_and_shadow_persists_only_v2_audit(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _insert_patient(db)
    capture = ShadowFactCapture()
    assert capture.capture(patient_id, as_of_at=AS_OF) is None
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_engine_runs"
    ).fetchone()["count"] == 0

    db.execute(
        "UPDATE settings SET value='shadow' "
        "WHERE key='clinical_engine_v2_mode'"
    )
    db.commit()
    run_id = capture.capture(
        patient_id,
        as_of_at=AS_OF,
        created_by="pytest",
    )
    row = db.execute(
        "SELECT * FROM clinical_engine_runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    assert row["run_status"] == "COMPLETED"
    payload = json.loads(row["fact_snapshot_json"])
    assert payload["content_hash"] == FactBuilder().build(
        patient_id,
        as_of_at=AS_OF,
    ).content_hash
    assert json.loads(row["summary_json"]) == {
        "clinical_data_revision": 0,
        "context_hash": payload["context_hash"],
        "engine_version": ENGINE_VERSION,
        "evaluated_rules": 0,
        "mode": "shadow",
        "recommendations": 0,
    }
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_rule_evaluations"
    ).fetchone()["count"] == 0
    assert db.execute(
        "SELECT COUNT(*) AS count FROM clinical_recommendation_events"
    ).fetchone()["count"] == 0


def test_demo_cohort_fixed_as_of_hashes_are_repeatable(facts_app):
    from src.services.clinical_engine.demo_cohort import DemoCohortService

    summary = DemoCohortService().ensure(actor="pytest")
    patient_ids = [patient["id"] for patient in summary["patients"]]
    builder = FactBuilder()
    first = {
        patient_id: builder.build(
            patient_id,
            as_of_at=AS_OF,
        ).content_hash
        for patient_id in patient_ids
    }
    second = {
        patient_id: builder.build(
            patient_id,
            as_of_at=AS_OF,
        ).content_hash
        for patient_id in reversed(patient_ids)
    }
    assert first == second
    assert len(set(first.values())) == 10


def test_missing_patient_fails_loudly(facts_app):
    with pytest.raises(LookupError, match="was not found"):
        FactBuilder().build(999999, as_of_at=AS_OF)


def test_raw_global_mode_without_seal_fails_closed(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        "UPDATE settings SET value='on' "
        "WHERE key='clinical_engine_v2_mode'"
    )
    db.commit()
    assert ClinicalEngineFactRepository().get_mode() == "off"


def test_selected_mode_requires_seal_and_limits_cohort(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    selected = _insert_patient(db, national_id="TEST0001")
    ordinary = _insert_patient(db, national_id="REAL0001")
    ruleset_id = install_sealed_rollout()

    repository = ClinicalEngineFactRepository()
    assert repository.get_mode() == "on_selected"
    assert repository.is_selected_patient(selected) is True
    assert repository.is_selected_patient(ordinary) is False

    capture = ShadowFactCapture()
    assert capture.capture(
        ordinary,
        as_of_at=AS_OF,
        ruleset_id=ruleset_id,
    ) is None
    selected_run = capture.capture(
        selected,
        as_of_at=AS_OF,
        ruleset_id=ruleset_id,
    )
    assert selected_run
    rows = db.execute(
        "SELECT patient_link_id, summary_json FROM clinical_engine_runs"
    ).fetchall()
    assert [row["patient_link_id"] for row in rows] == [selected]
    summary = json.loads(rows[0]["summary_json"])
    assert summary["mode"] == "on_selected"
    assert summary["engine_version"] == ENGINE_VERSION
