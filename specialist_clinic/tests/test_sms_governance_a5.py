from __future__ import annotations

from dataclasses import dataclass
import os

import pytest


@pytest.fixture()
def sms_a5_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "sms-a5.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "sms-a5-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db, national_id: str = "SMSA5001", phone: str = "09121234567") -> int:
    cursor = db.execute(
        """INSERT INTO patient_links
           (national_id,full_name,phone_number,enrolled_by,enrolled_at,updated_at)
           VALUES (?, 'SMS Patient', ?, 'pytest',
                   '2026-07-26 09:00:00','2026-07-26 09:00:00')""",
        (national_id, phone),
    )
    db.commit()
    return int(cursor.lastrowid)


def _login(client, username="admin", password="admin"):
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code in {302, 303}


def test_consent_defaults_are_conservative_and_append_only(sms_a5_app):
    import sqlite3

    from src.adapters.sqlite.core import get_db
    from src.services.sms.governance_service import SmsGovernanceService

    db = get_db()
    patient_id = _patient(db)
    service = SmsGovernanceService()
    summary = service.summary(patient_id)
    assert summary["CARE"]["decision"] == "GRANTED"
    assert summary["MARKETING"]["decision"] == "REVOKED"
    marketing_head = int(summary["MARKETING"]["id"])

    granted = service.record(
        patient_link_id=patient_id,
        purpose="MARKETING",
        decision="GRANTED",
        actor_username="staff-a",
        actor_user_id=None,
        source_code="PATIENT_EXPLICIT_OPT_IN",
        idempotency_key="marketing-grant-1",
        expected_current_event_id=marketing_head,
        note="Patient explicitly requested campaign messages.",
    )
    assert granted["decision"] == "GRANTED"
    with pytest.raises(Exception, match="STALE_SMS_CONSENT_STATE"):
        service.record(
            patient_link_id=patient_id,
            purpose="MARKETING",
            decision="REVOKED",
            actor_username="staff-b",
            actor_user_id=None,
            source_code="PATIENT_REQUEST",
            idempotency_key="marketing-revoke-stale",
            expected_current_event_id=marketing_head,
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute(
            "UPDATE sms_consent_events SET decision='REVOKED' WHERE id=?",
            (granted["id"],),
        )
    db.rollback()
    assert db.execute(
        "SELECT COUNT(*) FROM sms_consent_events WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 3


def test_canonical_mobile_and_marketing_segment_require_explicit_grant(sms_a5_app):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.campaign_service import resolve_segment
    from src.services.sms.governance_service import (
        SmsGovernanceService,
        canonicalize_iran_mobile,
    )

    db = get_db()
    patient_id = _patient(db, phone="+98 912-123-4567")
    assert canonicalize_iran_mobile("+98 912-123-4567") == "09121234567"
    assert resolve_segment("all", purpose="MARKETING") == []

    current = SmsGovernanceService().summary(patient_id)["MARKETING"]
    SmsGovernanceService().record(
        patient_link_id=patient_id,
        purpose="MARKETING",
        decision="GRANTED",
        actor_username="manager",
        actor_user_id=None,
        source_code="PATIENT_EXPLICIT_OPT_IN",
        idempotency_key="marketing-optin-segment",
        expected_current_event_id=int(current["id"]),
    )
    rows = resolve_segment("all", purpose="MARKETING")
    assert len(rows) == 1
    assert rows[0]["phone_number"] == "09121234567"


def test_database_blocks_submission_without_governance(sms_a5_app):
    import sqlite3

    from src.adapters.sqlite.core import get_db

    db = get_db()
    patient_id = _patient(db)
    message_id = db.execute(
        """INSERT INTO sms_messages
           (patient_link_id,recipient,body,status,provider,idempotency_key,
            delivery_status,retryable)
           VALUES (?, '09121234567','ungoverned','pending','kavenegar',
                   'ungoverned-a5','Queued',1)""",
        (patient_id,),
    ).lastrowid
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="governed consent"):
        db.execute(
            "UPDATE sms_messages SET delivery_status='Submitting' WHERE id=?",
            (message_id,),
        )
    db.rollback()


def test_kavenegar_status_ten_is_delivered(monkeypatch):
    from src.services.sms.kavenegar_provider import KavenegarProvider

    provider = KavenegarProvider("test-key")

    def fake_request(method, payload=None, http_method="POST"):
        assert method == "sms/status"
        assert payload == {"messageid": "123"}
        assert http_method == "GET"
        return 200, {
            "return": {"status": 200, "message": "تایید شد"},
            "entries": [
                {
                    "messageid": 123,
                    "status": 10,
                    "statustext": "رسیده به گیرنده",
                    "receptor": "09121234567",
                }
            ],
        }

    monkeypatch.setattr(provider, "_request", fake_request)
    updates = provider.fetch_delivery(message_id="123")
    assert len(updates) == 1
    assert updates[0].status == "Delivered"
    assert updates[0].status_int == 10
    assert updates[0].provider_msgid == "123"


def test_delivery_reconciliation_uses_each_messages_provider(sms_a5_app):
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.sms_dispatch_repo import SmsDispatchRepository
    from src.services.sms.delivery_service import DeliveryService
    from src.services.sms.governance_service import SmsGovernanceService
    from src.services.sms.provider import DeliveryUpdate

    db = get_db()
    patient_id = _patient(db)
    consent = SmsGovernanceService().require_allowed(
        patient_link_id=patient_id,
        purpose="CARE",
    )
    dispatch = SmsDispatchRepository()

    identifiers = {}
    for provider_name, provider_id in (("mediana", "med-1"), ("kavenegar", "kav-1")):
        message_id, _ = dispatch.create_message(
            campaign_id=None,
            patient_link_id=patient_id,
            recipient="09121234567",
            body=provider_name,
            provider_name=provider_name,
            idempotency_key=f"provider-affine:{provider_name}",
            source_type="care",
            source_ref=None,
            purpose="CARE",
            consent_event_id=consent.event_id,
            consent_decision=consent.decision,
            source_policy="TEST_PROVIDER_AFFINITY",
            created_by="pytest",
        )
        assert dispatch.claim_submission(message_id)
        dispatch.record_submission(
            message_id,
            ok=True,
            provider_msgid=provider_id,
            delivery_status="Accepted",
        )
        identifiers[provider_name] = (message_id, provider_id)

    requested = []

    @dataclass
    class FakeProvider:
        provider_name: str

        def fetch_delivery(self, *, request_id=None, message_id=None):
            requested.append((self.provider_name, request_id, message_id))
            return [
                DeliveryUpdate(
                    provider_request_id=request_id,
                    provider_msgid=message_id,
                    recipient="09121234567",
                    status="Delivered",
                    status_int=10 if self.provider_name == "kavenegar" else 6,
                )
            ]

    result = DeliveryService(
        provider_factory=lambda name: FakeProvider(name),
    ).reconcile(limit=10)
    assert result["errors"] == 0
    assert result["updated"] == 2
    assert {item[0] for item in requested} == {"mediana", "kavenegar"}
    for message_id, _provider_id in identifiers.values():
        assert dispatch.get(message_id)["delivery_status"] == "Delivered"


def test_production_secret_never_falls_back_to_plaintext_db(sms_a5_app, monkeypatch):
    from src.adapters.sqlite.sms_repo import SmsRepository
    from src.services.sms import secret_resolver

    SmsRepository().set_setting("kavenegar_api_key", "raw-database-secret")
    monkeypatch.delenv("CLINIC_KAVENEGAR_API_KEY", raising=False)
    monkeypatch.setattr(secret_resolver, "_production", lambda: True)
    assert secret_resolver.get_sms_secret("kavenegar") == ""
    assert secret_resolver.masked_secret("kavenegar") == ""


def test_staff_permissions_allow_operations_but_not_campaign_mutation(sms_a5_app):
    from src.adapters.sqlite.auth_repo import AuthRepository

    AuthRepository().create_user(
        "sms-staff",
        "password123",
        role="staff",
        full_name="SMS Staff",
    )
    client = sms_a5_app.test_client()
    _login(client, "sms-staff", "password123")
    assert client.get("/sms/").status_code == 200
    denied = client.post(
        "/sms/campaign/new",
        data={"name": "x", "body": "x", "segment": "all"},
    )
    assert denied.status_code in {302, 303, 403}
    assert client.post("/sms/messages/reconcile").status_code in {302, 303}


def test_settings_never_render_raw_api_key(sms_a5_app):
    from src.adapters.sqlite.sms_repo import SmsRepository

    SmsRepository().set_setting("kavenegar_api_key", "super-secret-api-key-1234")
    client = sms_a5_app.test_client()
    _login(client)
    response = client.get("/manager/settings")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "super-secret-api-key-1234" not in html
    assert "1234" in html
    assert "CLINIC_KAVENEGAR_API_KEY" in html


def test_patient_consent_route_updates_only_selected_purpose(sms_a5_app):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.governance_service import SmsGovernanceService

    patient_id = _patient(get_db())
    before = SmsGovernanceService().summary(patient_id)
    client = sms_a5_app.test_client()
    _login(client)
    response = client.post(
        f"/patients/{patient_id}/sms-consent",
        data={
            "purpose": "MARKETING",
            "decision": "GRANTED",
            "expected_current_event_id": before["MARKETING"]["id"],
            "note": "explicit request",
        },
    )
    assert response.status_code in {302, 303}
    after = SmsGovernanceService().summary(patient_id)
    assert after["MARKETING"]["decision"] == "GRANTED"
    assert after["CARE"]["id"] == before["CARE"]["id"]
