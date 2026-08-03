from __future__ import annotations

from pathlib import Path

import pytest


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def consent_ux_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "sms-consent-ux.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "sms-consent-ux-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _patient(db) -> int:
    cursor = db.execute(
        """INSERT INTO patient_links
           (national_id, full_name, phone_number, enrolled_by,
            enrolled_at, updated_at)
           VALUES ('SMSUX001', 'بیمار تست رضایت پیامک', '09121234567',
                   'pytest', '2026-08-03 09:00:00', '2026-08-03 09:00:00')"""
    )
    db.commit()
    patient_id = int(cursor.lastrowid)
    from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository

    SmsGovernanceRepository(db).ensure_patient_defaults(patient_id)
    return patient_id


def _login(client) -> None:
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert response.status_code in {302, 303}


def test_summary_explains_each_independent_message_purpose(consent_ux_app):
    from src.adapters.sqlite.core import get_db
    from src.services.sms.governance_service import SmsGovernanceService

    patient_id = _patient(get_db())
    summary = SmsGovernanceService().summary(patient_id)

    care = summary["CARE"]
    marketing = summary["MARKETING"]

    assert care["label"] == "پیام‌های مراقبتی و خدماتی"
    assert care["status_label"] == "دریافت می‌کند"
    assert "یادآوری نوبت" in care["description"]
    assert "آزمایش" in care["examples"]
    assert care["action_label"] == "توقف پیام‌های مراقبتی"
    assert care["source_label"] == "رابطهٔ مراقبتی موجود با درمانگاه"

    assert marketing["label"] == "پیام‌های عمومی و تبلیغاتی"
    assert marketing["status_label"] == "دریافت نمی‌کند"
    assert "کمپین" in marketing["description"]
    assert "روی پیام‌های مراقبتی و نوبت اثری ندارد" in marketing["status_help"]
    assert marketing["action_label"] == "فعال‌کردن پیام‌های عمومی و تبلیغاتی"
    assert marketing["source_label"] == "رضایت تبلیغاتی صریح ثبت نشده است"


def test_patient_detail_renders_explicit_sms_consent_structure(consent_ux_app):
    from src.adapters.sqlite.core import get_db

    patient_id = _patient(get_db())
    client = consent_ux_app.test_client()
    _login(client)

    response = client.get(f"/patients/{patient_id}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "تنظیم دریافت پیامک" in html
    assert "مشخص می‌کند درمانگاه اجازه دارد چه نوع پیامکی" in html
    assert "دو نوع پیام کاملاً مستقل هستند" in html
    assert "پیام‌های مراقبتی و خدماتی" in html
    assert "پیام‌های عمومی و تبلیغاتی" in html
    assert "دریافت می‌کند" in html
    assert "دریافت نمی‌کند" in html
    assert "توقف پیام‌های مراقبتی" in html
    assert "فعال‌کردن پیام‌های عمومی و تبلیغاتی" in html
    assert "دلیل یا توضیح تغییر" in html
    assert "جزئیات ثبت برای پشتیبانی" in html


def test_consent_ui_preserves_governed_form_contract():
    detail = (
        SPECIALIST_ROOT / "src" / "templates" / "patients" / "detail.html"
    ).read_text(encoding="utf-8")
    partial = (
        SPECIALIST_ROOT / "src" / "templates" / "patients" / "_sms_consent.html"
    ).read_text(encoding="utf-8")

    assert '{% include "patients/_sms_consent.html" %}' in detail
    assert "sms_consent_update" in partial
    assert 'name="purpose"' in partial
    assert 'name="decision"' in partial
    assert 'name="expected_current_event_id"' in partial
    assert "permissions.get('sms.consent.manage')" in partial
    assert "consent.source_code" in partial
    assert "consent.reason_code" in partial
