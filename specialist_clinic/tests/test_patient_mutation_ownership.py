"""Regression tests for patient-row ownership on legacy mutation URLs."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))


@pytest.fixture()
def ownership_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "ownership.db"),
        "BACKUP_FOLDER": str(tmp_path / "backups"),
        "SECRET_KEY": "ownership-test",
    })
    yield app
    core._initialized = False


def _login(client):
    response = client.post(
        "/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert response.status_code in {302, 303}


def _patients_and_rows(app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.patients_repo import PatientRepository

    with app.app_context():
        db = get_db()
        first = int(db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by, enrolled_at)
               VALUES ('OWN0001', 'First Patient', 'pytest',
                       '2026-07-22 09:00:00')"""
        ).lastrowid)
        second = int(db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by, enrolled_at)
               VALUES ('OWN0002', 'Second Patient', 'pytest',
                       '2026-07-22 09:00:00')"""
        ).lastrowid)
        db.commit()
        repo = PatientRepository()
        condition_id = repo.add_condition(first, 1, onset_date="2020-01-01")
        allergy_id = repo.add_allergy(
            first,
            substance="Penicillin",
            reaction="rash",
            severity="moderate",
        )
        stop_medication_id = repo.add_medication(
            first,
            drug_name="Medication Stop",
            dose="1",
            schedule="روزانه",
            start_date="2026-01-01",
            refill_due_date=None,
            notes=None,
            drug_class="test-stop",
            created_by="doctor",
        )
        dose_medication_id = repo.add_medication(
            first,
            drug_name="Medication Dose",
            dose="1",
            schedule="روزانه",
            start_date="2026-01-01",
            refill_due_date=None,
            notes=None,
            drug_class="test-dose",
            created_by="doctor",
        )
        return first, second, condition_id, allergy_id, stop_medication_id, dose_medication_id


def test_guard_handlers_are_installed_without_changing_public_endpoints(ownership_app):
    for endpoint in (
        "patients.remove_condition",
        "patients.stop_medication",
        "patients.change_dose",
        "patients.delete_allergy",
    ):
        view = ownership_app.view_functions[endpoint]
        assert view.__module__ == "src.api.patient_mutation_guards"


def test_cross_patient_row_ids_are_rejected_and_leave_history_unchanged(
    ownership_app,
):
    from src.adapters.sqlite.core import get_db

    first, second, condition_id, allergy_id, stop_med_id, dose_med_id = (
        _patients_and_rows(ownership_app)
    )
    client = ownership_app.test_client()
    _login(client)

    requests = (
        (f"/patients/{second}/condition/{condition_id}/remove", {}),
        (f"/patients/{second}/allergy/{allergy_id}/delete", {}),
        (f"/patients/{second}/medication/{stop_med_id}/stop", {}),
        (
            f"/patients/{second}/medication/{dose_med_id}/dose",
            {"dose": "99"},
        ),
    )
    for url, data in requests:
        response = client.post(url, data=data)
        assert response.status_code in {302, 303}

    with ownership_app.app_context():
        db = get_db()
        condition = db.execute(
            "SELECT is_active, resolved_at FROM patient_conditions WHERE id=?",
            (condition_id,),
        ).fetchone()
        allergy = db.execute(
            "SELECT is_active, resolved_at FROM allergies WHERE id=?",
            (allergy_id,),
        ).fetchone()
        stopped = db.execute(
            "SELECT is_active, end_date FROM patient_medications WHERE id=?",
            (stop_med_id,),
        ).fetchone()
        dose = db.execute(
            "SELECT dose FROM patient_medications WHERE id=?",
            (dose_med_id,),
        ).fetchone()
        assert dict(condition) == {"is_active": 1, "resolved_at": None}
        assert dict(allergy) == {"is_active": 1, "resolved_at": None}
        assert dict(stopped) == {"is_active": 1, "end_date": None}
        assert dose["dose"] == "1"
        assert db.execute(
            "SELECT COUNT(*) AS count FROM medication_events "
            "WHERE medication_id=? AND event_type='dose_change'",
            (dose_med_id,),
        ).fetchone()["count"] == 0


def test_valid_patient_owned_mutations_preserve_effective_history(ownership_app):
    from src.adapters.sqlite.core import get_db

    first, _second, condition_id, allergy_id, stop_med_id, dose_med_id = (
        _patients_and_rows(ownership_app)
    )
    client = ownership_app.test_client()
    _login(client)

    assert client.post(
        f"/patients/{first}/condition/{condition_id}/remove"
    ).status_code in {302, 303}
    assert client.post(
        f"/patients/{first}/allergy/{allergy_id}/delete"
    ).status_code in {302, 303}
    assert client.post(
        f"/patients/{first}/medication/{stop_med_id}/stop"
    ).status_code in {302, 303}
    assert client.post(
        f"/patients/{first}/medication/{dose_med_id}/dose",
        data={"dose": "2"},
    ).status_code in {302, 303}

    with ownership_app.app_context():
        db = get_db()
        assert db.execute(
            "SELECT is_active FROM patient_conditions WHERE id=?",
            (condition_id,),
        ).fetchone()["is_active"] == 0
        assert db.execute(
            "SELECT is_active FROM allergies WHERE id=?",
            (allergy_id,),
        ).fetchone()["is_active"] == 0
        stopped = db.execute(
            "SELECT is_active, end_date FROM patient_medications WHERE id=?",
            (stop_med_id,),
        ).fetchone()
        assert stopped["is_active"] == 0
        assert stopped["end_date"]
        assert db.execute(
            "SELECT dose FROM patient_medications WHERE id=?",
            (dose_med_id,),
        ).fetchone()["dose"] == "2"
        assert db.execute(
            "SELECT COUNT(*) AS count FROM medication_events "
            "WHERE medication_id=? AND event_type='dose_change'",
            (dose_med_id,),
        ).fetchone()["count"] == 1
