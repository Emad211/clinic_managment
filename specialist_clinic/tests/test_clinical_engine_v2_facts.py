"""PR-04: deterministic canonical facts and snapshot-only shadow execution."""

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

from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
from src.domain.clinical_engine import FactStatus
from src.services.clinical_engine.fact_builder import (
    FactBuilder,
    ShadowFactCapture,
    snapshot_payload,
)
from src.services.clinical_engine.legacy_adapter import (
    LegacyFactBundleAdapter,
    age_on,
    normalize_birthdate,
)


AS_OF = datetime(2026, 7, 21, 12, 0, 0)


@pytest.fixture()
def facts_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "facts.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "facts-test",
    })
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _insert_patient(db, national_id="FACT0001", birthdate="1988-08-01"):
    cur = db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, gender, birthdate, enrolled_by,
            enrolled_at, updated_at)
           VALUES (?, 'Fact Patient', 'female', ?, 'pytest', ?, ?)""",
        (national_id, birthdate, "2026-01-01 09:00:00", "2026-01-01 09:00:00"),
    )
    db.commit()
    return int(cur.lastrowid)


def _bundle(*, birthdate="1988-08-01", observations=None, unavailable=None):
    return {
        "patient": {"id": 7, "birthdate": birthdate, "gender": "female",
                    "enrolled_at": "2026-01-01 09:00:00", "updated_at": "2026-01-01 09:00:00"},
        "conditions": [], "medications": [], "allergies": [], "flags": [],
        "flag_catalog": [], "observations": observations or [],
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
def test_birthdate_normalization_requires_a_complete_valid_date(raw, expected):
    assert normalize_birthdate(raw) == expected


def test_age_uses_full_date_boundary_and_rejects_future_or_implausible_dates():
    birth = date(1988, 8, 1)
    assert age_on(birth, date(2026, 7, 31)) == 37
    assert age_on(birth, date(2026, 8, 1)) == 38
    assert age_on(date(2027, 1, 1), date(2026, 8, 1)) is None
    assert age_on(date(1800, 1, 1), date(2026, 8, 1)) is None


def test_hash_and_observation_union_are_independent_of_input_row_order():
    rows = [
        {"channel": "vital", "record_id": 99, "key": "hba1c", "value": 8.2,
         "unit": "%", "effective_at": "2026-07-01 10:00:00", "recorded_by": "nurse",
         "ref_low": None, "ref_high": None},
        {"channel": "lab", "record_id": 3, "key": "hba1c", "value": 7.1,
         "unit": "%", "effective_at": "2026-07-01 10:00:00", "recorded_by": "lab",
         "ref_low": 4.0, "ref_high": 5.6},
    ]
    first = FactBuilder(_BundleRepository(_bundle(observations=rows))).build(7, as_of_at=AS_OF)
    second = FactBuilder(_BundleRepository(_bundle(observations=list(reversed(rows))))).build(
        7, as_of_at=AS_OF
    )
    assert first.content_hash == second.content_hash
    assert snapshot_payload(first) == snapshot_payload(second)
    hba1c = [f for f in first.facts if f.key == "observation.hba1c"]
    assert [f.fact_id for f in hba1c] == ["vital:99", "lab:3"]
    assert [f.value for f in hba1c] == [8.2, 7.1]
    assert hba1c[-1].reference_range["high"] == 5.6
    assert all(f.freshness.value == "UNKNOWN" for f in hba1c)


def test_every_serialized_fact_conforms_to_the_published_v2_schema():
    schema_path = SPECIALIST_ROOT / "src" / "domain" / "clinical_engine" / "schemas" / "clinical-fact.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    bundle = _bundle()
    bundle["allergies"] = [{"id": 5, "substance": "پنی‌سیلین", "created_at": "2025-01-01"}]
    snapshot = FactBuilder(_BundleRepository(bundle)).build(7, as_of_at=AS_OF)
    for fact in snapshot_payload(snapshot)["facts"]:
        assert list(validator.iter_errors(fact)) == []


def test_empty_collection_and_unavailable_source_have_distinct_semantics():
    facts = LegacyFactBundleAdapter().adapt(
        _bundle(unavailable={"medications": "OperationalError"}), as_of_at=AS_OF
    )
    meds = next(f for f in facts if f.key == "medication.classes")
    allergies = next(f for f in facts if f.key == "allergy.substances")
    assert meds.status is FactStatus.UNKNOWN
    assert meds.value is None
    assert "SOURCE_UNAVAILABLE" in meds.warnings
    assert allergies.status is FactStatus.PRESENT
    assert allergies.value == []
    observations = next(f for f in facts if f.key == "observation.keys")
    flags = next(f for f in facts if f.key == "flag.values")
    assert observations.value == []
    assert flags.value == []


@pytest.mark.parametrize("effective_at", ["broken-date", "2027-01-01 10:00:00"])
def test_malformed_or_future_observation_is_explicitly_unusable(effective_at):
    row = {"channel": "vital", "record_id": 8, "key": "fbs", "value": 220,
           "unit": "mg/dL", "effective_at": effective_at, "recorded_by": "nurse",
           "ref_low": None, "ref_high": None}
    facts = LegacyFactBundleAdapter().adapt(_bundle(observations=[row]), as_of_at=AS_OF)
    fact = next(f for f in facts if f.fact_id == "vital:8")
    assert fact.status is FactStatus.UNKNOWN
    assert fact.value is None
    assert fact.verification.value == "UNVERIFIED"
    assert "OUTLIER" in fact.warnings


def test_unclassified_active_medication_cannot_look_like_verified_empty_class_list():
    bundle = _bundle()
    bundle["medications"] = [{"id": 4, "drug_name": "داروی قدیمی", "drug_class": None,
                              "created_at": "2025-01-01"}]
    facts = LegacyFactBundleAdapter().adapt(bundle, as_of_at=AS_OF)
    classes = next(f for f in facts if f.key == "medication.classes")
    assert classes.status is FactStatus.UNKNOWN
    assert classes.value is None
    assert "LEGACY_APPROXIMATION" in classes.warnings


def test_null_lab_value_is_not_emitted_as_present():
    row = {"channel": "lab", "record_id": 9, "key": "egfr", "value": None,
           "unit": "mL/min/1.73m2", "effective_at": "2026-06-01", "recorded_by": "lab",
           "ref_low": None, "ref_high": None}
    facts = LegacyFactBundleAdapter().adapt(_bundle(observations=[row]), as_of_at=AS_OF)
    fact = next(f for f in facts if f.fact_id == "lab:9")
    assert fact.status is FactStatus.UNKNOWN
    assert fact.value is None


def test_repository_canonical_union_preserves_both_channels_with_stable_tie_order(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    pid = _insert_patient(db)
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source, recorded_by)
           VALUES (?, 'egfr', 52, 'mL/min/1.73m2', '2026-06-01 08:00:00', 'clinic', 'nurse')""",
        (pid,),
    )
    db.execute(
        """INSERT INTO lab_results
           (patient_link_id, test_name, test_key, value, unit, taken_at, recorded_by)
           VALUES (?, 'eGFR', 'egfr', 44, 'mL/min/1.73m2', '2026-06-01 08:00:00', 'lab')""",
        (pid,),
    )
    db.commit()

    snapshot = FactBuilder().build(pid, as_of_at=AS_OF)
    egfr = [f for f in snapshot.facts if f.key == "observation.egfr"]
    assert [f.value for f in egfr] == [52, 44]
    assert egfr[0].fact_id.startswith("vital:")
    assert egfr[1].fact_id.startswith("lab:")


def test_off_mode_writes_nothing_and_shadow_persists_snapshot_without_outputs(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    pid = _insert_patient(db)
    capture = ShadowFactCapture()
    assert capture.capture(pid, as_of_at=AS_OF) is None
    assert db.execute("SELECT COUNT(*) c FROM clinical_engine_runs").fetchone()["c"] == 0

    db.execute("UPDATE settings SET value='shadow' WHERE key='clinical_engine_v2_mode'")
    db.commit()
    run_id = capture.capture(pid, as_of_at=AS_OF, created_by="pytest")
    row = db.execute("SELECT * FROM clinical_engine_runs WHERE run_id=?", (run_id,)).fetchone()
    assert row["run_status"] == "COMPLETED"
    payload = json.loads(row["fact_snapshot_json"])
    assert payload["content_hash"] == FactBuilder().build(pid, as_of_at=AS_OF).content_hash
    assert json.loads(row["summary_json"]) == {
        "evaluated_rules": 0, "mode": "shadow", "recommendations": 0
    }
    assert db.execute("SELECT COUNT(*) c FROM clinical_rule_evaluations").fetchone()["c"] == 0
    assert db.execute("SELECT COUNT(*) c FROM clinical_recommendation_events").fetchone()["c"] == 0


def test_test0001_through_test0010_have_repeatable_fixed_as_of_hashes(facts_app):
    from seed_demo_data import PATIENTS, trend
    from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
    from src.adapters.sqlite.patients_repo import PatientRepository
    from src.adapters.sqlite.vitals_repo import VitalsRepository

    patients = PatientRepository()
    vitals = VitalsRepository()
    flags = ClinicalFlagsRepository()
    patient_ids = []
    for spec in PATIENTS:
        pid = patients.create(
            national_id=spec["nid"], accounting_patient_id=None,
            full_name=spec["name"], phone_number=spec["phone"],
            gender=spec["gender"], birthdate=spec["birth"], address=None,
            enrolled_by="seed",
        )
        for condition_id in spec["conditions"]:
            patients.add_condition(pid, condition_id)
        flags.set_flags(pid, spec.get("flags", {}), recorded_by="seed")
        for vital_type, (start, end, dates) in spec["vitals"].items():
            for measured_on, value in zip(dates, trend(start, end, len(dates))):
                vitals.add_reading(
                    pid, vtype=vital_type, value=round(value, 1),
                    measured_at=measured_on + " 10:00:00", recorded_by="seed",
                )
        for name, drug_class, dose, start, change, stop in spec.get("meds", []):
            medication_id = patients.add_medication(
                pid, drug_name=name, dose=dose, schedule=None, start_date=start,
                refill_due_date="2026-07-01", notes=None, drug_class=drug_class,
                created_by="seed",
            )
            if change:
                patients.change_dose(
                    medication_id, change[1], change_date=change[0], created_by="seed"
                )
            if stop:
                patients.stop_medication(medication_id, end_date=stop, created_by="seed")
        patient_ids.append(pid)

    builder = FactBuilder()
    first = {pid: builder.build(pid, as_of_at=AS_OF).content_hash for pid in patient_ids}
    second = {pid: builder.build(pid, as_of_at=AS_OF).content_hash for pid in reversed(patient_ids)}
    assert first == second
    assert len(set(first.values())) == 10


def test_missing_patient_fails_loudly(facts_app):
    with pytest.raises(LookupError, match="was not found"):
        FactBuilder().build(999999, as_of_at=AS_OF)


def test_invalid_mode_fails_closed_to_off(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute("UPDATE settings SET value='on' WHERE key='clinical_engine_v2_mode'")
    db.commit()
    assert ClinicalEngineFactRepository().get_mode() == "off"


def test_on_selected_mode_is_limited_to_seeded_demo_patients(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    selected = _insert_patient(db, national_id="TEST0001")
    ordinary = _insert_patient(db, national_id="REAL0001")
    db.execute("UPDATE settings SET value='on_selected' WHERE key='clinical_engine_v2_mode'")
    db.commit()

    repository = ClinicalEngineFactRepository()
    assert repository.get_mode() == "on_selected"
    assert repository.is_selected_patient(selected) is True
    assert repository.is_selected_patient(ordinary) is False


def test_on_selected_capture_writes_only_for_seeded_demo_patient(facts_app):
    from src.adapters.sqlite.core import get_db

    db = get_db()
    selected = _insert_patient(db, national_id="TEST0010")
    ordinary = _insert_patient(db, national_id="REAL0010")
    db.execute("UPDATE settings SET value='on_selected' WHERE key='clinical_engine_v2_mode'")
    db.commit()

    capture = ShadowFactCapture()
    assert capture.capture(ordinary, as_of_at=AS_OF) is None
    selected_run = capture.capture(selected, as_of_at=AS_OF)
    assert selected_run
    rows = db.execute(
        "SELECT patient_link_id, summary_json FROM clinical_engine_runs"
    ).fetchall()
    assert [row["patient_link_id"] for row in rows] == [selected]
    assert json.loads(rows[0]["summary_json"])["mode"] == "on_selected"


def test_legacy_engine_output_is_identical_while_shadow_adds_audit_only(facts_app):
    from src.adapters.sqlite.core import get_db
    from src.services.rule_engine import RuleEngine

    db = get_db()
    pid = _insert_patient(db)
    engine = RuleEngine()
    legacy_off = engine.evaluate(pid)
    assert db.execute("SELECT COUNT(*) c FROM clinical_engine_runs").fetchone()["c"] == 0

    db.execute("UPDATE settings SET value='shadow' WHERE key='clinical_engine_v2_mode'")
    db.commit()
    legacy_shadow = engine.evaluate(pid)
    assert legacy_shadow == legacy_off
    assert db.execute("SELECT COUNT(*) c FROM clinical_engine_runs").fetchone()["c"] == 1
    assert db.execute("SELECT COUNT(*) c FROM clinical_recommendation_events").fetchone()["c"] == 0
