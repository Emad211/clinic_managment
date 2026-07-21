import os
import tempfile
import uuid

import pytest

from src.app import create_app


@pytest.fixture()
def app_ctx():
    with tempfile.TemporaryDirectory() as folder:
        app = create_app({'TESTING': True, 'DATABASE_PATH': os.path.join(folder, 'sms.db'),
                          'BACKUP_FOLDER': os.path.join(folder, 'backups'), 'SECRET_KEY': 'test'})
        with app.app_context():
            yield app


def _patient(db, phone='09110000000'):
    return db.execute("INSERT INTO patient_links(full_name,phone_number) VALUES('تست',?)",
                      (phone,)).lastrowid


def test_message_and_wallet_idempotency_are_database_enforced(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_repo import SmsRepository
    from src.adapters.sqlite.wallet_repo import WalletRepository
    db = get_db(); pid = _patient(db); db.commit()
    repo = SmsRepository()
    first = repo.add_message(campaign_id=None, patient_link_id=pid, recipient='09110000000',
                             body='test', idempotency_key='same')
    second = repo.add_message(campaign_id=None, patient_link_id=pid, recipient='09110000000',
                              body='test', idempotency_key='same')
    assert first == second
    wallet = WalletRepository()
    assert wallet.adjust(pid, 100, reason='campaign', idempotency_key='wallet:same') == 100
    assert wallet.adjust(pid, 100, reason='campaign', idempotency_key='wallet:same') == 100
    assert db.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0] == 1


def test_message_claim_prevents_double_click(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_repo import SmsRepository
    db = get_db(); pid = _patient(db); db.commit(); repo = SmsRepository()
    mid = repo.add_message(campaign_id=None, patient_link_id=pid, recipient='09110000000',
                           body='test', idempotency_key='click:' + uuid.uuid4().hex)
    assert repo.claim_message_attempt(mid) is True
    assert repo.claim_message_attempt(mid) is False
    assert repo.get_message(mid)['send_attempts'] == 1


def test_terminal_delivery_is_never_polled_again(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_repo import SmsRepository
    db = get_db(); pid = _patient(db); db.commit(); repo = SmsRepository()
    mid = repo.add_message(campaign_id=None, patient_link_id=pid, recipient='09110000000',
                           body='test', provider='mediana', idempotency_key='terminal:' + uuid.uuid4().hex)
    assert repo.claim_message_attempt(mid)
    repo.mark_submission(mid, ok=True, provider_request_id='r1', delivery_status='PendingApproval')
    repo.apply_delivery(mid, 'Delivered', 6)
    row = repo.get_message(mid)
    assert row['delivered_at'] and row['next_status_check_at'] is None
    assert repo.due_delivery_messages(message_ids=[mid]) == []


def test_timeout_is_ambiguous_and_not_claimable(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_repo import SmsRepository
    db = get_db(); pid = _patient(db); db.commit(); repo = SmsRepository()
    mid = repo.add_message(campaign_id=None, patient_link_id=pid, recipient='09110000000',
                           body='test', provider='mediana', idempotency_key='timeout:' + uuid.uuid4().hex)
    repo.claim_message_attempt(mid)
    repo.mark_submission(mid, ok=False, pending=True, error='timeout')
    assert repo.get_message(mid)['delivery_status'] == 'SubmissionUnknown'
    assert repo.claim_message_attempt(mid) is False


def test_delivery_summary_matches_the_filtered_rows():
    from src.services.sms.delivery_service import delivery_summary
    rows = [
        {'delivery_status': 'Delivered'}, {'delivery_status': 'SendToOperator'},
        {'delivery_status': 'NumberBlackListed'}, {'delivery_status': 'StatusUnknown'},
        {'delivery_status': None},
    ]
    assert delivery_summary(rows) == {
        'total': 5, 'delivered': 1, 'in_flight': 2, 'failed': 1, 'unknown': 1,
    }


def test_control_room_invite_is_approval_gated_and_idempotent_per_day(app_ctx):
    from src.adapters.sqlite.core import get_db
    from src.services.engagement_service import EngagementService
    db = get_db(); pid = _patient(db); db.commit()
    svc = EngagementService()

    first = svc.enqueue_control_room_invite(pid, 'سلام {name} عزیز')
    second = svc.enqueue_control_room_invite(pid, 'سلام {name} عزیز')

    assert first is not None
    assert second is None
    approval = svc.repo.get_approval(first)
    assert approval['status'] == 'pending'
    assert approval['event_key'] == 'control_room_invite'
    assert approval['message'] == 'سلام تست عزیز'
    assert db.execute("SELECT COUNT(*) FROM sms_messages").fetchone()[0] == 0
