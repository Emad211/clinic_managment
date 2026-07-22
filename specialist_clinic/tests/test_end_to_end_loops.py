"""End-to-end application loops across their real production boundaries.

Loop 1 proves the accounting database is consumed read-only and produces an approved,
idempotent informational outreach message.

Loop 2 proves the current clinical chain:

    reconciled diagnosis + current observation
    -> immutable bundled ruleset
    -> exact engine/ruleset/revision run
    -> recorded presentation
    -> append-only clinician decision

No v1 rule engine, clinical engagement SMS or automatic treatment action is involved.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPECIALIST_ROOT = REPOSITORY_ROOT / "specialist_clinic"
REAL_ACCOUNTING_DB = REPOSITORY_ROOT / "webapp" / "clinic_new.db"
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))
if str(SPECIALIST_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT / "tests"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    yield app, specialist_db, accounting_db
    context.pop()
    core._initialized = False


def _accounting_patient_and_invoice(accounting_db: Path):
    db = sqlite3.connect(accounting_db)
    patient_id = int(
        db.execute(
            """INSERT INTO patients
               (name, family_name, full_name, national_id, phone_number)
               VALUES ('بیمار', 'حسابداری', 'بیمار حسابداری',
                       'E2E-INVOICE-1', '09120000001')"""
        ).lastrowid
    )
    invoice_id = int(
        db.execute(
            """INSERT INTO invoices
               (patient_id, status, total_amount, work_date, closed_at)
               VALUES (?, 'closed', 5000, '2026-06-15',
                       '2026-06-15 10:00:00')""",
            (patient_id,),
        ).lastrowid
    )
    db.commit()
    db.close()
    return patient_id, invoice_id


def _specialist_patient(
    *,
    national_id: str,
    full_name: str,
    phone: str,
    birthdate: str = "1980-01-01",
) -> int:
    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, gender, birthdate,
                enrolled_by, enrolled_at, updated_at)
               VALUES (?, ?, ?, 'female', ?, 'pytest',
                       '2026-01-01 09:00:00', '2026-01-01 09:00:00')""",
            (national_id, full_name, phone, birthdate),
        ).lastrowid
    )
    db.commit()
    return patient_id


class TestInvoiceToApprovedThankYou:
    def _prepare(self, accounting_db: Path):
        from src.adapters.sqlite.core import get_db

        patient_id = _specialist_patient(
            national_id="E2E-INVOICE-1",
            full_name="بیمار حسابداری",
            phone="09120000001",
        )
        _accounting_patient_and_invoice(accounting_db)
        get_db().execute(
            """UPDATE settings SET value='00:00'
               WHERE key='engagement_quiet_start'"""
        )
        get_db().execute(
            """UPDATE settings SET value='23:59'
               WHERE key='engagement_quiet_end'"""
        )
        get_db().commit()
        return patient_id

    def test_closed_invoice_to_approved_simulated_sms_is_idempotent(
        self,
        e2e_app,
    ):
        from src.adapters.sqlite.core import get_db
        from src.services.engagement_service import EngagementService
        from src.services.invoice_sync_service import InvoiceSyncService

        _app, _specialist_db, accounting_db = e2e_app
        patient_id = self._prepare(accounting_db)
        first = InvoiceSyncService().run()
        second = InvoiceSyncService().run()
        db = get_db()

        assert first["new"] == 1
        assert second["new"] == 0
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

        result = EngagementService().approve(
            int(approval["id"]),
            decided_by="admin",
        )
        assert result["ok"] is True
        message = db.execute(
            """SELECT * FROM sms_messages
               WHERE patient_link_id=? ORDER BY id DESC LIMIT 1""",
            (patient_id,),
        ).fetchone()
        assert message["provider_msgid"] == "SIMULATED"
        assert message["status"] == "sent"

    @pytest.mark.skipif(
        not REAL_ACCOUNTING_DB.exists(),
        reason="committed accounting seed DB is absent",
    )
    def test_real_accounting_seed_database_is_unchanged(self, e2e_app):
        before = _sha256(REAL_ACCOUNTING_DB)
        from src.services.invoice_sync_service import InvoiceSyncService

        InvoiceSyncService().run()
        assert _sha256(REAL_ACCOUNTING_DB) == before


class TestCurrentClinicalSafetyChain:
    @staticmethod
    def _prepare_package() -> int:
        from src.services.clinical_engine.package_service import (
            ClinicalRulePackageService,
        )

        service = ClinicalRulePackageService()
        package = service.prepare(actor="pytest")
        frozen = service.approve_and_freeze(
            int(package["id"]),
            reviewer="pytest-physician",
            attested_codes=[
                member["rule_code"] for member in package["members"]
            ],
            note="end-to-end safety contract",
        )
        return int(frozen["id"])

    def test_reconciled_severe_bp_to_presentation_and_decision(
        self,
        e2e_app,
    ):
        from clinical_engine_current_test_support import (
            install_sealed_rollout,
        )
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

        patient_id = _specialist_patient(
            national_id="TEST0001",
            full_name="بیمار زنجیره بالینی",
            phone="09120000002",
        )
        patient_repo = PatientRepository()
        patient_repo.add_condition(
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
            reconciled_at=__import__("datetime").datetime(
                2026, 7, 22, 9, 0, 0
            ),
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

        ruleset_id = self._prepare_package()
        assert install_sealed_rollout() == ruleset_id
        projection = ClinicalEngineReadOnlyFacade().patient_detail(patient_id)

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
        assert recommendation["current_decision"] is None

        before_medications = db.execute(
            """SELECT COUNT(*) AS count FROM patient_medications
               WHERE patient_link_id=?""",
            (patient_id,),
        ).fetchone()["count"]
        decision = ClinicalDecisionService().record(
            patient_link_id=patient_id,
            recommendation_event_id=(
                recommendation["recommendation_event_id"]
            ),
            decision="ACCEPTED",
            actor_user_id=1,
            actor_username="admin",
            expected_current_event_id=None,
        )
        after_medications = db.execute(
            """SELECT COUNT(*) AS count FROM patient_medications
               WHERE patient_link_id=?""",
            (patient_id,),
        ).fetchone()["count"]

        assert decision["decision"] == "ACCEPTED"
        assert before_medications == after_medications == 0
        assert db.execute(
            """SELECT COUNT(*) AS count FROM sms_messages
               WHERE patient_link_id=?""",
            (patient_id,),
        ).fetchone()["count"] == 0
        assert db.execute(
            """SELECT COUNT(*) AS count FROM clinical_recommendation_events
               WHERE event_type='PRESENTED'"""
        ).fetchone()["count"] == 1


def test_sms_compliance_preserves_allowed_language_and_rewrites_price_claims():
    from src.services.sms.compliance import sanitize

    rewritten = sanitize("پیشنهادِ ارزان برای شما")
    assert "ارزان" not in rewritten
    assert "مقرون‌به‌صرفه" in rewritten
    assert sanitize("نسخهٔ آزاد غیربیمه") == "نسخهٔ آزاد غیربیمه"
