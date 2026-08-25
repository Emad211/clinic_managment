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


def test_automation_layer_is_additive_and_loaded_by_the_single_shell():
    base = read("src/templates/base.html")
    assert "css/automation-v1.css" in base
    assert "js/automation-v1.js" in base


def test_work_center_has_one_primary_action_and_automatic_filters():
    page = read("src/templates/followups/unified_worklist.html")
    assert '{% extends "base.html" %}' in page
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
    assert '{% extends "base.html" %}' in page
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
    assert '{% extends "base.html" %}' in page
    assert "بیمار بعدی" in page
    assert "شروع ویزیت" in page
    assert "ادامه مستندسازی" in page
    assert "اتصال اختیاری نوبت یا کمپین" in page
    assert 'name="appointment_id"' in page
    assert 'name="campaign_response_event_id"' in page
    assert "/done" not in page
    assert "فاکتور حسابداری" not in page


def test_encounter_has_three_human_steps_and_one_final_action():
    page = read("src/templates/doctor_queue/visit_quick.html")
    assert '{% extends "base.html" %}' in page
    for section in (
        "شرح حال و معاینه",
        "ارزیابی و برنامه",
        "پیگیری بعد از ویزیت",
    ):
        assert section in page
    assert 'name="action" value="draft"' in page
    assert 'name="action" value="sign"' in page
    assert "ذخیره پیش‌نویس" in page
    assert "پایان ویزیت" in page
    assert "Ctrl/⌘ + S" in page
    assert "تعهدهای اجرایی طرح درمان" not in page
    assert "امضا، ساخت Worklist و پایان ویزیت" not in page
    # Existing backend contract is preserved behind simpler wording.
    for field in (
        "commitment_client_key",
        "commitment_type",
        "commitment_instruction",
        "commitment_due_date",
        "commitment_fulfillment",
    ):
        assert f'name="{field}"' in page
    assert "FOLLOWUP_REQUIRED" in page
    assert "REFERRED" in page
    assert "URGENT_ESCALATION" in page
    # The current redirect/idempotency endpoint is not safe for repeated autosave.
    assert 'data-autosave="server"' not in page


def test_appointments_use_one_primary_row_action_and_optional_creation_fields():
    listing = read("src/templates/appointments/list.html")
    create = read("src/templates/appointments/new.html")
    styles = read("src/static/css/appointments-automation-v1.css")

    assert '{% extends "base.html" %}' in listing
    assert "appointments-automation-v1.css" in listing
    assert "appointment-card-list" in listing
    assert "appointment-card__actions" in listing
    assert "data-action-menu" in listing
    assert "انجام شد" in listing
    assert "ثبت غیبت" in listing
    assert "لغو نوبت" in listing

    assert '{% extends "base.html" %}' in create
    assert "appointments-automation-v1.css" in create
    assert "appointment-date-grid" in create
    assert "تنظیمات اختیاری" in create
    assert 'name="patient_link_id"' in create
    assert 'name="date"' in create
    assert 'name="time"' in create
    assert 'name="appt_type"' in create
    assert "یادآوری نوبت در مسیر خودکار" in create
    assert "@media(max-width:700px)" in styles


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
    assert ".encounter-layout" in css
    assert ".encounter-actions-sticky" in css
