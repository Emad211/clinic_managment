"""Contracts for the automation-first frontend layer.

These tests intentionally inspect the rendered-template contracts rather than
business logic. Server endpoints remain authoritative; the browser may only
orchestrate actions that already exist.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_frontend_automation_plan_is_the_implementation_source_of_truth():
    plan = read("docs/FRONTEND_AUTOMATION_V1_IMPLEMENTATION_PLAN.md")
    for contract in (
        "80%",
        "15%",
        "5%",
        "Work Center",
        "Patient Workspace",
        "Auto-claim",
        "Auto-complete",
        "Auto-next",
        "360px",
    ):
        assert contract in plan
    assert "never fakes persistence" in plan


def test_automation_layer_is_additive_and_loaded_only_by_opted_in_pages():
    base = read("src/templates/automation_base.html")
    assert '{% extends "base.html" %}' in base
    assert "css/automation-v1.css" in base
    assert "js/automation-v1.js" in base
    assert "{{ super() }}" in base


def test_work_center_has_one_primary_action_and_automatic_filters():
    page = read("src/templates/followups/unified_worklist.html")
    assert '{% extends "automation_base.html" %}' in page
    assert "مرکز کارها" in page
    assert "data-auto-filter" in page
    assert 'data-auto-submit="debounced"' in page
    assert "data-primary-action" in page
    assert page.count("data-primary-action") == 1
    assert "data-action-menu" in page
    assert "جزئیات فنی برای پشتیبانی" in page
    assert "sms/_hub_tabs.html" not in page


def test_work_item_detail_prioritizes_action_and_collapses_ceremony():
    page = read("src/templates/followups/unified_detail.html")
    assert '{% extends "automation_base.html" %}' in page
    assert "کاری که اکنون باید انجام شود" in page
    assert "دریافت برای رسیدگی" in page
    assert "رسیدگی و واگذاری" in page
    assert "جزئیات فنی مسیر" in page
    assert "تاریخچه کار" in page
    assert "sms/_hub_tabs.html" not in page
    for forbidden in (
        "مسئولیت را می‌پذیرم",
        "متعهد می‌شوم",
        "با سیاست فوق موافقم",
    ):
        assert forbidden not in page


def test_contact_outcomes_are_one_click_but_use_the_existing_server_form():
    partial = read("src/templates/followups/_structured_contact_detail.html")
    script = read("src/static/js/automation-v1.js")
    for outcome in (
        "REACHED",
        "NO_ANSWER",
        "BUSY",
        "PHONE_INVALID",
        "APPOINTMENT_BOOKED",
        "ESCALATED_TO_PHYSICIAN",
    ):
        assert f'data-contact-outcome="{outcome}"' in partial
    assert 'name="expected_event_id"' in partial
    assert 'name="idempotency_key"' in partial
    assert "form.requestSubmit" in script
    assert "data-contact-form" in partial


def test_doctor_queue_is_next_patient_first_and_keeps_safe_linking():
    page = read("src/templates/doctor_queue/queue.html")
    assert '{% extends "automation_base.html" %}' in page
    assert "بیمار بعدی" in page
    assert "شروع ویزیت" in page
    assert "ادامه مستندسازی" in page
    assert "اتصال اختیاری نوبت یا کمپین" in page
    assert 'name="appointment_id"' in page
    assert 'name="campaign_response_event_id"' in page
    assert "/done" not in page
    assert "فاکتور حسابداری" not in page


def test_autosave_is_explicit_opt_in_and_never_local_only():
    script = read("src/static/js/automation-v1.js")
    assert 'form[data-autosave="server"]' in script
    assert "form.dataset.autosaveEndpoint || form.action" in script
    assert "fetch(endpoint" in script
    assert "localStorage.setItem" not in script
    assert "sessionStorage.setItem" not in script


def test_automation_styles_cover_mobile_focus_and_reduced_motion():
    css = read("src/static/css/automation-v1.css")
    assert "@media(max-width:700px)" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert ":focus-visible" in css
    assert ".task-card__actions>.btn" in css
    assert "min-height:var(--touch-target,44px)" in css
    assert ".doctor-queue-card" in css
