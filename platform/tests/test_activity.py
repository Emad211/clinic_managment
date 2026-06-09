"""Append-only audit trail (REGULATORY §6 — accountability / ممیزی)."""
import pytest

from apps.common.models import ActivityLog

pytestmark = pytest.mark.django_db


def test_acknowledge_writes_activity_log(doctor_client, diabetic_patient):
    doctor_client.post(f"/patients/{diabetic_patient.id}/ack/", {"rule_code": "T2-DX-01"})
    row = ActivityLog.objects.filter(action="suggestion.acknowledge").first()
    assert row is not None
    assert row.actor_username == "doc"
    assert row.entity_id == diabetic_patient.id
    assert row.metadata.get("rule_code") == "T2-DX-01"


def test_wallet_credit_writes_activity_log(auth_client, diabetic_patient):
    auth_client.post(
        f"/patients/{diabetic_patient.id}/wallet/",
        {"kind": "credit", "amount": "5000", "reason": "شارژ"},
    )
    row = ActivityLog.objects.filter(action="wallet.credit").first()
    assert row is not None and row.metadata.get("amount") == 5000


def test_eprescription_writes_activity_log(doctor_client, diabetic_patient):
    doctor_client.post(f"/patients/{diabetic_patient.id}/rx/new/", {"insurer": "tamin"})
    assert ActivityLog.objects.filter(action="rx.create").count() == 1


def test_activity_page_manager_only(doctor_client, diabetic_patient):
    """A clinical user (doctor) cannot open the audit log — manager oversight only."""
    r = doctor_client.get("/activity/")
    assert r.status_code == 302 and "dashboard" in r["Location"]


def test_activity_page_renders_for_manager(auth_client, diabetic_patient):
    # generate one audited event first
    auth_client.post(
        f"/patients/{diabetic_patient.id}/wallet/",
        {"kind": "credit", "amount": "1000", "reason": "x"},
    )
    r = auth_client.get("/activity/")
    body = r.content.decode()
    assert r.status_code == 200
    assert "گزارشِ ممیزی" in body and "wallet.credit" in body


def test_log_failure_does_not_break_action(auth_client, diabetic_patient, monkeypatch):
    """A logging failure must never roll back the primary action (best-effort)."""
    from apps.common import activity

    def boom(*a, **k):
        raise RuntimeError("audit sink down")

    monkeypatch.setattr(activity.ActivityLog.objects, "create", boom)
    r = auth_client.post(
        f"/patients/{diabetic_patient.id}/wallet/",
        {"kind": "credit", "amount": "2000", "reason": "y"},
    )
    # the wallet credit still went through despite the audit insert failing
    diabetic_patient.refresh_from_db()
    assert diabetic_patient.wallet_balance == 2000
    assert r.status_code == 302
