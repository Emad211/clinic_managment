"""Contracts for the automation-first completion surfaces."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_completion_report_records_deliberate_frontend_boundaries():
    report = read("docs/FRONTEND_AUTOMATION_V1_COMPLETION_REPORT.md")
    for value in (
        "Home replaced by an action-first dashboard",
        "Message Center reduced",
        "Settings replaced by progressive",
        "Finance review changed to exception-first",
        "does not fake persistence",
        "FO-6 Auto Guard remains in its separate PR",
    ):
        assert value in report


def test_home_is_action_first_doctor_queue_reached_from_root():
    page = read("src/templates/doctor_queue/queue.html")
    route = read("src/api/dashboard.py")
    assert '{% extends "base.html" %}' in page
    assert "صف پزشک" in page
    assert "شروع ویزیت" in page
    assert "doctor_queue.start" in page
    assert "doctor_queue.visit" in page
    assert "redirect(url_for(\"doctor_queue.index\"))" in route or "redirect(url_for('doctor_queue.index'))" in route


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
    assert page.count("hub-nav-btn") == 3
    assert "clinical_alerts.index" not in page
    assert "نمای یکپارچه" not in page
    assert "ورک‌لیستِ تماس" not in page
    assert "مرکز کارها" not in page
    assert "url_for('followups.worklist')" not in page
    assert "url_for('unified_followups.index')" not in page


def test_finance_review_keeps_readonly_accounting_and_confirms_only_reversal():
    page = read("src/templates/finance_review/index.html")
    assert "مبالغ حسابداری همچنان فقط‌خواندنی‌اند" in page
    assert "تکمیل بازبینی" in page
    assert "ثبت اصلاح مالی" in page
    assert page.count("confirm(") == 1
    assert "برگشت داده شود" in page
    assert "accounting" not in page.lower() or "فاکتور" in page


def test_completion_styles_have_mobile_breakpoints():
    for css_path in (
        "src/static/css/dashboard-automation-v1.css",
        "src/static/css/settings-automation-v1.css",
        "src/static/css/message-center-automation-v1.css",
        "src/static/css/finance-automation-v1.css",
    ):
        css = read(css_path)
        assert "@media(max-width:" in css
