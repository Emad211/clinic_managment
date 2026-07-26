from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import uuid

import pytest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _accounting_schema(path: Path) -> None:
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
            status TEXT,
            insurance_type TEXT,
            supplementary_insurance TEXT,
            total_amount REAL,
            work_date TEXT,
            opened_at TEXT,
            closed_at TEXT
        );
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            price REAL,
            invoice_id INTEGER
        );
        CREATE TABLE injections (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            total_price REAL,
            invoice_id INTEGER
        );
        CREATE TABLE procedures (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            price REAL,
            invoice_id INTEGER
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
        """
    )
    db.execute(
        """INSERT INTO patients
           (id,full_name,national_id,phone_number,gender,birthdate,address,
            insurance_type,is_foreign)
           VALUES (1,'A7 Patient','A700000001','09120000001','female',
                   '1980-01-01','Test','base',0)"""
    )
    db.execute(
        """INSERT INTO invoices
           (id,patient_id,status,insurance_type,supplementary_insurance,
            total_amount,work_date,opened_at,closed_at)
           VALUES (101,1,'closed','base','supplementary',1000,
                   '2026-07-26','2026-07-26 09:00:00',
                   '2026-07-26 10:00:00')"""
    )
    db.execute("INSERT INTO visits VALUES (1,1,400,101)")
    db.execute("INSERT INTO injections VALUES (2,1,300,101)")
    db.execute("INSERT INTO procedures VALUES (3,1,200,101)")
    db.execute("INSERT INTO procedures VALUES (4,1,100,101)")
    db.executemany(
        """INSERT INTO invoice_item_payments
           (invoice_id,item_type,item_id,payment_type,is_paid,updated_at)
           VALUES (101,?,?,?,?, '2026-07-26 10:00:00')""",
        [
            ("visit", 1, "cash", 1),
            ("injection", 2, "card", 1),
            ("procedure", 3, "insurance", 1),
            ("procedure", 4, "other", 0),
        ],
    )
    db.commit()
    db.close()


@pytest.fixture()
def a7_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.app import create_app

    accounting = tmp_path / "accounting-a7.db"
    specialist = tmp_path / "specialist-a7.db"
    _accounting_schema(accounting)
    monkeypatch.setenv("ACCOUNTING_DB_PATH", str(accounting))
    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(specialist),
            "ACCOUNTING_DB_PATH": str(accounting),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "a7-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app, accounting, specialist
    context.pop()
    core._initialized = False


def _enroll_and_complete(invoice_id: int = 101) -> tuple[int, dict]:
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.common.utils import iran_now
    from src.services.patient_service import PatientService

    patient_id = int(PatientService().enroll_from_accounting(1, "pytest-a7"))
    # The effective timestamp is captured after enrollment, so it is never before the
    # specialist cutover. Repository recorded_at is generated afterwards, so the same
    # timestamp also cannot be in the future. Equal effective times preserve event order
    # through the append-only event IDs without relying on wall-clock sleeps.
    start = iran_now()
    active = start
    completed = start
    repo = CareJourneyRepository()
    encounter = repo.create_invoice_encounter_once(
        patient_link_id=patient_id,
        accounting_invoice_id=invoice_id,
        actor_username="pytest-a7",
        effective_at=start,
    )
    repo.start_encounter(
        encounter["encounter_id"],
        actor_username="pytest-a7",
        effective_at=active,
    )
    repo.attribute_invoice_once(
        accounting_invoice_id=invoice_id,
        accounting_patient_id=1,
        patient_link_id=patient_id,
        encounter_id=encounter["encounter_id"],
        actor_username="pytest-a7",
        effective_at=active,
    )
    repo.complete_encounter(
        encounter["encounter_id"],
        actor_username="pytest-a7",
        effective_at=completed,
        note="Completed A7 service.",
    )
    return patient_id, encounter


def _reconcile(invoice_id: int = 101) -> dict:
    from src.services.specialist_financial_reconciliation_service import (
        SpecialistFinancialReconciliationService,
    )

    return SpecialistFinancialReconciliationService().reconcile_invoice(invoice_id)


def _review(invoice_id: int, *, with_adjustment: bool) -> dict:
    from src.services.specialist_payer_adjustment_service import (
        SpecialistPayerAdjustmentService,
    )

    service = SpecialistPayerAdjustmentService()
    projection = service.invoice_projection(invoice_id)
    return service.mark_reviewed(
        accounting_invoice_id=invoice_id,
        actor_username="pytest-manager",
        actor_user_id=None,
        with_adjustment=with_adjustment,
        note="Verified against current payment and adjustment evidence.",
        expected_current_event_id=int(projection["review"]["id"]),
        idempotency_key=(
            f"a7-review:{invoice_id}:{projection['observation']['id']}:"
            f"{int(with_adjustment)}"
        ),
    )


def test_read_only_payer_breakdown_and_atomic_review_obligation(a7_app):
    from src.adapters import specialist_accounting_invoice_reader as reader
    from src.adapters.sqlite.core import get_db
    from src.services.specialist_payer_adjustment_service import (
        SpecialistPayerAdjustmentService,
    )

    _app, accounting, _specialist = a7_app
    _enroll_and_complete()
    before = _sha256(accounting)
    snapshot = reader.invoice_financial_snapshot(101)
    assert _sha256(accounting) == before
    assert snapshot["patient_cash_collected"] == 400
    assert snapshot["patient_card_collected"] == 300
    assert snapshot["insurance_collected"] == 200
    assert snapshot["unknown_collected"] == 0
    assert snapshot["unpaid_amount"] == 100
    assert snapshot["unknown_payment_type_count"] == 0

    result = _reconcile()
    assert _sha256(accounting) == before
    assert result["created"] is True
    assert result["payer_breakdown_created"] is True
    assert result["review_created"] is True
    projection = SpecialistPayerAdjustmentService().invoice_projection(101)
    assert projection["measurement_status"] == "FINANCIAL_REVIEW_REQUIRED"
    assert projection["safe_to_sum"] is False
    assert get_db().execute(
        "SELECT COUNT(*) FROM specialist_financial_observations"
    ).fetchone()[0] == 1
    assert get_db().execute(
        "SELECT COUNT(*) FROM specialist_payer_breakdown_observations"
    ).fetchone()[0] == 1
    assert get_db().execute(
        "SELECT COUNT(*) FROM specialist_financial_review_events"
    ).fetchone()[0] == 1

    _review(101, with_adjustment=False)
    projection = SpecialistPayerAdjustmentService().invoice_projection(101)
    assert projection["measurement_status"] == "READY"
    assert projection["adjusted_collected"] == 900
    assert projection["payer_breakdown"]["insurance_collected"] == 200


def test_adjustment_requires_evidence_and_reopens_review(a7_app):
    import sqlite3 as sqlite

    from src.adapters.sqlite.core import get_db
    from src.services.specialist_payer_adjustment_service import (
        SpecialistFinancialReviewValidationError,
        SpecialistPayerAdjustmentService,
    )

    _enroll_and_complete()
    _reconcile()
    _review(101, with_adjustment=False)
    service = SpecialistPayerAdjustmentService()

    with pytest.raises(
        SpecialistFinancialReviewValidationError,
        match="must reduce collection",
    ):
        service.record_adjustment(
            accounting_invoice_id=101,
            adjustment_type="REFUND",
            signed_amount=100,
            evidence_type="BANK_REFERENCE",
            evidence_ref="BANK-INVALID",
            actor_username="pytest-manager",
            actor_user_id=None,
        )
    with pytest.raises(
        SpecialistFinancialReviewValidationError,
        match="evidence reference",
    ):
        service.record_adjustment(
            accounting_invoice_id=101,
            adjustment_type="REFUND",
            signed_amount=-100,
            evidence_type="BANK_REFERENCE",
            evidence_ref="",
            actor_username="pytest-manager",
            actor_user_id=None,
        )

    event = service.record_adjustment(
        accounting_invoice_id=101,
        adjustment_type="REFUND",
        signed_amount=-100,
        evidence_type="BANK_REFERENCE",
        evidence_ref="BANK-REFUND-101",
        actor_username="pytest-manager",
        actor_user_id=None,
        note="Refund verified in bank statement.",
        idempotency_key="a7-refund-101",
    )
    projection = service.invoice_projection(101)
    assert projection["measurement_status"] == "FINANCIAL_REVIEW_REQUIRED"
    assert projection["adjustment_total"] == -100
    assert projection["adjusted_collected"] == 800
    _review(101, with_adjustment=True)
    projection = service.invoice_projection(101)
    assert projection["safe_to_sum"] is True
    assert projection["adjusted_collected"] == 800

    with pytest.raises(sqlite.IntegrityError, match="append-only"):
        get_db().execute(
            "UPDATE specialist_financial_adjustment_events "
            "SET signed_amount=-50 WHERE id=?",
            (event["id"],),
        )
    get_db().rollback()


def test_adjustment_reversal_forces_unique_review_reopen(a7_app):
    from src.services.specialist_payer_adjustment_service import (
        SpecialistPayerAdjustmentService,
    )

    _enroll_and_complete()
    _reconcile()
    service = SpecialistPayerAdjustmentService()
    adjustment = service.record_adjustment(
        accounting_invoice_id=101,
        adjustment_type="CHARGEBACK",
        signed_amount=-200,
        evidence_type="BANK_REFERENCE",
        evidence_ref="CHARGEBACK-101",
        actor_username="pytest-manager",
        actor_user_id=None,
        idempotency_key="a7-chargeback-101",
    )
    _review(101, with_adjustment=True)
    reviewed = service.invoice_projection(101)["review"]
    reversed_event = service.reverse_adjustment(
        adjustment_id=adjustment["adjustment_id"],
        actor_username="pytest-manager",
        actor_user_id=None,
        note="Chargeback notice was cancelled by the bank.",
        expected_current_event_id=int(adjustment["id"]),
        idempotency_key="a7-chargeback-reverse-101",
    )
    assert reversed_event["status"] == "REVERSED"
    projection = service.invoice_projection(101)
    assert projection["review"]["id"] != reviewed["id"]
    assert projection["review"]["event_type"] == "REOPENED"
    assert projection["measurement_status"] == "FINANCIAL_REVIEW_REQUIRED"
    assert projection["adjustment_total"] == 0
    _review(101, with_adjustment=False)
    assert service.invoice_projection(101)["adjusted_collected"] == 900


def test_new_accounting_snapshot_reopens_review_and_stales_old_adjustment(a7_app):
    from src.services.specialist_payer_adjustment_service import (
        SpecialistFinancialReviewValidationError,
        SpecialistPayerAdjustmentService,
    )

    _app, accounting, _specialist = a7_app
    _enroll_and_complete()
    _reconcile()
    service = SpecialistPayerAdjustmentService()
    adjustment = service.record_adjustment(
        accounting_invoice_id=101,
        adjustment_type="REFUND",
        signed_amount=-100,
        evidence_type="RECEIPT_DOCUMENT",
        evidence_ref="REFUND-OLD-SNAPSHOT",
        actor_username="pytest-manager",
        actor_user_id=None,
        idempotency_key="a7-old-refund",
    )
    _review(101, with_adjustment=True)

    db = sqlite3.connect(accounting)
    db.execute(
        """UPDATE invoice_item_payments
           SET is_paid=1,payment_type='card',updated_at='2026-07-26 12:00:00'
           WHERE invoice_id=101 AND item_type='procedure' AND item_id=4"""
    )
    db.commit()
    db.close()
    result = _reconcile()
    assert result["created"] is True
    projection = service.invoice_projection(101)
    assert projection["measurement_status"] == "ADJUSTMENT_OBSERVATION_STALE"
    assert projection["review"]["event_type"] == "REOPENED"
    assert projection["gross_collected"] == 1000
    assert projection["adjustment_total"] == 0
    with pytest.raises(
        SpecialistFinancialReviewValidationError,
        match="older financial observation",
    ):
        _review(101, with_adjustment=True)

    corrected = service.record_adjustment(
        accounting_invoice_id=101,
        adjustment_type="REFUND",
        signed_amount=-50,
        evidence_type="RECEIPT_DOCUMENT",
        evidence_ref="REFUND-CURRENT-SNAPSHOT",
        actor_username="pytest-manager",
        actor_user_id=None,
        adjustment_id=adjustment["adjustment_id"],
        expected_current_event_id=int(adjustment["id"]),
        note="Refund amount corrected after current accounting snapshot.",
        idempotency_key="a7-refund-current-correction",
    )
    assert corrected["event_type"] == "CORRECTED"
    _review(101, with_adjustment=True)
    projection = service.invoice_projection(101)
    assert projection["measurement_status"] == "READY"
    assert projection["adjusted_collected"] == 950


def test_legacy_snapshot_falls_back_to_unknown_payer_without_guessing(a7_app):
    from src.adapters.sqlite.specialist_financial_funnel_repo import (
        SpecialistFinancialFunnelRepository,
    )
    from src.services.specialist_payer_adjustment_service import (
        SpecialistPayerAdjustmentService,
    )

    patient_id, encounter = _enroll_and_complete()
    funnel = SpecialistFinancialFunnelRepository()
    context = next(
        row
        for row in funnel.eligible_invoice_contexts()
        if int(row["accounting_invoice_id"]) == 101
    )
    fingerprint = hashlib.sha256(b"legacy-a7").hexdigest()
    snapshot = {
        "accounting_invoice_id": 101,
        "accounting_patient_id": 1,
        "invoice_status": "closed",
        "work_date": "2026-07-26",
        "closed_at": "2026-07-26 10:00:00",
        "source_total_amount": 1000,
        "visits_billed": 1000,
        "injections_billed": 0,
        "procedures_billed": 0,
        "billed_amount": 1000,
        "visits_collected": 900,
        "injections_collected": 0,
        "procedures_collected": 0,
        "collected_amount": 900,
        "billable_item_count": 1,
        "paid_item_count": 1,
        "collection_state": "PARTIALLY_COLLECTED",
        "source_fingerprint": fingerprint,
    }
    observation, _ = funnel.record_observation_once(
        context=context,
        snapshot=snapshot,
        observed_at="2026-07-26 11:05:00",
        created_by="legacy-test",
    )
    evidence = SpecialistPayerAdjustmentService().attach_reconciliation_evidence(
        observation=observation,
        snapshot=snapshot,
        observed_at="2026-07-26 11:05:00",
        actor_username="legacy-test",
    )
    breakdown = evidence["breakdown"]
    assert breakdown["evidence_code"] == "LEGACY_UNAVAILABLE"
    assert breakdown["unknown_collected"] == 900
    assert breakdown["patient_cash_collected"] == 0
    assert breakdown["insurance_collected"] == 0


def test_campaign_roi_is_blocked_until_current_adjustment_review(a7_app):
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsRepository,
    )
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
    from src.adapters.sqlite.sms_repo import SmsRepository
    from src.services.campaign_economics_service import CampaignEconomicsService
    from src.services.campaign_management_service import CampaignManagementService
    from src.services.sms.governance_service import SmsGovernanceService

    patient_id, encounter = _enroll_and_complete()
    consent = SmsGovernanceService()
    current = consent.summary(patient_id)["MARKETING"]
    consent.record(
        patient_link_id=patient_id,
        purpose="MARKETING",
        decision="GRANTED",
        actor_username="pytest-a7",
        actor_user_id=None,
        source_code="PATIENT_EXPLICIT_OPT_IN",
        idempotency_key="a7-marketing-optin",
        expected_current_event_id=int(current["id"]),
        note="Explicit opt-in for A7 campaign test.",
    )
    campaign_id = CampaignManagementService().create(
        name="A7 ROI",
        body="سلام {name}",
        segment="all",
        campaign_type="info",
        credit_amount=0,
        credit_expires_days=None,
        holdout_percent=0,
        scheduled_at=None,
        created_by="pytest-a7",
    )
    economics = CampaignEconomicsService()
    prepared = economics.prepare_execution(
        campaign_id, actor_username="pytest-a7"
    )
    assert prepared["members"]
    governed = consent.require_allowed(
        patient_link_id=patient_id,
        purpose="MARKETING",
    )
    dispatch = SmsDispatchRepository()
    message_id, _ = dispatch.create_message(
        campaign_id=campaign_id,
        patient_link_id=patient_id,
        recipient="09120000001",
        body="سلام A7 Patient",
        provider_name="kavenegar",
        idempotency_key="a7-roi-message",
        source_type="campaign",
        source_ref=str(campaign_id),
        purpose="MARKETING",
        consent_event_id=governed.event_id,
        consent_decision=governed.decision,
        source_policy="A7_TEST",
        created_by="pytest-a7",
    )
    assert dispatch.claim_submission(message_id)
    dispatch.record_submission(
        message_id,
        ok=True,
        provider_msgid="a7-provider-message",
        delivery_status="Accepted",
    )
    dispatch.record_delivery(message_id, status="Delivered", status_int=10)
    SmsRepository().set_setting("sms_cost_per_part_kavenegar_toman", "100")
    economics.record_cost_for_message(message_id)
    response = economics.record_response(
        campaign_id=campaign_id,
        patient_link_id=patient_id,
        response_type="POSITIVE",
        evidence_type="PATIENT_STATED",
        actor_username="pytest-a7",
        idempotency_key="a7-positive-response",
        message_id=message_id,
        note="Patient requested the visit.",
    )
    economics.attribute_response_to_journey(
        response_event_id=int(response["id"]),
        journey_id=encounter["journey_id"],
        actor_username="pytest-a7",
        idempotency_key="a7-response-journey",
    )
    _reconcile()
    economics.reconcile_campaign_state(campaign_id)
    projection = CampaignEconomicsRepository().campaign_projection(campaign_id)
    assert projection["measurement_status"] == (
        "FINANCIAL_ADJUSTMENT_REVIEW_REQUIRED"
    )
    assert projection["safe_to_sum"] is False
    _review(101, with_adjustment=False)
    projection = CampaignEconomicsRepository().campaign_projection(campaign_id)
    assert projection["measurement_status"] == "READY"
    assert projection["finance"]["gross_collected"] == 900
    assert projection["finance"]["collected"] == 900
    assert projection["net_contribution"] == 800
