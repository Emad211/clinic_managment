"""End-to-end loops across current production boundaries only."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPECIALIST_ROOT = REPOSITORY_ROOT / "specialist_clinic"
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
if str(SPECIALIST_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT / "tests"))


def _make_accounting_stub(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            status TEXT DEFAULT 'open',
            total_amount REAL DEFAULT 0,
            work_date TEXT,
            closed_at TEXT,
            opened_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            patient_id INTEGER,
            visit_date TEXT,
            doctor_name TEXT,
            price REAL DEFAULT 0,
            insurance_type TEXT,
            supplementary_insurance TEXT
        );
        CREATE TABLE injections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            patient_id INTEGER,
            injection_type TEXT,
            total_price REAL DEFAULT 0
        );
        CREATE TABLE procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            patient_id INTEGER,
            procedure_type TEXT,
            price REAL DEFAULT 0
        );
        """
    )
    db.commit()
    db.close()


@pytest.fixture()
def e2e_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.app import create_app
    from src.config.settings import Config

    specialist_db = tmp_path / "specialist-e2e.db"
    accounting_db = tmp_path / "accounting-e2e.db"
    _make_accounting_stub(accounting_db)
    monkeypatch.setenv("ACCOUNTING_DB_PATH", str(accounting_db))
    Config.ACCOUNTING_DB_PATH = str(accounting_db)
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(specialist_db),
            "ACCOUNTING_DB_PATH": str(accounting_db),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "e2e-test",
        }
    )
    context = app.app_context()
    context.push()
    core.get_db()
    yield app, accounting_db
    context.pop()
    core._initialized = False


def _specialist_patient(
    *,
    national_id: str,
    full_name: str,
    phone: str,
) -> int:
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, gender, birthdate,
                enrolled_by, enrolled_at, updated_at)
               VALUES (?, ?, ?, 'female', '1980-01-01', 'pytest',
                       '2026-01-01 09:00:00', '2026-01-01 09:00:00')""",
            (national_id, full_name, phone),
        ).lastrowid
    )
    db.commit()
    return patient_id


def test_closed_invoice_to_approved_simulated_sms_is_idempotent(e2e_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_repo import SmsRepository
    from src.services.engagement_service import EngagementService
    from src.services.invoice_sync_service import InvoiceSyncService

    _app, accounting_db = e2e_app
    patient_id = _specialist_patient(
        national_id="E2E-INVOICE-1",
        full_name="بیمار حسابداری",
        phone="09120000001",
    )
    accounting = sqlite3.connect(accounting_db)
    accounting_patient_id = int(
        accounting.execute(
            """INSERT INTO patients
               (name, family_name, full_name, national_id, phone_number)
               VALUES ('بیمار', 'حسابداری', 'بیمار حسابداری',
                       'E2E-INVOICE-1', '09120000001')"""
        ).lastrowid
    )
    accounting.execute(
        """INSERT INTO invoices
           (patient_id, status, total_amount, work_date, closed_at)
           VALUES (?, 'closed', 5000, '2026-06-15',
                   '2026-06-15 10:00:00')""",
        (accounting_patient_id,),
    )
    accounting.commit()
    accounting.close()

    settings = SmsRepository()
    settings.set_setting("engagement_quiet_start", "00:00")
    settings.set_setting("engagement_quiet_end", "23:59")
    assert InvoiceSyncService().run()["new"] == 1
    assert InvoiceSyncService().run()["new"] == 0

    db = get_db()
    approval = db.execute(
        """SELECT * FROM engagement_approvals
           WHERE patient_link_id=? AND event_key='thank_you'""",
        (patient_id,),
    ).fetchone()
    assert approval is not None
    assert db.execute(
        """SELECT COUNT(*) AS count FROM engagement_approvals
           WHERE patient_link_id=? AND event_key='thank_you'""",
        (patient_id,),
    ).fetchone()["count"] == 1

    # Explicit override makes this test independent of Tehran wall-clock while
    # preserving daily-cap, opt-out, provider and idempotency checks.
    result = EngagementService().approve(
        int(approval["id"]),
        decided_by="admin",
        override=True,
    )
    assert result["ok"] is True, result
    message = db.execute(
        """SELECT * FROM sms_messages
           WHERE patient_link_id=? ORDER BY id DESC LIMIT 1""",
        (patient_id,),
    ).fetchone()
    assert message["provider_msgid"] == "SIMULATED"
    assert message["status"] == "sent"


def test_reconciled_severe_bp_to_presentation_and_decision(e2e_app):
    from clinical_engine_current_test_support import install_sealed_rollout
    from src.adapters.sqlite.clinical_reconciliation_repo import (
        ClinicalReconciliationRepository,
    )
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.patients_repo import PatientRepository
    from src.services.clinical_engine.decision_service import (
        ClinicalDecisionService,
    )
    from src.services.clinical_engine.facade import (
        ClinicalEngineReadOnlyFacade,
    )
    from src.services.clinical_engine.fact_builder import ENGINE_VERSION
    from src.services.clinical_engine.runtime import (
        ClinicalEngineRuntimeService,
    )
    from src.services.clinical_engine.package_service import (
        ClinicalRulePackageService,
    )

    patient_id = _specialist_patient(
        national_id="TEST0001",
        full_name="بیمار زنجیره بالینی",
        phone="09120000002",
    )
    PatientRepository().add_condition(
        patient_id,
        1,
        onset_date="2020-01-01",
    )
    ClinicalReconciliationRepository().record(
        patient_link_id=patient_id,
        collection_key="conditions",
        completeness="complete",
        actor_username="pytest-physician",
        source="clinician",
        patient_confirmed=True,
        reconciled_at=datetime(2026, 7, 22, 9, 0, 0),
    )
    db = get_db()
    db.execute(
        """INSERT INTO vital_readings
           (patient_link_id, type, value, unit, measured_at, source,
            recorded_by)
           VALUES (?, 'bp_systolic', 185, 'mmHg',
                   '2026-07-22 09:30:00', 'clinic', 'nurse')""",
        (patient_id,),
    )
    db.commit()

    packages = ClinicalRulePackageService()
    package = packages.prepare(actor="pytest")
    frozen = packages.approve_and_freeze(
        int(package["id"]),
        reviewer="pytest-physician",
        attested_codes=[
            member["rule_code"] for member in package["members"]
        ],
        note="end-to-end safety contract",
    )
    assert install_sealed_rollout() == int(frozen["id"])

    runtime = ClinicalEngineRuntimeService(
        clock=lambda: datetime(2026, 7, 22, 10, 0, 0),
    )
    projection = ClinicalEngineReadOnlyFacade(
        runtime=runtime,
    ).patient_detail(patient_id)
    assert projection["current"] is True
    assert projection["engine_version"] == ENGINE_VERSION
    redflags = [
        item
        for group in projection["groups"]
        if group["action_type"] == "redflag"
        for item in group["items"]
    ]
    assert len(redflags) == 1
    recommendation = redflags[0]
    assert recommendation["suggestion_only"] is True

    before = db.execute(
        "SELECT COUNT(*) AS count FROM patient_medications "
        "WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["count"]
    decision = ClinicalDecisionService().record(
        patient_link_id=patient_id,
        recommendation_event_id=recommendation[
            "recommendation_event_id"
        ],
        decision="ACCEPTED",
        actor_user_id=1,
        actor_username="admin",
        expected_current_event_id=None,
    )
    after = db.execute(
        "SELECT COUNT(*) AS count FROM patient_medications "
        "WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["count"]

    assert decision["decision"] == "ACCEPTED"
    assert before == after == 0
    assert db.execute(
        "SELECT COUNT(*) AS count FROM sms_messages "
        "WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()["count"] == 0
    assert db.execute(
        """SELECT COUNT(*) AS count
           FROM clinical_recommendation_events
           WHERE event_type='PRESENTED'"""
    ).fetchone()["count"] == 1
