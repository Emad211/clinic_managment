import pytest

from apps.chronic.models import WalletTransaction

pytestmark = pytest.mark.django_db


def test_credit_increases_balance(auth_client, diabetic_patient):
    p = diabetic_patient
    auth_client.post(f"/patients/{p.id}/wallet/", {"kind": "credit", "amount": "50000", "reason": "هدیه"})
    p.refresh_from_db()
    assert p.wallet_balance == 50000
    tx = WalletTransaction.objects.get(patient=p)
    assert tx.kind == "credit" and tx.amount == 50000 and tx.balance_after == 50000
    assert tx.created_by_id is not None


def test_debit_decreases_balance(auth_client, diabetic_patient):
    p = diabetic_patient
    auth_client.post(f"/patients/{p.id}/wallet/", {"kind": "credit", "amount": "50000"})
    auth_client.post(f"/patients/{p.id}/wallet/", {"kind": "debit", "amount": "20000"})
    p.refresh_from_db()
    assert p.wallet_balance == 30000
    assert WalletTransaction.objects.filter(patient=p).count() == 2


def test_debit_never_goes_negative(auth_client, diabetic_patient):
    p = diabetic_patient
    auth_client.post(f"/patients/{p.id}/wallet/", {"kind": "credit", "amount": "10000"})
    # try to overdraw
    auth_client.post(f"/patients/{p.id}/wallet/", {"kind": "debit", "amount": "999999"})
    p.refresh_from_db()
    assert p.wallet_balance == 0  # clamped to available balance, not negative
