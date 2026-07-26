from __future__ import annotations

import hashlib
import sqlite3
import uuid

import pytest


@pytest.fixture()
def a6_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "campaign-a6.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "campaign-a6-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(
    *,
    name: str,
    phone: str | None,
    national_id: str,
    marketing: bool = False,
) -> int:
    from src.services.patient_service import PatientService
    from src.services.sms.governance_service import SmsGovernanceService

    patient_id = PatientService().enroll_manual(
        full_name=name,
        national_id=national_id,
        phone_number=phone,
        gender=None,
        birthdate=None,
        address=None,
        enrolled_by="pytest-a6",
    )
    assert patient_id
    if marketing:
        service = SmsGovernanceService()
        current = service.summary(patient_id)["MARKETING"]
        service.record(
            patient_link_id=patient_id,
            purpose="MARKETING",
            decision="GRANTED",
            actor_username="pytest-a6",
            actor_user_id=None,
            source_code="PATIENT_EXPLICIT_OPT_IN",
            idempotency_key=f"marketing-optin:{patient_id}",
            expected_current_event_id=int(current["id"]),
            note="A6 test explicit marketing opt-in.",
        )
    return int(patient_id)


def _campaign(
    *,
    name: str,
    campaign_type: str = "info",
    credit_amount: int = 0,
    holdout_percent: int = 0,
) -> int:
    from src.services.campaign_management_service import CampaignManagementService

    return CampaignManagementService().create(
        name=name,
        body="سلام {name}، پیام آزمایشی کمپین.",
        segment="all",
        campaign_type=campaign_type,
        credit_amount=credit_amount,
        credit_expires_days=30 if credit_amount else None,
        holdout_percent=holdout_percent,
        scheduled_at=None,
        created_by="pytest-a6",
    )


def _freeze(campaign_id: int) -> dict:
    from src.services.campaign_economics_service import CampaignEconomicsService

    return CampaignEconomicsService().prepare_execution(
        campaign_id, actor_username="pytest-a6"
    )


def _governed_message(
    *,
    campaign_id: int,
    patient_id: int,
    provider: str = "kavenegar",
    body: str = "پیام آزمایشی",
    outcome: str = "accepted",
) -> int:
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
    from src.services.sms.governance_service import SmsGovernanceService

    consent = SmsGovernanceService().require_allowed(
        patient_link_id=patient_id,
        purpose="MARKETING",
    )
    dispatch = SmsDispatchRepository()
    message_id, _created = dispatch.create_message(
        campaign_id=campaign_id,
        patient_link_id=patient_id,
        recipient="09121234567",
        body=body,
        provider_name=provider,
        idempotency_key=f"a6-message:{campaign_id}:{patient_id}:{outcome}",
        source_type="campaign",
        source_ref=str(campaign_id),
        purpose="MARKETING",
        consent_event_id=consent.event_id,
        consent_decision=consent.decision,
        source_policy="A6_TEST_FROZEN_AUDIENCE",
        created_by="pytest-a6",
    )
    assert dispatch.claim_submission(message_id)
    if outcome == "accepted":
        dispatch.record_submission(
            message_id,
            ok=True,
            provider_msgid=f"provider-{message_id}",
            delivery_status="Accepted",
        )
    elif outcome == "pending":
        dispatch.record_submission(
            message_id,
            ok=False,
            pending=True,
            delivery_status="SubmissionUnknown",
            error="timeout",
        )
    elif outcome == "failed":
        dispatch.record_submission(
            message_id,
            ok=False,
            delivery_status="Failed",
            error="rejected",
        )
    else:
        raise AssertionError(outcome)
    return int(message_id)


def _scope_patient(patient_id: int, accounting_patient_id: int) -> None:
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        "UPDATE patient_links SET accounting_patient_id=? WHERE id=?",
        (int(accounting_patient_id), int(patient_id)),
    )
    content_hash = hashlib.sha256(
        f"scope:{patient_id}:{accounting_patient_id}".encode("utf-8")
    ).hexdigest()
    db.execute(
        """INSERT INTO specialist_program_enrollments
           (patient_link_id,accounting_patient_id,effective_at,
            accounting_snapshot_at,accounting_invoice_cutoff_id,
            history_policy,created_by,content_hash,created_at)
           VALUES (?,?,'2026-07-26 08:00:00','2026-07-26 08:00:00',0,
                   'VISIBLE_EXCLUDED','pytest-a6',?,'2026-07-26 08:00:00')""",
        (int(patient_id), int(accounting_patient_id), content_hash),
    )
    db.commit()


def _completed_financial_journey(
    *,
    patient_id: int,
    accounting_patient_id: int,
    invoice_id: int,
    billed: int,
    collected: int,
) -> tuple[str, str]:
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.adapters.sqlite.specialist_financial_funnel_repo import (
        SpecialistFinancialFunnelRepository,
    )

    journey_repo = CareJourneyRepository()
    encounter = journey_repo.create_invoice_encounter_once(
        patient_link_id=patient_id,
        accounting_invoice_id=invoice_id,
        actor_username="pytest-a6",
        effective_at="2026-07-26 10:00:00",
    )
    journey_repo.start_encounter(
        encounter["encounter_id"],
        actor_username="pytest-a6",
        effective_at="2026-07-26 10:05:00",
    )
    journey_repo.attribute_invoice_once(
        accounting_invoice_id=invoice_id,
        accounting_patient_id=accounting_patient_id,
        patient_link_id=patient_id,
        encounter_id=encounter["encounter_id"],
        actor_username="pytest-a6",
        effective_at="2026-07-26 10:05:00",
    )
    journey_repo.complete_encounter(
        encounter["encounter_id"],
        actor_username="pytest-a6",
        effective_at="2026-07-26 10:30:00",
        note="Completed specialist service.",
    )
    funnel = SpecialistFinancialFunnelRepository()
    contexts = {
        int(row["accounting_invoice_id"]): row
        for row in funnel.eligible_invoice_contexts()
    }
    context = contexts[int(invoice_id)]
    paid_items = 1 if collected else 0
    collection_state = (
        "COLLECTED"
        if collected == billed and billed > 0
        else "PARTIALLY_COLLECTED"
        if collected > 0
        else "UNPAID"
    )
    fingerprint = hashlib.sha256(
        f"invoice:{invoice_id}:{billed}:{collected}".encode("utf-8")
    ).hexdigest()
    snapshot = {
        "accounting_invoice_id": invoice_id,
        "accounting_patient_id": accounting_patient_id,
        "invoice_status": "closed",
        "work_date": "2026-07-26",
        "closed_at": "2026-07-26 11:00:00",
        "source_total_amount": billed,
        "visits_billed": billed,
        "injections_billed": 0,
        "procedures_billed": 0,
        "billed_amount": billed,
        "visits_collected": collected,
        "injections_collected": 0,
        "procedures_collected": 0,
        "collected_amount": collected,
        "billable_item_count": 1,
        "paid_item_count": paid_items,
        "unpaid_item_count": 0 if paid_items else 1,
        "collection_state": collection_state,
        "patient_cash_collected": 0,
        "patient_card_collected": collected,
        "insurance_collected": 0,
        "unknown_collected": 0,
        "unpaid_amount": max(billed - collected, 0),
        "unknown_payment_type_count": 0,
        "payer_breakdown_evidence": "ACCOUNTING_ITEM_PAYMENT_TYPE_V1",
        "source_fingerprint": fingerprint,
    }
    observation, _created = funnel.record_observation_once(
        context=context,
        snapshot=snapshot,
        observed_at="2026-07-26 11:05:00",
        created_by="pytest-a6",
    )
    from src.services.specialist_payer_adjustment_service import (
        SpecialistPayerAdjustmentService,
    )
    payer = SpecialistPayerAdjustmentService()
    evidence = payer.attach_reconciliation_evidence(
        observation=observation,
        snapshot=snapshot,
        observed_at="2026-07-26 11:05:00",
        actor_username="pytest-a6",
    )
    payer.mark_reviewed(
        accounting_invoice_id=invoice_id,
        actor_username="pytest-a6",
        actor_user_id=None,
        with_adjustment=False,
        note="A6 fixture reviewed with no additional adjustment.",
        expected_current_event_id=int(evidence["review"]["id"]),
        idempotency_key=f"a6-fixture-review:{invoice_id}:{observation['id']}",
    )
    return str(encounter["journey_id"]), str(encounter["encounter_id"])


def test_campaign_creation_and_prepare_are_atomic_and_append_only(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsRepository,
    )
    from src.adapters.sqlite.core import get_db

    _patient(
        name="Eligible",
        phone="09121234567",
        national_id="A600000001",
        marketing=True,
    )
    campaign_id = _campaign(name="Atomic lifecycle")
    repository = CampaignEconomicsRepository()
    current = repository.current_lifecycle(campaign_id)
    assert current["status"] == "DRAFT"
    assert len(repository.lifecycle_history(campaign_id)) == 1

    with pytest.raises(sqlite3.IntegrityError, match="invalid campaign lifecycle"):
        repository.append_lifecycle(
            campaign_id=campaign_id,
            status="COMPLETED",
            actor_username="pytest-a6",
            idempotency_key="invalid-draft-complete",
            execution_id="invalid-execution",
            expected_current_event_id=int(current["id"]),
        )
    get_db().rollback()

    prepared = _freeze(campaign_id)
    assert prepared["lifecycle"]["status"] == "SENDING"
    assert prepared["snapshot"]["source_code"] == "NEW_FROZEN"
    history = repository.lifecycle_history(campaign_id)
    assert [row["status"] for row in history] == ["DRAFT", "PREPARING", "SENDING"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        get_db().execute(
            "UPDATE campaign_lifecycle_events SET status='FAILED' WHERE id=?",
            (history[-1]["id"],),
        )
    get_db().rollback()


def test_audience_is_deterministic_frozen_and_excludes_without_consent(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsRepository,
    )
    from src.adapters.sqlite.core import get_db

    first = _patient(
        name="First",
        phone="09121234561",
        national_id="A600000011",
        marketing=True,
    )
    second = _patient(
        name="Second",
        phone="09121234562",
        national_id="A600000012",
        marketing=True,
    )
    excluded = _patient(
        name="No marketing consent",
        phone="09121234563",
        national_id="A600000013",
        marketing=False,
    )
    campaign_id = _campaign(name="Frozen audience", holdout_percent=50)
    prepared = _freeze(campaign_id)
    snapshot = prepared["snapshot"]
    assert snapshot["candidate_count"] == 3
    assert snapshot["eligible_count"] == 2
    assert snapshot["treated_count"] == 1
    assert snapshot["control_count"] == 1
    assert snapshot["excluded_count"] == 1

    repository = CampaignEconomicsRepository()
    members = repository.audience_members(campaign_id)
    assignments = {int(row["patient_link_id"]): row["assignment"] for row in members}
    assert assignments[excluded] == "EXCLUDED"
    assert {assignments[first], assignments[second]} == {"TREATED", "CONTROL"}
    assert all(
        row["consent_event_id"] is not None
        for row in members
    )

    _patient(
        name="Added after freeze",
        phone="09121234564",
        national_id="A600000014",
        marketing=True,
    )
    second_prepare = _freeze(campaign_id)
    assert second_prepare["snapshot"]["snapshot_id"] == snapshot["snapshot_id"]
    assert repository.audience_summary(campaign_id)["candidate_count"] == 3
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        get_db().execute(
            "UPDATE campaign_audience_members SET assignment='TREATED' WHERE campaign_id=?",
            (campaign_id,),
        )
    get_db().rollback()


def test_positive_response_requires_trusted_treated_member_and_evidence(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsRepository,
    )
    from src.adapters.sqlite.core import get_db
    from src.services.campaign_economics_service import CampaignEconomicsService

    for suffix in (21, 22):
        _patient(
            name=f"Patient {suffix}",
            phone=f"091212345{suffix}",
            national_id=f"A6000000{suffix}",
            marketing=True,
        )
    campaign_id = _campaign(name="Response evidence", holdout_percent=50)
    _freeze(campaign_id)
    repository = CampaignEconomicsRepository()
    members = repository.audience_members(campaign_id)
    treated = next(row for row in members if row["assignment"] == "TREATED")
    control = next(row for row in members if row["assignment"] == "CONTROL")

    with pytest.raises(sqlite3.IntegrityError, match="trusted treated audience"):
        CampaignEconomicsService().record_response(
            campaign_id=campaign_id,
            patient_link_id=int(control["patient_link_id"]),
            response_type="POSITIVE",
            evidence_type="PATIENT_STATED",
            actor_username="pytest-a6",
            idempotency_key="control-positive",
            note="Control patient called.",
        )
    get_db().rollback()

    with pytest.raises(sqlite3.IntegrityError, match="explicit evidence"):
        CampaignEconomicsService().record_response(
            campaign_id=campaign_id,
            patient_link_id=int(treated["patient_link_id"]),
            response_type="POSITIVE",
            evidence_type="PATIENT_STATED",
            actor_username="pytest-a6",
            idempotency_key="missing-positive-evidence",
        )
    get_db().rollback()

    event = CampaignEconomicsService().record_response(
        campaign_id=campaign_id,
        patient_link_id=int(treated["patient_link_id"]),
        response_type="POSITIVE",
        evidence_type="PATIENT_STATED",
        actor_username="pytest-a6",
        idempotency_key="valid-positive-evidence",
        note="Patient explicitly requested an appointment.",
    )
    assert event["response_type"] == "POSITIVE"
    assert repository.current_response(
        campaign_id, int(treated["patient_link_id"])
    )["id"] == event["id"]


def test_legacy_audience_is_visible_but_not_executable(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsRepository,
    )
    from src.services.campaign_economics_service import (
        CampaignEconomicsService,
        CampaignExecutionError,
    )

    patient_id = _patient(
        name="Legacy",
        phone="09121234570",
        national_id="A600000070",
        marketing=True,
    )
    campaign_id = _campaign(name="Legacy audience")
    repository = CampaignEconomicsRepository()
    current = repository.current_lifecycle(campaign_id)
    repository.create_audience_snapshot(
        campaign_id=campaign_id,
        execution_id="legacy-execution-test",
        source_code="LEGACY_BACKFILL_UNTRUSTED",
        segment_key="all",
        purpose="MARKETING",
        holdout_percent=0,
        random_seed="legacy",
        members=[
            {
                "patient_link_id": patient_id,
                "accounting_patient_id": None,
                "assignment": "TREATED",
                "eligibility": "LEGACY_UNKNOWN",
                "finance_scope": "LEGACY_UNKNOWN",
                "consent_event_id": None,
                "consent_decision": "LEGACY_UNKNOWN",
                "recipient_canonical": "09121234570",
                "assigned_rank": 1,
                "exclusion_reason": None,
            }
        ],
        actor_username="pytest-a6",
    )
    assert current["status"] == "DRAFT"
    with pytest.raises(CampaignExecutionError, match="LEGACY_AUDIENCE"):
        CampaignEconomicsService().prepare_execution(
            campaign_id, actor_username="pytest-a6"
        )


def test_wallet_grant_occurs_after_acceptance_and_compensates_non_delivery(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import CampaignEconomicsRepository
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
    from src.adapters.sqlite.sms_repo import SmsRepository
    from src.adapters.sqlite.wallet_repo import WalletRepository
    from src.services.campaign_economics_service import CampaignEconomicsService

    patient_id = _patient(
        name="Wallet",
        phone="09121234571",
        national_id="A600000071",
        marketing=True,
    )
    campaign_id = _campaign(
        name="Wallet accepted",
        campaign_type="wallet_credit",
        credit_amount=100,
    )
    _freeze(campaign_id)
    SmsRepository().set_setting("sms_cost_per_part_kavenegar_toman", "10")
    message_id = _governed_message(
        campaign_id=campaign_id,
        patient_id=patient_id,
        outcome="accepted",
    )
    service = CampaignEconomicsService()
    cost = service.record_cost_for_message(message_id)
    grant = service.ensure_wallet_grant(message_id)
    assert cost["amount"] == 10
    assert grant["status"] == "ACTIVE"
    assert WalletRepository().get_balance(patient_id) == 100
    assert service.ensure_wallet_grant(message_id)["id"] == grant["id"]

    SmsDispatchRepository().record_delivery(
        message_id,
        status="Undelivered",
        status_int=11,
    )
    service.reconcile_campaign_state(campaign_id)
    current = CampaignEconomicsRepository().current_wallet_grant(
        campaign_id, patient_id
    )
    assert current["status"] == "COMPENSATED"
    assert WalletRepository().get_balance(patient_id) == 0
    assert get_db().execute(
        "SELECT COUNT(*) FROM wallet_transactions WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()[0] == 2


def test_wallet_unknown_submission_creates_review_then_resolves_on_delivery(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import CampaignEconomicsRepository
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
    from src.adapters.sqlite.wallet_repo import WalletRepository
    from src.services.campaign_economics_service import CampaignEconomicsService

    patient_id = _patient(
        name="Ambiguous wallet",
        phone="09121234572",
        national_id="A600000072",
        marketing=True,
    )
    campaign_id = _campaign(
        name="Wallet timeout",
        campaign_type="wallet_credit",
        credit_amount=200,
    )
    _freeze(campaign_id)
    message_id = _governed_message(
        campaign_id=campaign_id,
        patient_id=patient_id,
        outcome="pending",
    )
    service = CampaignEconomicsService()
    service.reconcile_campaign_state(campaign_id)
    current = CampaignEconomicsRepository().current_wallet_grant(
        campaign_id, patient_id
    )
    assert current["status"] == "REVIEW_REQUIRED"
    assert WalletRepository().get_balance(patient_id) == 0

    SmsDispatchRepository().record_delivery(
        message_id,
        status="Delivered",
        status_int=10,
    )
    service.reconcile_campaign_state(campaign_id)
    current = CampaignEconomicsRepository().current_wallet_grant(
        campaign_id, patient_id
    )
    assert current["status"] == "ACTIVE"
    assert WalletRepository().get_balance(patient_id) == 200


def test_wallet_failure_after_spend_requires_manual_review(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import CampaignEconomicsRepository
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
    from src.adapters.sqlite.wallet_repo import WalletRepository
    from src.services.campaign_economics_service import CampaignEconomicsService

    patient_id = _patient(
        name="Spent wallet",
        phone="09121234573",
        national_id="A600000073",
        marketing=True,
    )
    campaign_id = _campaign(
        name="Wallet spent",
        campaign_type="wallet_credit",
        credit_amount=100,
    )
    _freeze(campaign_id)
    message_id = _governed_message(
        campaign_id=campaign_id,
        patient_id=patient_id,
        outcome="accepted",
    )
    service = CampaignEconomicsService()
    service.ensure_wallet_grant(message_id)
    WalletRepository().adjust(
        patient_id,
        -50,
        reason="redeem",
        idempotency_key="redeem-after-campaign-grant",
    )
    SmsDispatchRepository().record_delivery(
        message_id,
        status="Undelivered",
        status_int=11,
    )
    service.reconcile_campaign_state(campaign_id)
    current = CampaignEconomicsRepository().current_wallet_grant(
        campaign_id, patient_id
    )
    assert current["status"] == "REVIEW_REQUIRED"
    assert WalletRepository().get_balance(patient_id) == 50


def test_explicit_response_journey_invoice_chain_is_the_only_roi_source(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import CampaignEconomicsRepository
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
    from src.adapters.sqlite.sms_repo import SmsRepository
    from src.services.campaign_economics_service import CampaignEconomicsService
    from src.services.revenue_service import RevenueService

    patient_id = _patient(
        name="ROI patient",
        phone="09121234574",
        national_id="A600000074",
        marketing=True,
    )
    _scope_patient(patient_id, 7401)
    campaign_id = _campaign(name="Explicit ROI")
    prepared = _freeze(campaign_id)
    treated = prepared["members"][0]
    assert int(treated["patient_link_id"]) == patient_id
    SmsRepository().set_setting("sms_cost_per_part_kavenegar_toman", "100")
    message_id = _governed_message(
        campaign_id=campaign_id,
        patient_id=patient_id,
        outcome="accepted",
    )
    dispatch = SmsDispatchRepository()
    dispatch.record_delivery(message_id, status="Delivered", status_int=10)
    service = CampaignEconomicsService()
    service.record_cost_for_message(message_id)
    response = service.record_response(
        campaign_id=campaign_id,
        patient_link_id=patient_id,
        response_type="POSITIVE",
        evidence_type="PATIENT_STATED",
        actor_username="pytest-a6",
        idempotency_key="roi-positive-response",
        message_id=message_id,
        note="Patient requested a specialist visit.",
    )
    journey_id, _encounter_id = _completed_financial_journey(
        patient_id=patient_id,
        accounting_patient_id=7401,
        invoice_id=74001,
        billed=10000,
        collected=10000,
    )
    service.attribute_response_to_journey(
        response_event_id=int(response["id"]),
        journey_id=journey_id,
        actor_username="pytest-a6",
        idempotency_key="roi-response-journey",
    )
    # Another completed, collected invoice for the same patient is not campaign revenue.
    _completed_financial_journey(
        patient_id=patient_id,
        accounting_patient_id=7401,
        invoice_id=74002,
        billed=50000,
        collected=50000,
    )
    reconciled = service.reconcile_campaign_state(campaign_id)
    assert reconciled["lifecycle"]["status"] == "COMPLETED"
    projection = CampaignEconomicsRepository().campaign_projection(campaign_id)
    assert projection["measurement_status"] == "READY"
    assert projection["safe_to_sum"] is True
    assert projection["finance"]["collected"] == 10000
    assert projection["finance"]["invoices"] == 1
    assert projection["costs"]["direct_cost"] == 100
    assert projection["net_contribution"] == 9900
    assert projection["roi_percent"] == 9900.0

    summary = RevenueService().campaign_revenue()
    row = next(row for row in summary["rows"] if row["id"] == campaign_id)
    assert row["revenue"] == 10000
    assert row["net_contribution"] == 9900
    assert summary["safe_to_sum"] is True


def test_response_can_be_attributed_to_only_one_active_journey(a6_app):
    from src.adapters.sqlite.campaign_economics_repo import (
        CampaignEconomicsConflict,
        CampaignEconomicsRepository,
    )
    from src.services.campaign_economics_service import CampaignEconomicsService

    patient_id = _patient(
        name="Exclusive",
        phone="09121234575",
        national_id="A600000075",
        marketing=True,
    )
    _scope_patient(patient_id, 7501)
    campaign_id = _campaign(name="Exclusive attribution")
    prepared = _freeze(campaign_id)
    assert prepared["members"]
    response = CampaignEconomicsService().record_response(
        campaign_id=campaign_id,
        patient_link_id=patient_id,
        response_type="POSITIVE",
        evidence_type="STAFF_PHONE_CALL",
        actor_username="pytest-a6",
        idempotency_key="exclusive-positive",
        note="Patient accepted the invitation during a call.",
    )
    first_journey, _ = _completed_financial_journey(
        patient_id=patient_id,
        accounting_patient_id=7501,
        invoice_id=75001,
        billed=1000,
        collected=1000,
    )
    second_journey, _ = _completed_financial_journey(
        patient_id=patient_id,
        accounting_patient_id=7501,
        invoice_id=75002,
        billed=2000,
        collected=2000,
    )
    service = CampaignEconomicsService()
    first = service.attribute_response_to_journey(
        response_event_id=int(response["id"]),
        journey_id=first_journey,
        actor_username="pytest-a6",
        idempotency_key="exclusive-first",
    )
    with pytest.raises(CampaignEconomicsConflict, match="another journey"):
        service.attribute_response_to_journey(
            response_event_id=int(response["id"]),
            journey_id=second_journey,
            actor_username="pytest-a6",
            idempotency_key="exclusive-second-invalid",
        )
    repository = CampaignEconomicsRepository()
    repository.revoke_journey_attribution(
        journey_id=first_journey,
        actor_username="pytest-a6",
        idempotency_key="exclusive-revoke",
        note="First visit was linked in error.",
        expected_current_event_id=int(first["id"]),
    )
    second = service.attribute_response_to_journey(
        response_event_id=int(response["id"]),
        journey_id=second_journey,
        actor_username="pytest-a6",
        idempotency_key="exclusive-second-corrected",
    )
    assert second["status"] == "ATTRIBUTED"
    assert repository.current_journey_attribution(first_journey)["status"] == "REVOKED"


def test_doctor_queue_campaign_link_is_atomic_and_patient_scoped(a6_app, monkeypatch):
    from src.adapters import accounting_bridge, specialist_accounting_revenue
    from src.adapters.sqlite.campaign_economics_repo import CampaignEconomicsRepository
    from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
    from src.common.utils import today_str
    from src.services.campaign_economics_service import CampaignEconomicsService
    from src.services.doctor_queue_service import DoctorQueueService

    patient_id = _patient(
        name="Queue patient",
        phone="09121234576",
        national_id="A600000076",
        marketing=True,
    )
    other_id = _patient(
        name="Other patient",
        phone="09121234577",
        national_id="A600000077",
        marketing=True,
    )
    _scope_patient(patient_id, 7601)
    _scope_patient(other_id, 7701)
    campaign_id = _campaign(name="Queue attribution")
    _freeze(campaign_id)
    response = CampaignEconomicsService().record_response(
        campaign_id=campaign_id,
        patient_link_id=patient_id,
        response_type="POSITIVE",
        evidence_type="PATIENT_STATED",
        actor_username="pytest-a6",
        idempotency_key="queue-positive",
        note="Patient requested a visit.",
    )
    other_campaign = _campaign(name="Other queue attribution")
    _freeze(other_campaign)
    other_response = CampaignEconomicsService().record_response(
        campaign_id=other_campaign,
        patient_link_id=other_id,
        response_type="POSITIVE",
        evidence_type="PATIENT_STATED",
        actor_username="pytest-a6",
        idempotency_key="queue-other-positive",
        note="Other patient requested a visit.",
    )
    work_date = today_str()

    def invoice_identity(invoice_id: int):
        return {
            "invoice_id": int(invoice_id),
            "patient_id": 7601,
            "status": "open",
            "work_date": work_date,
            "opened_at": f"{work_date} 09:00:00",
            "closed_at": None,
            "total_amount": 0,
        }

    monkeypatch.setattr(specialist_accounting_revenue, "invoice_identity", invoice_identity)
    monkeypatch.setattr(
        accounting_bridge,
        "get_patient_by_id",
        lambda _accounting_id: {
            "id": 7601,
            "national_id": "A600000076",
            "full_name": "Queue patient",
            "phone_number": "09121234576",
        },
    )
    queue = DoctorQueueService(work_date_provider=lambda: work_date)
    visit = queue.start(
        {"accounting_invoice_id": 76001},
        actor_username="pytest-a6",
        campaign_response_event_id=int(response["id"]),
    )
    attribution = CampaignEconomicsRepository().current_journey_attribution(
        visit["journey_id"]
    )
    assert attribution["response_event_id"] == response["id"]

    with pytest.raises(Exception, match="patient mismatch"):
        queue.start(
            {"accounting_invoice_id": 76002},
            actor_username="pytest-a6",
            campaign_response_event_id=int(other_response["id"]),
        )
    assert CareJourneyRepository().encounter_for_invoice(76002) is None
