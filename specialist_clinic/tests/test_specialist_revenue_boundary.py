from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

import pytest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _accounting_schema(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY,
            name TEXT,
            family_name TEXT,
            full_name TEXT,
            national_id TEXT UNIQUE,
            phone_number TEXT,
            birthdate TEXT,
            gender TEXT,
            insurance_type TEXT,
            insurance_expiry TEXT,
            address TEXT,
            is_foreign INTEGER DEFAULT 0,
            created_by TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER,
            nurse_id INTEGER,
            status TEXT DEFAULT 'open',
            insurance_type TEXT,
            supplementary_insurance TEXT,
            total_amount REAL DEFAULT 0,
            work_date TEXT,
            shift TEXT,
            opened_at TEXT,
            closed_at TEXT,
            opened_by TEXT,
            opened_by_name TEXT,
            closed_by TEXT,
            closed_by_name TEXT
        );
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            doctor_name TEXT,
            visit_date TEXT,
            shift TEXT,
            work_date TEXT,
            insurance_type TEXT,
            supplementary_insurance TEXT,
            status TEXT,
            price REAL DEFAULT 0,
            payment_status TEXT,
            reception_user TEXT,
            notes TEXT,
            invoice_id INTEGER,
            doctor_id INTEGER,
            nurse_id INTEGER,
            created_at TEXT
        );
        CREATE TABLE injections (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            injection_type TEXT,
            total_price REAL DEFAULT 0,
            invoice_id INTEGER
        );
        CREATE TABLE procedures (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            procedure_type TEXT,
            price REAL DEFAULT 0,
            invoice_id INTEGER
        );
        CREATE TABLE invoice_item_payments (
            invoice_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            payment_type TEXT,
            is_paid INTEGER DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY(invoice_id, item_type, item_id)
        );
        """
    )
    connection.execute(
        """INSERT INTO patients
           (id, name, family_name, full_name, national_id, phone_number,
            birthdate, gender, insurance_type, is_foreign)
           VALUES (1, 'آزمایش', 'مرزی', 'آزمایش مرزی', '0010000001',
                   '09120000001', '1980-01-01', 'female', 'آزاد', 0)"""
    )
    # Six-month/pilot history: visible after enrollment, never specialist revenue.
    connection.execute(
        """INSERT INTO invoices
           (id, patient_id, status, total_amount, work_date, opened_at, closed_at)
           VALUES (1, 1, 'closed', 100000, '2025-12-01',
                   '2025-12-01 09:00:00', '2025-12-01 10:00:00')"""
    )
    connection.execute(
        """INSERT INTO visits
           (id, patient_id, doctor_name, visit_date, work_date, price,
            payment_status, invoice_id)
           VALUES (1, 1, 'پزشک عمومی', '2025-12-01 09:30:00',
                   '2025-12-01', 100000, 'paid', 1)"""
    )
    connection.execute(
        """INSERT INTO invoice_item_payments
           (invoice_id, item_type, item_id, payment_type, is_paid, updated_at)
           VALUES (1, 'visit', 1, 'cash', 1, '2025-12-01 10:00:00')"""
    )
    connection.commit()
    connection.close()


def _add_open_specialist_invoice(path: Path, *, work_date: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """INSERT INTO invoices
           (id, patient_id, status, total_amount, work_date, opened_at)
           VALUES (2, 1, 'open', 250000, ?, ?)""",
        (work_date, f"{work_date} 09:00:00"),
    )
    connection.execute(
        """INSERT INTO visits
           (id, patient_id, doctor_name, visit_date, work_date, price,
            payment_status, invoice_id)
           VALUES (2, 1, 'پزشک تخصصی', ?, ?, 250000, 'unpaid', 2)""",
        (f"{work_date} 09:30:00", work_date),
    )
    connection.commit()
    connection.close()


def _close_and_pay_specialist_invoice(path: Path, *, work_date: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """UPDATE invoices SET status='closed', closed_at=? WHERE id=2""",
        (f"{work_date} 10:00:00",),
    )
    connection.execute(
        """INSERT INTO invoice_item_payments
           (invoice_id, item_type, item_id, payment_type, is_paid, updated_at)
           VALUES (2, 'visit', 2, 'card', 1, ?)""",
        (f"{work_date} 10:00:00",),
    )
    connection.commit()
    connection.close()


@pytest.fixture()
def boundary_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.config.settings import Config
    from src.app import create_app

    accounting = tmp_path / "accounting-pilot.db"
    specialist = tmp_path / "specialist-test.db"
    _accounting_schema(accounting)
    monkeypatch.setenv("ACCOUNTING_DB_PATH", str(accounting))
    Config.ACCOUNTING_DB_PATH = str(accounting)
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(specialist),
            "ACCOUNTING_DB_PATH": str(accounting),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "a0-boundary-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app, accounting, specialist
    context.pop()
    core._initialized = False


def _enroll() -> int:
    from src.services.patient_service import PatientService

    patient_id = PatientService().enroll_from_accounting(1, "pytest-admin")
    assert patient_id
    return int(patient_id)


def test_history_is_visible_but_not_specialist_revenue(boundary_app):
    from src.adapters.sqlite.specialist_enrollment_repo import (
        SpecialistEnrollmentRepository,
    )
    from src.services.patient_service import PatientService
    from src.services.revenue_service import RevenueService

    patient_id = _enroll()
    profile = PatientService().get_full_profile(patient_id)
    assert len(profile["visit_history"]) == 1
    assert profile["visit_history"][0]["invoice_id"] == 1

    enrollment = SpecialistEnrollmentRepository().get_by_patient(patient_id)
    assert enrollment["history_policy"] == "VISIBLE_EXCLUDED"
    assert enrollment["accounting_invoice_cutoff_id"] == 1

    dashboard = RevenueService().dashboard()
    assert dashboard["available"] is True
    assert dashboard["total"]["total"] == 0
    assert dashboard["total"]["collected"] == 0
    assert dashboard["total"]["invoices"] == 0
    assert dashboard["scope"]["history_visible_but_excluded"] is True


def test_enrollment_cutover_and_accounting_identity_are_immutable(boundary_app):
    import sqlite3 as sqlite

    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.specialist_enrollment_repo import (
        SpecialistEnrollmentRepository,
    )

    patient_id = _enroll()
    enrollment = SpecialistEnrollmentRepository().get_by_patient(patient_id)
    assert enrollment
    with pytest.raises(sqlite.IntegrityError, match="immutable"):
        get_db().execute(
            "UPDATE specialist_program_enrollments SET effective_at='2020-01-01'"
        )
    get_db().rollback()
    with pytest.raises(sqlite.IntegrityError, match="immutable"):
        get_db().execute(
            "UPDATE patient_links SET accounting_patient_id=99 WHERE id=?",
            (patient_id,),
        )
    get_db().rollback()


def test_manual_patient_never_infers_accounting_link(boundary_app):
    from src.adapters.sqlite.patients_repo import PatientRepository
    from src.services.patient_service import PatientService

    patient_id = PatientService().enroll_manual(
        full_name="بیمار دستی",
        national_id="0020000002",
        phone_number="09120000002",
        gender="male",
        birthdate="1990-01-01",
        address=None,
        enrolled_by="pytest-admin",
    )
    patient = PatientRepository().get_by_id(patient_id)
    assert patient["accounting_patient_id"] is None


def test_enrollment_rolls_back_local_patient_when_cutover_fails(boundary_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.specialist_enrollment_repo import (
        SpecialistEnrollmentRepository,
    )
    from src.services.specialist_enrollment_service import (
        SpecialistProgramEnrollmentService,
    )

    class BrokenRepository(SpecialistEnrollmentRepository):
        def create_once(self, **kwargs):
            raise RuntimeError("simulated cutover failure")

    with pytest.raises(RuntimeError, match="cutover failure"):
        SpecialistProgramEnrollmentService(
            repository=BrokenRepository(get_db())
        ).enroll_from_accounting(1, actor_username="pytest-admin")
    assert get_db().execute(
        "SELECT COUNT(*) AS count FROM patient_links WHERE accounting_patient_id=1"
    ).fetchone()["count"] == 0


def test_doctor_queue_creates_explicit_journey_and_only_that_invoice_counts(
    boundary_app,
):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.common.utils import today_str
    from src.services.doctor_queue_service import DoctorQueueService
    from src.services.revenue_service import RevenueService

    _app, accounting, _specialist = boundary_app
    patient_id = _enroll()
    work_date = today_str()
    _add_open_specialist_invoice(accounting, work_date=work_date)

    before_read = _sha256(accounting)
    DoctorQueueService(work_date_provider=lambda: work_date).start(
        {"accounting_invoice_id": 2, "patient_link_id": 999999,
         "national_id": "TAMPERED", "full_name": "TAMPERED"},
        actor_username="pytest-doctor",
    )
    assert _sha256(accounting) == before_read

    repository = CareJourneyRepository()
    encounter = repository.encounter_for_invoice(2)
    assert encounter["patient_link_id"] == patient_id
    attribution = repository.current_attribution(2)
    assert attribution["event_type"] == "ATTRIBUTED"
    assert attribution["patient_link_id"] == patient_id
    assert repository.attributed_invoice_ids() == [2]

    # Open invoice is scoped, but not billed/collected until accounting closes it.
    before_close = RevenueService().dashboard()
    assert before_close["total"]["total"] == 0
    assert before_close["total"]["invoices"] == 0

    # This write simulates the independent accounting app, not the specialist app.
    _close_and_pay_specialist_invoice(accounting, work_date=work_date)
    after_accounting_write = _sha256(accounting)
    dashboard = RevenueService().dashboard()
    assert _sha256(accounting) == after_accounting_write
    assert dashboard["total"]["visits"] == 250000
    assert dashboard["total"]["total"] == 250000
    assert dashboard["total"]["collected"] == 250000
    assert dashboard["total"]["invoices"] == 1
    # The older paid invoice remains visible but excluded.
    assert dashboard["total"]["total"] != 350000


def test_route_ignores_cross_patient_hidden_identity(boundary_app):
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.common.utils import today_str

    app, accounting, _specialist = boundary_app
    patient_id = _enroll()
    work_date = today_str()
    _add_open_specialist_invoice(accounting, work_date=work_date)
    client = app.test_client()
    response = client.post(
        "/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert response.status_code in {302, 303}
    response = client.post(
        "/doctor-queue/2/start",
        data={
            "patient_link_id": "999999",
            "national_id": "0000000000",
            "full_name": "بیمار اشتباه",
            "work_date": "1999-01-01",
        },
    )
    assert response.status_code in {302, 303}
    encounter = CareJourneyRepository().encounter_for_invoice(2)
    assert encounter["patient_link_id"] == patient_id


def test_campaign_revenue_is_fail_closed_until_journey_link(boundary_app):
    from src.services.revenue_service import RevenueService

    _enroll()
    result = RevenueService().campaign_revenue()
    assert result["attributed_total"] == 0
    assert result["safe_to_sum"] is False
    assert result["measurement_status"] == "JOURNEY_LINK_REQUIRED"
