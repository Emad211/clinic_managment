from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


@pytest.fixture()
def remaining_surfaces_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "remaining-surfaces.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "remaining-surfaces-test",
            "CLINICAL_ENGINE_REQUIRE_ACTIVATION_GATE": True,
        }
    )
    context = app.app_context()
    context.push()
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    yield app, client
    context.pop()
    core._initialized = False


def test_clinical_engine_defaults_to_summary_and_keeps_wizard_advanced(
    remaining_surfaces_app,
):
    _app, client = remaining_surfaces_app

    summary = client.get("/manager/clinical-engine")
    summary_html = summary.get_data(as_text=True)
    assert summary.status_code == 200
    assert "خلاصه وضعیت و اقدام بعدی" in summary_html
    assert "اقدام بعدی" in summary_html
    assert "قواعد و فعال‌سازی پیشرفته" in summary_html
    assert "engine-wizard" not in summary_html
    assert "clinical-engine/prepare-rules" not in summary_html

    advanced = client.get("/manager/clinical-engine?view=advanced")
    advanced_html = advanced.get_data(as_text=True)
    assert advanced.status_code == 200
    assert "راه‌اندازی قدم‌به‌قدم" in advanced_html
    assert "engine-wizard" in advanced_html
    assert "clinical-engine/prepare-rules" in advanced_html


def test_message_center_exposes_five_tabs_and_reuses_settings_contract(
    remaining_surfaces_app,
):
    _app, client = remaining_surfaces_app
    response = client.get("/manager/settings?section=messages")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "تنظیمات پیشرفته پیام‌ها" in html
    for label in (
        "نیازمند تأیید",
        "کمپین‌ها",
        "خودکارسازی",
        "گزارش ارسال",
        "تنظیمات پیشرفته",
    ):
        assert label in html
    assert html.count("hub-nav-btn") == 5
    assert 'aria-current="page"' in html
    assert 'name="settings_context" value="messages"' in html
    assert "ذخیره مستقل تا وجود Endpoint جدا فعال نمی‌شود" in html
    assert html.count('id="settings-form"') == 1


def test_settings_adds_no_parallel_write_endpoint():
    route = read("src/api/manager.py")
    settings = read("src/templates/manager/settings.html")

    assert route.count('@bp.route("/settings", methods=["GET", "POST"])') == 1
    assert "settings_redirect" in route
    assert "message_settings_context" in route
    assert "settings_context" in settings
    assert settings.count("<form method=\"post\" class=\"settings-workspace") == 1
    assert settings.count("ذخیره تنظیمات") == 1


def test_users_are_cards_on_mobile_without_new_account_mutations():
    page = read("src/templates/manager/users.html")
    route = read("src/api/manager.py")
    css = read("src/static/css/remaining-surfaces-automation-v2.css")

    assert '{% extends "automation_base.html" %}' in page
    assert "user-card-list" in page
    assert "user-card__actions" in page
    assert 'type="password"' in page
    assert 'autocomplete="new-password"' in page
    assert "صدور مجدد توکن" in page
    assert page.count("confirm(") == 1
    assert route.count('@bp.route("/users", methods=["GET", "POST"])') == 1
    assert route.count('@bp.route("/users/<int:uid>/token", methods=["POST"])') == 1
    assert ".user-management-layout" in css
    assert "@media(max-width:700px)" in css


def test_finance_keeps_existing_actions_and_finishes_mobile_keyboard_css():
    page = read("src/templates/finance_review/index.html")
    css = read("src/static/css/finance-automation-v1.css")

    assert page.count("confirm(") == 1
    assert "تکمیل بازبینی" in page
    assert "ثبت اصلاح مالی" in page
    assert "برگشت داده شود" in page
    assert ".finance-review-primary:focus-within" in css
    assert ":focus-visible" in css
    assert "min-height:var(--touch-target,44px)" in css
    assert "@media(max-width:700px)" in css
