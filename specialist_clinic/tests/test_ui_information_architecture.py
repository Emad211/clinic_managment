"""Guard the one-home-per-capability information architecture."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def template(name):
    return (ROOT / "src" / "templates" / name).read_text(encoding="utf-8")


def test_shell_has_one_native_work_center_and_no_legacy_primary_destinations():
    base = template("base.html")
    automation = (ROOT / "src" / "static" / "js" / "automation-v1.js").read_text(encoding="utf-8")
    assert "مرکز کارها" in base
    assert "url_for('unified_followups.index')" in base
    assert "url_for('control_room.index')" not in base
    assert "اتاقِ کنترل" not in base
    assert "هاب پیام" not in base
    assert "بازبینی وصول" not in base
    assert "humanizePrimaryNavigation" not in automation


def test_message_center_does_not_duplicate_followup_navigation():
    hub = template("sms/_hub_tabs.html")
    assert "مرکز کارها" in hub
    assert "هشدارهای بالینی" not in hub
    assert "ورک‌لیستِ تماس" not in hub
    assert "نمای یکپارچه" not in hub


def test_management_page_has_one_daily_surface_and_advanced_tools_are_collapsed():
    page = template("manager/index.html")
    for endpoint in (
        "manager.settings", "manager.clinical_engine", "manager.users",
    ):
        assert page.count(f"url_for('{endpoint}')") == 1
    assert "url_for('manager.diseases')" not in page
    assert "url_for('manager.engagement')" not in page
    assert "url_for('manager.protocols')" not in page
    assert "ابزارهای پیشرفته و Shadow" in page
    assert 'data-technical-details' in page
    assert "card kpi" not in page


def test_dashboard_routes_to_action_first_home():
    route = (ROOT / "src" / "api" / "dashboard.py").read_text(encoding="utf-8")
    dashboard = template("dashboard_v1.html")
    assert '"dashboard_v1.html"' in route
    assert '{% extends "automation_base.html" %}' in dashboard
    assert "الان چه کاری لازم است؟" in dashboard
    assert "شروع کارهای امروز" in dashboard
    assert "مرکز کارها" in dashboard
    assert "صف پزشک" in dashboard
    assert "نوبت‌های بعدی" in dashboard


def test_dashboard_is_summary_only_and_work_center_owns_admin_ranking():
    dashboard = template("dashboard_v1.html")
    control_room = template("control_room.html")
    route = (ROOT / "src" / "api" / "dashboard.py").read_text(encoding="utf-8")
    assert dashboard.count("url_for('control_room.index')") == 1
    assert "بیمارانِ نیازمندِ توجه" not in dashboard
    assert "attention" not in dashboard
    assert 'class="card control-patient-list"' in control_room
    assert 'ControlRoomService().panel(show_value=False)["summary"]' in route
    assert "r['hba1c'] > 8" not in route


def test_visit_has_one_message_action_with_explicit_message_type():
    page = template("doctor_queue/visit_quick.html")
    assert page.count("url_for('doctor_queue.invite'") == 1
    assert "url_for('patients.invite_patient'" not in page
    assert 'name="event_key"' in page
    assert "افزودن پیام" in page
    assert "ارسال مستقیم" not in page


def test_disease_page_is_the_visible_home_for_indicator_management():
    diseases = template("manager/diseases.html")
    assert "url_for('manager.rules')" not in diseases
    assert "url_for('manager.decision_rules')" not in diseases
    detail = template("manager/disease_detail.html")
    assert "url_for('manager.rules_add')" in detail
    assert "افزودن شاخص به" in detail


def test_control_room_has_a_balanced_three_level_layout_but_is_not_primary_nav():
    page = template("control_room.html")
    base = template("base.html")
    assert 'class="control-summary"' in page
    assert 'class="control-cohorts"' in page
    assert 'class="card control-patient-list"' in page
    assert "grid grid-4" not in page
    assert "🔴" not in page and "💰" not in page and "📋" not in page
    assert page.count('class="card kpi') == 3
    assert "url_for('control_room.index')" not in base


def test_message_center_has_five_clear_destinations_and_responsive_controls():
    page = template("sms/_hub_tabs.html")
    assert page.count("hub-nav-btn") == 5
    assert "مرکز پیام‌ها" in page
    for label in (
        "نیازمند تأیید",
        "کمپین‌ها",
        "خودکارسازی",
        "گزارش ارسال",
        "تنظیمات پیشرفته",
    ):
        assert label in page
    assert "permissions.get('sms.settings.manage')" in page
    css = (ROOT / "src" / "static" / "css" / "message-center-automation-v1.css").read_text(encoding="utf-8")
    assert ".message-center-shell" in css
    assert "@media(max-width:700px)" in css


def test_message_center_follows_exception_compose_automate_deliver_advanced_order():
    hub = template("sms/_hub_tabs.html")
    assert (
        hub.index("sms.approvals")
        < hub.index("sms.campaigns")
        < hub.index("manager.engagement")
        < hub.index("sms.messages_report")
        < hub.index("manager.settings")
    )
    assert 'aria-current="page"' in hub
    campaigns = template("sms/campaigns.html")
    assert 'class="card campaign-composer"' in campaigns
    assert "چرخه کمپین پیامکی" in campaigns
    detail = template("sms/campaign_detail.html")
    assert '{% include "sms/_hub_tabs.html" %}' in detail
    report = template("sms/messages.html")
    assert 'class="message-report-summary"' in report
    assert 'class="card message-filters"' in report


def test_settings_keep_existing_server_contract_but_use_progressive_sections():
    page = template("manager/settings.html")
    route = (ROOT / "src" / "api" / "manager.py").read_text(encoding="utf-8")
    assert '{% extends "automation_base.html" %}' in page
    for section in (
        "settings-network", "settings-sms", "settings-costs",
        "settings-card", "settings-prescription",
    ):
        assert f'id="{section}"' in page
    for field in (
        "sms_provider", "kavenegar_api_key", "mediana_api_key",
        "sms_cost_per_part_kavenegar_toman", "reminder_template",
        "patient_card_enabled", "public_base_url", "clinic_name",
        "prescriber_name", "rx_disclaimer",
    ):
        assert f'name="{field}"' in page
    assert page.count("ذخیره تنظیمات") == 1
    assert "data-sensitive-clear" in page
    assert "تنظیمات طولانی" not in page
    assert 'name="settings_context"' in page
    assert "message_settings_context" in page
    assert route.count('@bp.route("/settings", methods=["GET", "POST"])') == 1
    assert "settings_redirect" in route
    assert "ذخیره مستقل تا وجود Endpoint جدا فعال نمی‌شود" in page


def test_finance_review_is_exception_first_keyboard_ready_and_only_reversal_confirms():
    page = template("finance_review/index.html")
    css = (ROOT / "src" / "static" / "css" / "finance-automation-v1.css").read_text(encoding="utf-8")
    assert '{% extends "automation_base.html" %}' in page
    assert "نیازمند بازبینی" in page
    assert "تکمیل بازبینی" in page
    assert "جزئیات فنی برای پشتیبانی" in page
    assert page.count("confirm(") == 1
    assert "برگشت داده شود" in page
    assert ".finance-review-primary:focus-within" in css
    assert ":focus-visible" in css
    assert "min-height:var(--touch-target,44px)" in css
    assert "@media(max-width:700px)" in css


def test_control_room_messages_are_approval_gated_not_sent_directly():
    route = (ROOT / "src" / "api" / "control_room.py").read_text(encoding="utf-8")
    page = template("control_room.html")
    assert "send_single" not in route
    assert "enqueue_control_room_invite" in route
    assert "افزودن به صف تأیید" in page
    assert "ارسال مستقیم انجام نمی‌شود" in page


def test_component_contract_has_shared_control_sizes_and_accessible_icon_buttons():
    css = (ROOT / "src" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    for token in ("--control-sm:36px", "--control-md:42px", "--control-lg:48px", "--touch-target:44px"):
        assert token in css
    assert "--faint:#7b87a5" in css
    assert "--btn-bg:var(--primary2);--btn-bg-h:#1d4ed8" in css
    assert ".btn-secondary{" in css

    templates = list((ROOT / "src" / "templates").rglob("*.html"))
    all_markup = "\n".join(path.read_text(encoding="utf-8") for path in templates)
    icon_buttons = re.findall(
        r'<button\b(?=[^>]*class="[^"]*btn-icon[^"]*")[^>]*>',
        all_markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert icon_buttons
    assert all('aria-label="' in tag for tag in icon_buttons)
    assert "btn-secondary" not in all_markup
    assert not any("style=" in line for line in all_markup.splitlines() if "class=\"btn" in line)


def test_global_shell_supports_native_role_navigation_mobile_bottom_nav_and_errors():
    base = template("base.html")
    app_css = (ROOT / "src" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    shell_css = (ROOT / "src" / "static" / "css" / "shell-automation-v2.css").read_text(encoding="utf-8")
    shell_js = (ROOT / "src" / "static" / "js" / "shell-automation-v2.js").read_text(encoding="utf-8")
    app = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
    assert 'class="skip-link"' in base
    assert 'class="mobile-shell-header"' in base
    assert 'class="mobile-bottom-nav"' in base
    assert 'aria-controls="clinic-sidebar"' in base
    assert "permissions.get('clinical.task.view')" in base
    assert "permissions.get('financial.review.view')" in base
    assert "document.body.classList.toggle('nav-open'" in shell_js
    assert "event.submitter" in shell_js and "button.classList.add('is-loading')" in shell_js
    assert "markScrollableTables" in shell_js
    assert "@media(max-width:900px)" in app_css and ".sidebar.is-open" in app_css
    assert "@media(max-width:900px)" in shell_css and ".mobile-bottom-nav" in shell_css
    assert "@app.errorhandler(404)" in app and "@app.errorhandler(500)" in app
    assert 'class="error-state"' in template("errors/error.html")


def test_patient_record_has_one_summary_next_action_and_unified_timeline():
    page = template("patients/detail.html")
    workspace = (ROOT / "src" / "static" / "js" / "patient-workspace-automation-v2.js").read_text(encoding="utf-8")
    assert page.count('class="patient-hero"') == 1
    assert page.count('class="patient-status-strip"') == 1
    assert page.count("اولویت بعدی پرونده") == 1
    assert page.count('class="care-timeline"') == 1
    assert "moveHeaderContextIntoStickyHero" in workspace
    assert "careTimelineCard" in workspace
    assert "encountersPane.appendChild(careTimelineCard)" in workspace
    assert "وضعیت سلامت کلی" not in page
    assert "📅" not in page


def test_patient_workspace_exposes_exact_five_tabs_keyboard_and_legacy_hashes():
    page = template("patients/detail.html")
    loader = (ROOT / "src" / "static" / "js" / "automation-v1.js").read_text(encoding="utf-8")
    workspace = (ROOT / "src" / "static" / "js" / "patient-workspace-automation-v2.js").read_text(encoding="utf-8")
    css = (ROOT / "src" / "static" / "css" / "patient-workspace-automation-v2.css").read_text(encoding="utf-8")

    expected = (
        ("summary", "خلاصه"),
        ("actions", "اقدامات"),
        ("clinical-data", "داده‌های بالینی"),
        ("medications", "دارو و نسخه"),
        ("encounters-documents", "ویزیت‌ها و اسناد"),
    )
    for name, label in expected:
        assert f"name: '{name}', label: '{label}'" in workspace
        assert f"tab-${{definition.name}}" in workspace
        assert f"pane-${{definition.name}}" in workspace
    assert "paneDefinitions" in workspace
    assert "['ArrowRight', 'ArrowLeft', 'Home', 'End']" in workspace
    assert "button.setAttribute('aria-selected'" in workspace
    assert "pane.setAttribute('aria-labelledby'" in workspace

    for legacy, target in (
        ("cockpit", "summary"),
        ("trends", "clinical-data"),
        ("record", "clinical-data"),
        ("meds", "medications"),
        ("labs", "clinical-data"),
        ("vitals", "clinical-data"),
    ):
        assert f"{legacy}: '{target}'" in workspace

    assert "setupPatientWorkspaceModule" in loader
    assert "patient-workspace-automation-v2.js" in loader
    assert "localStorage" not in workspace
    assert "sessionStorage" not in workspace
    assert "fetch(" not in workspace
    assert ".patient-workspace-tabs" in css
    assert ".patient-hero.is-compact" in css
    assert "@media(max-width:700px)" in css
    assert "@media(max-width:420px)" in css

    for label in ("مقدار آزمایش", "واحد آزمایش", "حد پایین مرجع", "حد بالای مرجع"):
        assert f'aria-label="{label}"' in page
