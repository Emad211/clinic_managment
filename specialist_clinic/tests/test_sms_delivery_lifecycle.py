import os
import tempfile
import uuid

import pytest

from src.app import create_app


@pytest.fixture()
def app_ctx():
    with tempfile.TemporaryDirectory() as folder:
        app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": os.path.join(folder, "sms.db"),
                "BACKUP_FOLDER": os.path.join(folder, "backups"),
                "SECRET_KEY": "test",
            }
        )
        with app.app_context():
            yield app


def _patient(db, phone="09110000000"):
    patient_id = db.execute(
        "INSERT INTO patient_links(full_name,phone_number) VALUES('تست',?)",
        (phone,),
    ).lastrowid
    db.commit()
    return int(patient_id)


def _message(pid, *, provider="mediana", key=None):
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
    from src.services.sms.governance_service import SmsGovernanceService

    consent = SmsGovernanceService().require_allowed(
        patient_link_id=pid,
        purpose="CARE",
    )
    return SmsDispatchRepository().create_message(
        campaign_id=None,
        patient_link_id=pid,
        recipient="09110000000",
        body="test",
        provider_name=provider,
        idempotency_key=key or "message:" + uuid.uuid4().hex,
        source_type="care",
        source_ref=None,
        purpose="CARE",
        consent_event_id=consent.event_id,
        consent_decision=consent.decision,
        source_policy="TEST_CARE_MESSAGE",
        created_by="pytest",
    )


def test_message_and_wallet_idempotency_are_database_enforced(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.wallet_repo import WalletRepository

    db = get_db()
    patient_id = _patient(db)
    first, created_first = _message(patient_id, key="same")
    second, created_second = _message(patient_id, key="same")
    assert first == second
    assert created_first is True
    assert created_second is False

    wallet = WalletRepository()
    assert wallet.adjust(
        patient_id,
        100,
        reason="campaign",
        idempotency_key="wallet:same",
    ) == 100
    assert wallet.adjust(
        patient_id,
        100,
        reason="campaign",
        idempotency_key="wallet:same",
    ) == 100
    assert db.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0] == 1


def test_message_claim_requires_governance_and_prevents_double_click(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository

    db = get_db()
    patient_id = _patient(db)
    legacy_id = db.execute(
        """INSERT INTO sms_messages
           (patient_link_id,recipient,body,status,provider,idempotency_key,
            delivery_status,retryable)
           VALUES (?, '09110000000', 'legacy', 'pending', 'mediana', ?,
                   'Queued', 1)""",
        (patient_id, "legacy:" + uuid.uuid4().hex),
    ).lastrowid
    db.commit()
    with pytest.raises(Exception, match="governed consent"):
        db.execute(
            "UPDATE sms_messages SET delivery_status='Submitting' WHERE id=?",
            (legacy_id,),
        )
    db.rollback()

    message_id, _created = _message(patient_id)
    dispatch = SmsDispatchRepository()
    assert dispatch.claim_submission(message_id) is True
    assert dispatch.claim_submission(message_id) is False
    assert dispatch.get(message_id)["send_attempts"] == 1


def test_terminal_delivery_is_never_polled_again(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository

    patient_id = _patient(get_db())
    message_id, _created = _message(patient_id, provider="mediana")
    dispatch = SmsDispatchRepository()
    assert dispatch.claim_submission(message_id)
    dispatch.record_submission(
        message_id,
        ok=True,
        provider_request_id="r1",
        delivery_status="PendingApproval",
    )
    dispatch.record_delivery(message_id, status="Delivered", status_int=6)
    row = dispatch.get(message_id)
    assert row["delivered_at"]
    assert row["next_status_check_at"] is None
    assert dispatch.due_delivery_messages(message_ids=[message_id]) == []


def test_timeout_is_ambiguous_and_not_claimable(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository

    patient_id = _patient(get_db())
    message_id, _created = _message(patient_id, provider="mediana")
    dispatch = SmsDispatchRepository()
    assert dispatch.claim_submission(message_id)
    dispatch.record_submission(
        message_id,
        ok=False,
        pending=True,
        delivery_status="SubmissionUnknown",
        error="timeout",
    )
    assert dispatch.get(message_id)["delivery_status"] == "SubmissionUnknown"
    assert dispatch.claim_submission(message_id) is False


def test_delivery_summary_matches_filtered_rows():
    from src.services.sms.delivery_service import delivery_summary

    rows = [
        {"delivery_status": "Accepted"},
        {"delivery_status": "Delivered"},
        {"delivery_status": "SendToOperator"},
        {"delivery_status": "NumberBlackListed"},
        {"delivery_status": "StatusUnknown"},
        {"delivery_status": None},
    ]
    assert delivery_summary(rows) == {
        "total": 6,
        "accepted": 1,
        "delivered": 1,
        "in_flight": 3,
        "failed": 1,
        "unknown": 1,
    }


def test_control_room_invite_is_approval_gated_and_idempotent_per_day(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.services.engagement_service import EngagementService

    db = get_db()
    patient_id = _patient(db)
    service = EngagementService()

    first = service.enqueue_control_room_invite(patient_id, "سلام {name} عزیز")
    second = service.enqueue_control_room_invite(patient_id, "سلام {name} عزیز")

    assert first is not None
    assert second is None
    approval = service.repo.get_approval(first)
    assert approval["status"] == "pending"
    assert approval["event_key"] == "control_room_invite"
    assert approval["message"] == "سلام تست عزیز"
    assert db.execute("SELECT COUNT(*) FROM sms_messages").fetchone()[0] == 0
