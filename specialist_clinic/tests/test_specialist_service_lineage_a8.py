from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3

import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accounting_db(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY,
            full_name TEXT,
            national_id TEXT UNIQUE,
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
            insurance_type TEXT,
            supplementary_insurance TEXT,
            total_amount INTEGER,
            work_date TEXT,
            opened_at TEXT,
            closed_at TEXT
        );
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            doctor_name TEXT,
            visit_date TEXT,
            work_date TEXT,
            status TEXT,
            price INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL,
            doctor_id INTEGER
        );
        CREATE TABLE injections (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            injection_type TEXT,
            injection_date TEXT,
            work_date TEXT,
            count INTEGER,
            unit_price INTEGER,
            total_price INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL,
            nurse_id INTEGER
        );
        CREATE TABLE procedures (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            procedure_type TEXT,
            procedure_date TEXT,
            work_date TEXT,
            price INTEGER NOT NULL,
            invoice_id INTEGER NOT NULL,
            performer_type TEXT,
            performer_id INTEGER
        );
        CREATE TABLE invoice_item_payments (
            invoice_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            payment_type TEXT,
            is_paid INTEGER DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY(invoice_id,item_type,item_id)
        );
        INSERT INTO patients
          (id,full_name,national_id,phone_number,gender,birthdate,address,
           insurance_type,is_foreign)
        VALUES (1,'A8 Patient','A800000001','09120000001','female',
                '1980-01-01','Tehran','base',0);
        INSERT INTO invoices
          (id,patient_id,status,insurance_type,supplementary_insurance,
           total_amount,work_date,opened_at,closed_at)
        VALUES (101,1,'closed','base','supp',900000,'2026-07-26',
                '2026-07-26 09:00:00','2026-07-26 10:00:00'),
               (102,1,'closed','base',NULL,400000,'2026-07-26',
                '2026-07-26 11:00:00','2026-07-26 12:00:00');
        INSERT INTO visits
          (id,patient_id,doctor_name,visit_date,work_date,status,price,
           invoice_id,doctor_id)
        VALUES (11,1,'Dr A','2026-07-26 09:10:00','2026-07-26','done',
                400000,101,7),
               (21,1,'Dr B','2026-07-26 11:10:00','2026-07-26','done',
                400000,102,8);
        INSERT INTO injections
          (id,patient_id,injection_type,injection_date,work_date,count,
           unit_price,total_price,invoice_id,nurse_id)
        VALUES (12,1,'تزریق عضلانی','2026-07-26 09:30:00','2026-07-26',
                2,100000,200000,101,4);
        INSERT INTO procedures
          (id,patient_id,procedure_type,procedure_date,work_date,price,
           invoice_id,performer_type,performer_id)
        VALUES (13,1,'پانسمان','2026-07-26 09:40:00','2026-07-26',
                300000,101,'nurse',4);
        INSERT INTO invoice_item_payments VALUES
          (101,'visit',11,'cash',1,'2026-07-26 10:00:00'),
          (101,'injection',12,'card',1,'2026-07-26 10:00:00'),
          (101,'procedure',13,'insurance',1,'2026-07-26 10:00:00'),
          (102,'visit',21,'cash',1,'2026-07-26 12:00:00');
        """
    )
    db.commit()
    db.close()


@pytest.fixture()
def a8_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.app import create_app

    accounting = tmp_path / "accounting-a8.db"
    specialist = tmp_path / "specialist-a8.db"
    _accounting_db(accounting)
    monkeypatch.setenv("ACCOUNTING_DB_PATH", str(accounting))
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(specialist),
            "ACCOUNTING_DB_PATH": str(accounting),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "a8-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app, accounting, specialist
    context.pop()
    core._initialized = False


def _enroll_and_complete(invoice_id: int) -> tuple[int, dict]:
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.common.utils import iran_now
    from src.services.patient_service import PatientService

    patient_id = int(PatientService().enroll_from_accounting(1, "pytest-a8"))
    when = iran_now()
    repository = CareJourneyRepository()
    encounter = repository.create_invoice_encounter_once(
        patient_link_id=patient_id,
        accounting_invoice_id=invoice_id,
        actor_username="pytest-a8",
        effective_at=when,
    )
    repository.start_encounter(
        encounter["encounter_id"],
        actor_username="pytest-a8",
        effective_at=when,
    )
    repository.attribute_invoice_once(
        accounting_invoice_id=invoice_id,
        accounting_patient_id=1,
        patient_link_id=patient_id,
        encounter_id=encounter["encounter_id"],
        actor_username="pytest-a8",
        effective_at=when,
    )
    repository.complete_encounter(
        encounter["encounter_id"],
        actor_username="pytest-a8",
        effective_at=when,
        note="A8 completed service.",
    )
    return patient_id, encounter


def test_strict_bundle_and_atomic_lineage_are_read_only(a8_app):
    from src.adapters import specialist_accounting_invoice_reader as reader
    from src.adapters.sqlite.specialist_service_lineage_repo import (
        SpecialistServiceLineageRepository,
    )
    from src.services.specialist_financial_reconciliation_service import (
        SpecialistFinancialReconciliationService,
    )

    _app, accounting, _specialist = a8_app
    patient_id, encounter = _enroll_and_complete(101)
    before = _sha256(accounting)
    bundle = reader.invoice_reconciliation_bundle(101)
    assert _sha256(accounting) == before
    assert bundle["financial"]["billable_item_count"] == 3
    assert bundle["financial"]["billed_amount"] == 900000
    assert bundle["services"]["expected_line_count"] == 3
    assert sum(line["total_amount"] for line in bundle["services"]["lines"]) == 900000
    assert [line["item_type"] for line in bundle["services"]["lines"]] == [
        "VISIT", "INJECTION", "PROCEDURE"
    ]
    assert bundle["services"]["lines"][0]["performer_name"] == "Dr A"
    assert bundle["services"]["lines"][1]["description"] == "تزریق عضلانی"
    assert bundle["services"]["lines"][2]["description"] == "پانسمان"

    result = SpecialistFinancialReconciliationService().reconcile_invoice(101)
    assert _sha256(accounting) == before
    assert result["service_manifest_status"] == "COMPLETE"
    assert result["service_line_count"] == 3
    lines = SpecialistServiceLineageRepository().current_lines_for_patient(patient_id)
    assert len(lines) == 3
    assert {line["encounter_id"] for line in lines} == {encounter["encounter_id"]}


def test_service_storage_is_append_only_and_scope_guarded(a8_app):
    import sqlite3 as sqlite

    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.specialist_service_lineage_repo import (
        SpecialistServiceLineageConflict,
        SpecialistServiceLineageRepository,
    )
    from src.services.specialist_financial_reconciliation_service import (
        SpecialistFinancialReconciliationService,
    )

    _enroll_and_complete(101)
    SpecialistFinancialReconciliationService().reconcile_invoice(101)
    repository = SpecialistServiceLineageRepository()
    manifest = repository.current_manifest(101)
    lines = repository.lines_for_snapshot(manifest["snapshot_id"])
    db = get_db()
    with pytest.raises(sqlite.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE specialist_service_line_observations SET description='x' WHERE id=?",
            (lines[0]["id"],),
        )
    db.rollback()
    observation = db.execute(
        "SELECT * FROM specialist_financial_observations WHERE id=?",
        (manifest["financial_observation_id"],),
    ).fetchone()
    with pytest.raises(SpecialistServiceLineageConflict, match="SERVICE_INVOICE"):
        repository.attach_snapshot(
            observation=dict(observation),
            service_snapshot={
                "status": "COMPLETE",
                "accounting_invoice_id": 999,
                "accounting_patient_id": 1,
                "expected_line_count": 0,
                "expected_total_amount": 0,
                "evidence_code": "ACCOUNTING_SERVICE_LINES_V1",
                "source_fingerprint": "a" * 64,
                "lines": [],
            },
        )


def test_invalid_service_bundle_rolls_back_all_local_evidence(a8_app):
    from src.adapters.sqlite.core import get_db
    from src.services.specialist_financial_reconciliation_service import (
        SpecialistFinancialReconciliationService,
    )

    _enroll_and_complete(102)

    class BrokenReader:
        @staticmethod
        def invoice_reconciliation_bundle(invoice_id):
            assert invoice_id == 102
            return {
                "financial": {
                    "accounting_invoice_id": 102,
                    "accounting_patient_id": 1,
                    "invoice_status": "closed",
                    "work_date": "2026-07-26",
                    "closed_at": "2026-07-26 12:00:00",
                    "source_total_amount": 400000,
                    "visits_billed": 400000,
                    "injections_billed": 0,
                    "procedures_billed": 0,
                    "billed_amount": 400000,
                    "visits_collected": 400000,
                    "injections_collected": 0,
                    "procedures_collected": 0,
                    "collected_amount": 400000,
                    "billable_item_count": 1,
                    "paid_item_count": 1,
                    "collection_state": "COLLECTED",
                    "source_fingerprint": "b" * 64,
                    "patient_cash_collected": 400000,
                    "patient_card_collected": 0,
                    "insurance_collected": 0,
                    "unknown_collected": 0,
                    "unpaid_amount": 0,
                    "unknown_payment_type_count": 0,
                    "payer_breakdown_evidence": "ACCOUNTING_ITEM_PAYMENT_TYPE_V1",
                },
                "services": {
                    "status": "COMPLETE",
                    "accounting_invoice_id": 102,
                    "accounting_patient_id": 1,
                    "expected_line_count": 2,
                    "expected_total_amount": 400000,
                    "evidence_code": "ACCOUNTING_SERVICE_LINES_V1",
                    "source_fingerprint": "c" * 64,
                    "lines": [],
                },
            }

    with pytest.raises(Exception, match="SERVICE_FINANCIAL_ITEM_COUNT_MISMATCH"):
        SpecialistFinancialReconciliationService(reader=BrokenReader()).reconcile_invoice(102)
    db = get_db()
    assert db.execute(
        "SELECT COUNT(*) FROM specialist_financial_observations WHERE accounting_invoice_id=102"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM specialist_financial_review_events WHERE accounting_invoice_id=102"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM specialist_service_snapshot_manifests WHERE accounting_invoice_id=102"
    ).fetchone()[0] == 0


def test_changed_service_description_supersedes_without_mutating_history(a8_app):
    from src.adapters.sqlite.specialist_service_lineage_repo import (
        SpecialistServiceLineageRepository,
    )
    from src.services.specialist_financial_reconciliation_service import (
        SpecialistFinancialReconciliationService,
    )

    _app, accounting, _specialist = a8_app
    patient_id, _encounter = _enroll_and_complete(101)
    service = SpecialistFinancialReconciliationService()
    first = service.reconcile_invoice(101)
    repository = SpecialistServiceLineageRepository()
    first_manifest = repository.current_manifest(101)

    db = sqlite3.connect(accounting)
    db.execute("UPDATE procedures SET procedure_type='تعویض پانسمان' WHERE id=13")
    db.commit()
    db.close()

    second = service.reconcile_invoice(101)
    second_manifest = repository.current_manifest(101)
    assert first["observation_id"] == second["observation_id"]
    assert second_manifest["snapshot_id"] != first_manifest["snapshot_id"]
    assert second_manifest["supersedes_snapshot_id"] == first_manifest["snapshot_id"]
    assert repository.lines_for_snapshot(first_manifest["snapshot_id"])[2]["description"] == "پانسمان"
    current = repository.current_lines_for_patient(patient_id)
    assert current[2]["description"] == "تعویض پانسمان"


def test_legacy_reader_creates_unavailable_manifest_without_invented_lines(a8_app):
    from src.adapters import specialist_accounting_invoice_reader as reader
    from src.adapters.sqlite.specialist_service_lineage_repo import (
        SpecialistServiceLineageRepository,
    )
    from src.services.specialist_financial_reconciliation_service import (
        SpecialistFinancialReconciliationService,
    )

    patient_id, _encounter = _enroll_and_complete(102)

    class LegacyReader:
        @staticmethod
        def invoice_financial_snapshot(invoice_id):
            return reader.invoice_financial_snapshot(invoice_id)

    result = SpecialistFinancialReconciliationService(reader=LegacyReader()).reconcile_invoice(102)
    assert result["service_manifest_status"] == "LEGACY_UNAVAILABLE"
    manifest = SpecialistServiceLineageRepository().current_manifest(102)
    assert manifest["evidence_code"] == "LEGACY_UNAVAILABLE"
    assert SpecialistServiceLineageRepository().lines_for_snapshot(manifest["snapshot_id"]) == []
    assert SpecialistServiceLineageRepository().current_lines_for_patient(patient_id) == []


def test_patient_timeline_uses_exact_lines_and_deduplicates_same_invoice():
    from src.services.patient_cockpit_service import PatientCockpitService

    service_lines = [
        {
            "item_type": "VISIT", "accounting_invoice_id": 101,
            "encounter_id": "enc-1", "description": "ویزیت",
            "performer_name": "Dr A", "performed_at": "2026-07-26 09:10:00",
        },
        {
            "item_type": "INJECTION", "accounting_invoice_id": 101,
            "encounter_id": "enc-1", "description": "تزریق عضلانی",
            "performed_at": "2026-07-26 09:30:00",
        },
        {
            "item_type": "PROCEDURE", "accounting_invoice_id": 101,
            "encounter_id": "enc-1", "description": "پانسمان",
            "performed_at": "2026-07-26 09:40:00",
        },
    ]
    events = PatientCockpitService.timeline(
        appointments=[],
        visits=[{
            "invoice_id": 101,
            "visit_date": "2026-07-26 09:10:00",
            "doctor_name": "Dr A",
        }],
        labs=[],
        followups=[],
        medication_events=[],
        service_lines=service_lines,
    )
    assert len(events) == 3
    assert {event["kind"] for event in events} == {
        "service_visit", "service_injection", "service_procedure"
    }
    assert all(event.get("lineage") == "ACCOUNTING_SERVICE_LINES_V1" for event in events)
