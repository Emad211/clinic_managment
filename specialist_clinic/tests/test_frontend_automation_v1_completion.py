"""Contracts for the delivered automation surfaces and honest status reporting."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_previous_completion_claim_is_withdrawn_and_replaced_by_gap_audit():
    report = read("docs/FRONTEND_AUTOMATION_V1_COMPLETION_REPORT.md")
    audit = read("docs/FRONTEND_AUTOMATION_V1_REALITY_GAP_AUDIT.md")
    assert "Previous Completion Report (Withdrawn)" in report
    assert "not supported by the actual browser experience" in report
    assert "REALITY_GAP_AUDIT" in report
    assert "about 31%" in audit
    assert "Repair 1 — Global shell and route reliability" in audit
    assert "Doctor Queue" in audit and "404" in audit


def test_home_is_action_first_and_uses_existing_workflows():
    page = read("src/templates/dashboard_v1.html")
    route = read("src/api/dashboard.py")
    assert '{% extends "automation_base.html" %}' in page
    assert "الان چه کاری لازم است؟" in page
    assert "شروع کارهای امروز" in page
    assert "unified_followups.index" in page
    assert "doctor_queue.index" in page
    assert "appointments.list_appointments" in page
    assert "patients.list_patients" in page
    assert 'render_template(\n        "dashboard_v1.html"' in route


def test_settings_preserve_all_existing_post_contracts_without_extra_confirmation():
    page = read("src/templates/manager/settings.html")
    required_fields = (
        "sms_provider", "kavenegar_api_key", "kavenegar_sender",
        "kavenegar_timeout", "mediana_api_key", "mediana_sending_number",
        "mediana_message_type", "mediana_timeout",
        "sms_cost_per_part_kavenegar_toman",
        "sms_cost_per_part_mediana_toman", "reminder_template",
        "clinic_name", "clinic_phone", "clinic_address",
        "prescriber_name", "prescriber_license", "rx_disclaimer",
        "patient_card_enabled", "public_base_url",
    )
    for field in required_fields:
        assert f'name="{field}"' in page
    assert page.count("confirm(") == 1
    assert "کلید ذخیره‌شده پاک شود؟" in page
    assert page.count("ذخیره تنظیمات") == 1


def test_message_center_has_no_duplicate_followup_destinations():
    page = read("src/templates/sms/_hub_tabs.html")
    assert page.count("hub-nav-btn") == 4
    assert "clinical_alerts.index" not in page
    assert "نمای یکپارچه" not in page
    assert "ورک‌لیستِ تماس" not in page
    assert "مرکز کارها" in page


def test_finance_review_keeps_readonly_accounting_and_confirms_only_reversal():
    page = read("src/templates/finance_review/index.html")
    assert "مبالغ حسابداری همچنان فقط‌خواندنی‌اند" in page
    assert "تکمیل بازبینی" in page
    assert "ثبت اصلاح مالی" in page
    assert page.count("confirm(") == 1
    assert "برگشت داده شود" in page
    assert "accounting" not in page.lower() or "فاکتور" in page


def test_completion_surface_styles_have_mobile_breakpoints():
    for css_path in (
        "src/static/css/dashboard-automation-v1.css",
        "src/static/css/settings-automation-v1.css",
        "src/static/css/message-center-automation-v1.css",
        "src/static/css/finance-automation-v1.css",
        "src/static/css/shell-automation-v2.css",
    ):
        css = read(css_path)
        assert "@media(max-width:" in css
