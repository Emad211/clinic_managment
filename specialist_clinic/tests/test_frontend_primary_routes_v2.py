"""Browser-facing smoke contracts for the primary frontend shell and routes."""
from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def frontend_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "frontend-routes.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "frontend-routes-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _login(client):
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert response.status_code in {302, 303}


def test_doctor_queue_canonical_path_renders_and_aliases_redirect(frontend_app, monkeypatch):
    from src.api import doctor_queue as doctor_queue_api

    monkeypatch.setattr(
        doctor_queue_api.DoctorQueueService,
        "queue",
        lambda self: {
            "waiting": [],
            "done": [],
            "work_date": "2026-08-05",
        },
    )

    client = frontend_app.test_client()
    _login(client)

    canonical = client.get("/doctor-queue/")
    assert canonical.status_code == 200
    html = canonical.get_data(as_text=True)
    assert "صف پزشک" in html
    assert "ویزیت فعالی وجود ندارد" in html
    assert "بیماری در انتظار نیست" in html
    assert "تکمیل‌شده امروز" in html
    assert "مرکز کارها" in html
    assert "اتاقِ کنترل" not in html

    no_slash = client.get("/doctor-queue", follow_redirects=False)
    legacy = client.get("/doctor_queue", follow_redirects=False)
    assert no_slash.status_code in {301, 302, 307, 308}
    assert legacy.status_code in {301, 302, 307, 308}
    assert no_slash.headers["Location"].endswith("/doctor-queue/")
    assert legacy.headers["Location"].endswith("/doctor-queue/")


def test_error_pages_use_the_same_native_shell(frontend_app):
    client = frontend_app.test_client()
    _login(client)

    response = client.get("/definitely-missing-page")
    assert response.status_code == 404
    html = response.get_data(as_text=True)

    for label in (
        "خانه",
        "مرکز کارها",
        "بیماران",
        "نوبت‌ها",
        "صف پزشک",
        "مرکز پیام‌ها",
        "امور مالی",
        "موتور بالینی",
        "کاربران",
        "تنظیمات",
    ):
        assert label in html
    assert "اتاقِ کنترل" not in html
    assert "هاب پیام" not in html
    assert 'class="mobile-bottom-nav"' in html


def test_primary_endpoint_names_exist_in_url_map(frontend_app):
    endpoints = {rule.endpoint for rule in frontend_app.url_map.iter_rules()}
    expected = {
        "dashboard.index",
        "unified_followups.index",
        "patients.list_patients",
        "appointments.list_appointments",
        "doctor_queue.index",
        "sms.campaigns",
        "finance_review.index",
        "manager.clinical_engine",
        "manager.users",
        "manager.settings",
    }
    assert expected <= endpoints


def test_shell_assets_and_icon_sprite_are_available(frontend_app):
    client = frontend_app.test_client()
    _login(client)

    for path in (
        "/static/css/shell-automation-v2.css",
        "/static/css/automation-v1.css",
        "/static/js/shell-automation-v2.js",
        "/static/js/automation-v1.js",
    ):
        response = client.get(path)
        assert response.status_code == 200, path

    sprite = (ROOT / "src" / "templates" / "_icon_sprite.html").read_text(
        encoding="utf-8"
    )
    for icon in ("i-home", "i-list-checks", "i-stethoscope", "i-more"):
        assert f'id="{icon}"' in sprite
