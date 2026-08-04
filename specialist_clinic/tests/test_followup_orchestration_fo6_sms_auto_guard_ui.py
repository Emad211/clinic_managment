from __future__ import annotations

from datetime import timedelta

import pytest


@pytest.fixture()
def fo6_ui_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "fo6-ui.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "fo6-ui-test",
            "FOLLOWUP_SMS_AUTO_GUARDED": False,
        }
    )
    context = app.app_context()
    context.push()
    from src.adapters.sqlite.sms_repo import SmsRepository

    settings = SmsRepository()
    settings.set_setting("engagement_quiet_start", "00:00")
    settings.set_setting("engagement_quiet_end", "00:00")
    settings.set_setting("engagement_daily_cap", "10")
    yield app
    context.pop()
    core._initialized = False


def _login(client, username="admin", password="admin"):
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code in {302, 303}


def _seed(db):
    from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
    from src.common.utils import iran_now

    now = iran_now().replace(tzinfo=None, microsecond=0)
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, is_active, enrolled_by)
               VALUES ('FO6UI001', 'Secret FO6 UI Patient', '09121112222', 1, 'pytest')"""
        ).lastrowid
    )
    db.execute(
        """INSERT INTO appointments
           (patient_link_id, scheduled_at, status, created_by)
           VALUES (?, ?, 'scheduled', 'pytest')""",
        (patient_id, (now + timedelta(days=1)).isoformat(sep=" ")),
    )
    db.execute(
        """UPDATE engagement_events
           SET channel='sms', is_active=1, lead_days=30, cooldown_days=0,
               sms_template='سلام {name}، یادآوری {detail}'
           WHERE event_key='appointment_reminder'"""
    )
    db.commit()
    SmsGovernanceRepository(db).ensure_patient_defaults(patient_id)
    return patient_id


def test_get_is_read_only_and_flag_off_mutations_are_404(fo6_ui_app):
    from src.adapters.sqlite.core import get_db

    client = fo6_ui_app.test_client()
    _login(client)
    db = get_db()
    before = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    response = client.get("/sms/auto-guard/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "مسیر خودکار خاموش است" in html
    after = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert before == after
    assert "sms_auto_guard_candidates" not in after
    for path in ("publish", "collect", "execute"):
        assert client.post(f"/sms/auto-guard/{path}").status_code == 404


def test_manager_can_publish_collect_execute_without_ui_phi_leak(fo6_ui_app):
    from src.adapters.sqlite.core import get_db

    client = fo6_ui_app.test_client()
    _login(client)
    db = get_db()
    patient_id = _seed(db)
    fo6_ui_app.config["FOLLOWUP_SMS_AUTO_GUARDED"] = True

    published = client.post(
        "/sms/auto-guard/publish",
        data={"ttl_hours": "24"},
    )
    assert published.status_code in {302, 303}
    collected = client.post(
        "/sms/auto-guard/collect",
        data={"limit": "100"},
    )
    assert collected.status_code in {302, 303}
    candidate = db.execute(
        """SELECT id FROM sms_auto_guard_candidates
           WHERE patient_link_id=? AND event_key='appointment_reminder'""",
        (patient_id,),
    ).fetchone()
    assert candidate is not None

    page = client.get("/sms/auto-guard/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "ارسال محافظت‌شدهٔ پیامک" in html
    assert "appointment_reminder" in html
    assert "Secret FO6 UI Patient" not in html
    assert "09121112222" not in html
    assert "سلام" not in html
    assert f"پرونده #{patient_id}" in html or "پرونده #" in html

    executed = client.post(
        "/sms/auto-guard/execute",
        data={"candidate_id": str(candidate["id"])},
    )
    assert executed.status_code in {302, 303}
    assert db.execute(
        """SELECT COUNT(*) FROM sms_auto_guard_decision_events
           WHERE candidate_id=? AND decision_type='SUBMITTED'""",
        (candidate["id"],),
    ).fetchone()[0] == 1
    assert db.execute(
        """SELECT COUNT(*) FROM sms_messages
           WHERE source_type='fo6_auto_guard' AND source_ref=?""",
        (str(candidate["id"]),),
    ).fetchone()[0] == 1

    after = client.get("/sms/auto-guard/").get_data(as_text=True)
    assert "SUBMITTED" in after
    assert "Secret FO6 UI Patient" not in after
    assert "09121112222" not in after
    assert "سلام" not in after


def test_staff_may_view_but_cannot_run_manager_actions(fo6_ui_app):
    from src.services.auth_service import AuthService

    assert AuthService().register_user(
        "fo6-staff",
        "password123",
        role="staff",
        full_name="FO6 Staff",
    )
    client = fo6_ui_app.test_client()
    _login(client, "fo6-staff", "password123")
    assert client.get("/sms/auto-guard/").status_code == 200
    fo6_ui_app.config["FOLLOWUP_SMS_AUTO_GUARDED"] = True
    response = client.post("/sms/auto-guard/publish", data={"ttl_hours": "24"})
    assert response.status_code in {302, 303, 403}


def test_campaign_page_links_to_governed_care_surface(fo6_ui_app):
    client = fo6_ui_app.test_client()
    _login(client)
    response = client.get("/sms/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "ارسال محافظت‌شدهٔ CARE" in html
    assert "/sms/auto-guard/" in html


def test_cli_status_redaction_never_returns_hash_material_or_payload():
    from scripts.run_fo6_sms_auto_guard import _redact_status

    redacted = _redact_status(
        {
            "storage_ready": True,
            "feature_enabled": True,
            "policy": {"version": 1, "policy_json": "secret"},
            "templates": {
                "appointment_reminder": {
                    "version": 2,
                    "template_text": "raw body",
                }
            },
            "candidates": [
                {
                    "id": 7,
                    "patient_link_id": 4,
                    "event_key": "appointment_reminder",
                    "period_key": "appt:1",
                    "generation_no": 1,
                    "expires_at": "2026-08-05 10:00:00",
                    "state": "AVAILABLE",
                    "phone_hash": "x" * 64,
                    "body_hash": "y" * 64,
                }
            ],
            "decisions": [
                {
                    "id": 3,
                    "candidate_id": 7,
                    "decision_type": "DENIED",
                    "attempt_no": 0,
                    "reason_code": "QUIET_HOURS",
                    "message_id": None,
                    "recorded_at": "2026-08-04 22:00:00",
                    "payload_json": '{"raw":"secret"}',
                }
            ],
        }
    )
    rendered = str(redacted)
    assert "raw body" not in rendered
    assert "phone_hash" not in rendered
    assert "body_hash" not in rendered
    assert "payload_json" not in rendered
    assert "secret" not in rendered
    assert redacted["contains_raw_phone_or_body"] is False
