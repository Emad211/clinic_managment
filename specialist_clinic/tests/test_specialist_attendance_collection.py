from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelConflict,
    SpecialistFinancialFunnelRepository,
)
from src.adapters.sqlite.specialist_financial_funnel_schema import (
    ensure_specialist_financial_funnel_storage,
)
from src.config.settings import Config
from src.services.doctor_queue_service import (
    DoctorQueueIdentityError,
    DoctorQueueService,
)
from src.services.patient_service import PatientService
from src.services.revenue_service import RevenueService
from src.services.specialist_financial_reconciliation_service import (
    SpecialistFinancialReconciliationService,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accounting_db(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY,
            full_name TEXT,
            national_id TEXT,
            phone_number TEXT,
            gender TEXT,
            birthdate TEXT,
            address TEXT,
            insurance_type TEXT,
            insurance_expiry TEXT,
            is_foreign INTEGER DEFAULT 0
        );
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            work_date TEXT,
            opened_at TEXT,
            closed_at TEXT,
            total_amount INTEGER
        );
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY,
            invoice_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            visit_date TEXT,
            doctor_name TEXT,
            insurance_type TEXT,
            supplementary_insurance TEXT
        );
        CREATE TABLE injections (
            id INTEGER PRIMARY KEY,
            invoice_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            total_price INTEGER NOT NULL,
            injection_type TEXT
        );
        CREATE TABLE procedures (
            id INTEGER PRIMARY KEY,
            invoice_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            procedure_type TEXT
        );
        CREATE TABLE invoice_item_payments (
            invoice_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            is_paid INTEGER NOT NULL DEFAULT 0,
            UNIQUE(invoice_id, item_type, item_id)
        );
        INSERT INTO patients
          (id, full_name, national_id, phone_number, gender, birthdate, address,
           insurance_type, insurance_expiry, is_foreign)
        VALUES
          (1, 'بیمار تخصصی', 'A4-001', '09120000001', 'female', '1980-01-01',
           'تهران', 'basic', NULL, 0),
          (2, 'بیمار دیگر', 'A4-002', '09120000002', 'male', '1982-01-01',
           'تهران', 'basic', NULL, 0);
        INSERT INTO invoices
          (id, patient_id, status, work_date, opened_at, closed_at, total_amount)
        VALUES
          (10, 1, 'closed', '2026-01-10', '2026-01-10 08:00:00',
           '2026-01-10 09:00:00', 900000),
          (20, 1, 'open', '2026-07-26', '2026-07-26 08:00:00', NULL, 1500000),
          (30, 2, 'open', '2026-07-26', '2026-07-26 08:30:00', NULL, 500000);
        INSERT INTO visits
          (id, invoice_id, patient_id, price, visit_date, doctor_name)
        VALUES
          (101, 10, 1, 900000, '2026-01-10', 'پزشک عمومی'),
          (201, 20, 1, 1000000, '2026-07-26', 'پزشک تخصصی'),
          (301, 30, 2, 500000, '2026-07-26', 'پزشک تخصصی');
        INSERT INTO procedures
          (id, invoice_id, patient_id, price, procedure_type)
        VALUES (202, 20, 1, 500000, 'specialist-procedure');
        INSERT INTO invoice_item_payments
          (invoice_id, item_type, item_id, is_paid)
        VALUES (10, 'visit', 101, 1);
        """
    )
    db.commit()
    db.close()


@pytest.fixture()
def a4_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    accounting = tmp_path / "accounting.db"
    _accounting_db(accounting)
    previous = Config.ACCOUNTING_DB_PATH
    Config.ACCOUNTING_DB_PATH = str(accounting)
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "specialist.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "a4-test",
        }
    )
    ctx = app.app_context()
    ctx.push()
    ensure_specialist_financial_funnel_storage(core.get_db())
    yield app, accounting
    ctx.pop()
    core._initialized = False
    Config.ACCOUNTING_DB_PATH = previous


def _enroll_and_appointment() -> tuple[int, int]:
    patient_id = PatientService().enroll_from_accounting(1, "pytest")
    assert patient_id
    appointment_id = AppointmentRepository().create(
        patient_id,
        scheduled_at="2026-07-26 09:00:00",
        appt_type="visit",
        notes="از پیگیری",
        created_by="pytest",
    )
    return int(patient_id), int(appointment_id)


def _start_and_complete(patient_id: int, appointment_id: int) -> dict:
    service = DoctorQueueService(work_date_provider=lambda: "2026-07-26")
    started = service.start(
        {"accounting_invoice_id": 20},
        actor_username="doctor",
        appointment_id=appointment_id,
    )
    assert started["patient_link_id"] == patient_id
    assert started["appointment_id"] == appointment_id
    encounter = CareJourneyRepository().encounter_for_invoice(20)
    assert encounter
    assert (
        CareJourneyRepository().current_encounter_event(encounter["encounter_id"])[
            "event_type"
        ]
        == "STARTED"
    )
    link = SpecialistFinancialFunnelRepository().appointment_link_for_encounter(
        encounter["encounter_id"]
    )
    assert int(link["appointment_id"]) == appointment_id
    assert AppointmentRepository().get(appointment_id)["status"] == "done"
    completed = service.end_visit(
        {"accounting_invoice_id": 20},
        "doctor",
        notes="خدمت تخصصی تکمیل شد",
    )
    assert completed["encounter_id"] == encounter["encounter_id"]
    assert (
        CareJourneyRepository().current_encounter_event(encounter["encounter_id"])[
            "event_type"
        ]
        == "COMPLETED"
    )
    return encounter


def test_explicit_appointment_link_rejects_other_patient(a4_app):
    from src.adapters.sqlite.core import get_db

    patient_id, _ = _enroll_and_appointment()
    other_local = int(
        get_db().execute(
            """INSERT INTO patient_links
               (national_id, full_name, enrolled_by)
               VALUES ('LOCAL-OTHER','بیمار دیگر','pytest')"""
        ).lastrowid
    )
    get_db().commit()
    wrong = AppointmentRepository().create(
        other_local,
        scheduled_at="2026-07-26 09:00:00",
        appt_type="visit",
        created_by="pytest",
    )
    with pytest.raises(
        DoctorQueueIdentityError, match="SPECIALIST_APPOINTMENT_PATIENT_MISMATCH"
    ):
        DoctorQueueService(work_date_provider=lambda: "2026-07-26").start(
            {"accounting_invoice_id": 20},
            actor_username="doctor",
            appointment_id=wrong,
        )
    assert CareJourneyRepository().encounter_for_invoice(20) is None
    assert AppointmentRepository().get(wrong)["status"] == "scheduled"
    assert patient_id > 0


def test_complete_encounter_financial_states_and_accounting_zero_write(a4_app):
    _app, accounting_path = a4_app
    patient_id, appointment_id = _enroll_and_appointment()
    _start_and_complete(patient_id, appointment_id)
    before = _sha256(accounting_path)

    service = SpecialistFinancialReconciliationService(
        clock=lambda: datetime(2026, 7, 26, 10, 10, 0)
    )
    first = service.reconcile_all()
    assert first["issues"] == []
    assert first["changed"] == 1
    latest = SpecialistFinancialFunnelRepository().latest_observations()
    assert len(latest) == 1
    assert latest[0]["collection_state"] == "WAITING_FOR_INVOICE_CLOSURE"
    assert _sha256(accounting_path) == before

    accounting = sqlite3.connect(accounting_path)
    accounting.execute(
        """UPDATE invoices SET status='closed', closed_at='2026-07-26 11:00:00'
           WHERE id=20"""
    )
    accounting.execute(
        """INSERT INTO invoice_item_payments
           (invoice_id,item_type,item_id,is_paid) VALUES (20,'visit',201,1)"""
    )
    accounting.commit()
    accounting.close()
    closed_partial_hash = _sha256(accounting_path)

    second = SpecialistFinancialReconciliationService(
        clock=lambda: datetime(2026, 7, 26, 11, 5, 0)
    ).reconcile_all()
    assert second["changed"] == 1
    latest = SpecialistFinancialFunnelRepository().latest_observations()[0]
    assert latest["collection_state"] == "PARTIALLY_COLLECTED"
    assert latest["billed_amount"] == 1500000
    assert latest["collected_amount"] == 1000000
    assert latest["paid_item_count"] == 1
    assert latest["billable_item_count"] == 2
    assert _sha256(accounting_path) == closed_partial_hash

    accounting = sqlite3.connect(accounting_path)
    accounting.execute(
        """INSERT INTO invoice_item_payments
           (invoice_id,item_type,item_id,is_paid) VALUES (20,'procedure',202,1)"""
    )
    accounting.commit()
    accounting.close()
    fully_paid_hash = _sha256(accounting_path)

    third = SpecialistFinancialReconciliationService(
        clock=lambda: datetime(2026, 7, 26, 11, 20, 0)
    ).reconcile_all()
    assert third["changed"] == 1
    fourth = SpecialistFinancialReconciliationService(
        clock=lambda: datetime(2026, 7, 26, 11, 21, 0)
    ).reconcile_all()
    assert fourth["changed"] == 0
    latest = SpecialistFinancialFunnelRepository().latest_observations()[0]
    assert latest["collection_state"] == "COLLECTED"
    assert latest["collected_amount"] == 1500000
    assert _sha256(accounting_path) == fully_paid_hash

    totals = SpecialistFinancialFunnelRepository().finance_totals()
    assert totals == {
        "visits": 1000000,
        "injections": 0,
        "procedures": 500000,
        "total": 1500000,
        "collected": 1500000,
        "invoices": 1,
    }
    funnel = SpecialistFinancialFunnelRepository().funnel_summary()
    assert funnel["booked"] == 1
    assert funnel["attended"] == 1
    assert funnel["service_completed"] == 1
    assert funnel["invoice_closed"] == 1
    assert funnel["collected"] == 1

    # Historical invoice 10 is visible through accounting history but never observed as
    # specialist revenue because no attributed completed Encounter exists for it.
    assert {row["accounting_invoice_id"] for row in SpecialistFinancialFunnelRepository().latest_observations()} == {20}


def test_dashboard_publishes_only_fresh_completed_encounter_observations(a4_app):
    patient_id, appointment_id = _enroll_and_appointment()
    _start_and_complete(patient_id, appointment_id)
    accounting_path = a4_app[1]
    db = sqlite3.connect(accounting_path)
    db.execute(
        """UPDATE invoices SET status='closed', closed_at='2026-07-26 11:00:00'
           WHERE id=20"""
    )
    db.execute(
        """INSERT INTO invoice_item_payments
           (invoice_id,item_type,item_id,is_paid) VALUES
           (20,'visit',201,1),(20,'procedure',202,1)"""
    )
    db.commit()
    db.close()

    missing = RevenueService(
        clock=lambda: datetime(2026, 7, 26, 11, 2, 0)
    ).dashboard()
    assert missing["available"] is False
    assert missing["error_code"] == "FINANCIAL_RECONCILIATION_INCOMPLETE"

    SpecialistFinancialReconciliationService(
        clock=lambda: datetime(2026, 7, 26, 11, 3, 0)
    ).reconcile_all()
    dashboard = RevenueService(
        clock=lambda: datetime(2026, 7, 26, 11, 5, 0)
    ).dashboard()
    assert dashboard["available"] is True
    assert dashboard["total"]["total"] == 1500000
    assert dashboard["total"]["collected"] == 1500000
    assert dashboard["total"]["invoices"] == 1
    assert dashboard["scope"]["eligible_invoices"] == 1
    assert dashboard["scope"]["missing_observations"] == 0
    assert dashboard["funnel"]["service_completed"] == 1

    stale = RevenueService(
        clock=lambda: datetime(2026, 7, 26, 11, 30, 0)
    ).dashboard()
    assert stale["available"] is False
    assert stale["error_code"] == "FINANCIAL_OBSERVATION_STALE"


def test_financial_observation_rows_are_append_only(a4_app):
    from src.adapters.sqlite.core import get_db

    patient_id, appointment_id = _enroll_and_appointment()
    _start_and_complete(patient_id, appointment_id)
    SpecialistFinancialReconciliationService(
        clock=lambda: datetime(2026, 7, 26, 10, 10, 0)
    ).reconcile_all()
    observation = SpecialistFinancialFunnelRepository().latest_observations()[0]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        get_db().execute(
            "UPDATE specialist_financial_observations SET billed_amount=0 WHERE id=?",
            (int(observation["id"]),),
        )
    get_db().rollback()


def test_observation_cannot_be_recorded_before_encounter_completion(a4_app):
    from src.adapters import specialist_accounting_invoice_reader

    patient_id, appointment_id = _enroll_and_appointment()
    DoctorQueueService(work_date_provider=lambda: "2026-07-26").start(
        {"accounting_invoice_id": 20},
        actor_username="doctor",
        appointment_id=appointment_id,
    )
    assert SpecialistFinancialFunnelRepository().eligible_invoice_contexts() == []
    snapshot = specialist_accounting_invoice_reader.invoice_financial_snapshot(20)
    encounter = CareJourneyRepository().encounter_for_invoice(20)
    fake_context = {
        "accounting_invoice_id": 20,
        "accounting_patient_id": 1,
        "patient_link_id": patient_id,
        "journey_id": encounter["journey_id"],
        "encounter_id": encounter["encounter_id"],
        "encounter_completion_event_id": CareJourneyRepository().current_encounter_event(
            encounter["encounter_id"]
        )["id"],
        "appointment_id": appointment_id,
    }
    with pytest.raises(sqlite3.IntegrityError, match="scope mismatch"):
        SpecialistFinancialFunnelRepository().record_observation_once(
            context=fake_context,
            snapshot=snapshot,
            observed_at="2026-07-26 10:00:00",
        )
