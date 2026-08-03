"""Guard the one-home-per-capability information architecture."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def template(name):
    return (ROOT / "src" / "templates" / name).read_text(encoding="utf-8")


def test_followups_live_inside_message_hub_not_as_second_sidebar_destination():
    base = template("base.html")
    assert "url_for('followups.worklist')" not in base
    assert "> هاب پیام</a>" in base
    hub = template("sms/_hub_tabs.html")
    assert hub.count("url_for('followups.worklist')") == 1


def test_management_page_has_one_navigation_surface_and_no_operational_duplicates():
    page = template("manager/index.html")
    for endpoint in (
        "manager.settings", "manager.clinical_engine", "manager.users",
    ):
        assert page.count(f"url_for('{endpoint}')") == 1
    assert "url_for('manager.diseases')" not in page
    assert "url_for('manager.engagement')" not in page
    assert "url_for('manager.protocols')" not in page
    assert "پیگیری‌های باز" not in page
    assert "card kpi" not in page


def test_dashboard_exposes_only_one_followup_call_to_action():
    page = template("dashboard.html")
    assert page.count("url_for('followups.worklist')") == 1


def test_dashboard_is_summary_only_and_worklist_owns_admin_ranking():
    dashboard = template("dashboard.html")
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
    assert "افزودن پیام به صف تأیید" in page


def test_disease_page_is_the_visible_home_for_indicator_management():
    diseases = template("manager/diseases.html")
    assert "url_for('manager.rules')" not in diseases
    assert "url_for('manager.decision_rules')" not in diseases
    detail = template("manager/disease_detail.html")
    assert "url_for('manager.rules_add')" in detail
    assert "افزودن شاخص به" in detail


def test_control_room_has_a_balanced_three_level_layout():
    page = template("control_room.html")
    assert 'class="control-summary"' in page
    assert 'class="control-cohorts"' in page
    assert 'class="card control-patient-list"' in page
    assert "grid grid-4" not in page
    assert "🔴" not in page and "💰" not in page and "📋" not in page
    assert page.count('class="card kpi') == 3


def test_message_hub_destinations_share_one_fixed_button_size():
    page = template("sms/_hub_tabs.html")
    assert page.count("hub-nav-btn") == 7
    assert "FOLLOWUP_UNIFIED_WORKLIST_READONLY" in page
    css = (ROOT / "src" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".hub-nav-btn{inline-size:190px;block-size:38px;min-width:190px" in css


def test_message_hub_follows_compose_approve_deliver_order_and_one_delivery_report():
    hub = template("sms/_hub_tabs.html")
    assert hub.index("sms.campaigns") < hub.index("sms.approvals") < hub.index("sms.messages_report")
    assert 'aria-current="page"' in hub
    campaigns = template("sms/campaigns.html")
    assert 'class="card campaign-composer"' in campaigns
    assert "چرخه کمپین پیامکی" in campaigns
    detail = template("sms/campaign_detail.html")
    assert '{% include "sms/_hub_tabs.html" %}' in detail
    report = template("sms/messages.html")
    assert 'class="message-report-summary"' in report
    assert 'class="card message-filters"' in report


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
    icon_buttons = [line for line in all_markup.splitlines() if "btn-icon" in line and "<button" in line]
    assert icon_buttons
    assert all('aria-label="' in line for line in icon_buttons)
    assert "btn-secondary" not in all_markup
    assert not any("style=" in line for line in all_markup.splitlines() if "class=\"btn" in line)


def test_global_shell_supports_mobile_navigation_loading_and_error_states():
    base = template("base.html")
    css = (ROOT / "src" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    app = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
    assert 'class="skip-link"' in base
    assert 'class="mobile-shell-header"' in base
    assert 'aria-controls="clinic-sidebar"' in base
    assert "document.body.classList.toggle('nav-open'" in base
    assert "e.submitter" in base and "btn.classList.add('is-loading')" in base
    assert "if(btn.name)" in base
    assert "markScrollableTables" in base
    assert "@media(max-width:900px)" in css and ".sidebar.is-open" in css
    assert "@app.errorhandler(404)" in app and "@app.errorhandler(500)" in app
    assert 'class="error-state"' in template("errors/error.html")


def test_patient_record_has_one_summary_next_action_and_unified_timeline():
    page = template("patients/detail.html")
    assert page.count('class="patient-hero"') == 1
    assert page.count('class="patient-status-strip"') == 1
    assert page.count("اولویت بعدی پرونده") == 1
    assert page.count('class="care-timeline"') == 1
    assert "وضعیت سلامت کلی" not in page
    assert "📅" not in page


def test_patient_record_tabs_expose_keyboard_and_aria_contract():
    page = template("patients/detail.html")
    for name in ("cockpit", "trends", "meds", "record"):
        assert f'id="tab-{name}"' in page
        assert f'aria-controls="pane-{name}"' in page
        assert f'id="pane-{name}"' in page
        assert f'aria-labelledby="tab-{name}"' in page
    assert "b.setAttribute('aria-selected'" in page
    assert "['ArrowRight','ArrowLeft','Home','End']" in page
    for label in ("مقدار آزمایش", "واحد آزمایش", "حد پایین مرجع", "حد بالای مرجع"):
        assert f'aria-label="{label}"' in page
