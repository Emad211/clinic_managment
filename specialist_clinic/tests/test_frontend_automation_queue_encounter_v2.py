from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


@pytest.fixture()
def queue_ui_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "queue-ui.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "queue-ui-test",
        }
    )
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    yield app, client
    core._initialized = False


def _queue_row(invoice_id: int, name: str, status: str) -> dict:
    return {
        "invoice_id": invoice_id,
        "accounting_patient_id": invoice_id + 100,
        "national_id": f"001000{invoice_id:04d}",
        "full_name": name,
        "phone_number": "09120000000",
        "opened_at": "2026-08-05 08:00:00",
        "work_date": "2026-08-05",
        "status": status,
        "patient_link_id": invoice_id + 200,
        "enrolled": True,
        "done_by": "admin" if status == "done" else None,
        "appointment_options": [],
        "linked_appointment_id": None,
        "campaign_response_options": [],
    }


def test_queue_read_failure_renders_controlled_unavailable_state(
    queue_ui_app, monkeypatch
):
    from src.services.doctor_queue_service import DoctorQueueService

    _app, client = queue_ui_app

    def fail(_self):
        raise RuntimeError("RAW_ACCOUNTING_PATH_SHOULD_NOT_RENDER")

    monkeypatch.setattr(DoctorQueueService, "queue", fail)
    response = client.get("/doctor-queue/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "صف پزشک موقتاً در دسترس نیست" in html
    assert "هیچ بیمار یا وضعیت ویزیتی حدس زده نشده است" in html
    assert "RAW_ACCOUNTING_PATH_SHOULD_NOT_RENDER" not in html
    assert "اتاقِ کنترل" not in html


def test_queue_runtime_separates_current_waiting_and_completed(
    queue_ui_app, monkeypatch
):
    from src.services.doctor_queue_service import DoctorQueueService

    _app, client = queue_ui_app
    current = _queue_row(1, "بیمار در حال ویزیت", "in_progress")
    next_patient = _queue_row(2, "بیمار بعدی صف", "waiting")
    completed = _queue_row(3, "بیمار تکمیل شده", "done")

    monkeypatch.setattr(
        DoctorQueueService,
        "queue",
        lambda _self: {
            "waiting": [current, next_patient],
            "done": [completed],
            "work_date": "2026-08-05",
        },
    )
    response = client.get("/doctor-queue/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count('id="current-visit-title"') == 1
    assert html.count('id="waiting-title"') == 1
    assert html.count('id="done-title"') == 1
    assert "در حال ویزیت" in html
    assert "منتظر" in html
    assert "تکمیل‌شده امروز" in html
    assert "بیمار در حال ویزیت" in html
    assert "بیمار بعدی صف" in html
    assert "بیمار تکمیل شده" in html
    assert html.count("data-queue-current-action") == 1
    assert html.count("data-queue-start") == 1
    assert html.count("data-queue-next") == 1
    assert "ادامه مستندسازی" in html
    assert "شروع ویزیت" in html


def test_queue_template_keeps_start_explicit_and_optional_links_progressive():
    queue = read("src/templates/doctor_queue/queue.html")
    assert "active_visits" in queue
    assert "queued_visits" in queue
    assert "queue_unavailable" in queue
    assert "data-queue-next" in queue
    assert "data-queue-start" in queue
    assert "اتصال اختیاری نوبت یا کمپین" in queue
    assert "requestSubmit" not in queue
    assert "autofocus" not in queue


def test_finalisation_returns_to_queue_with_next_focus_but_never_auto_starts():
    route = read("src/api/doctor_queue.py")
    automation = read("src/static/js/automation-v1.js")

    assert route.count('url_for("doctor_queue.index", focus="next")') == 2
    assert "ویزیت نهایی شد؛ بیمار بعدی در صف آماده است." in route
    assert "requested === 'next'" in automation
    assert "qs('[data-queue-next]')" in automation
    assert "next.focus({ preventScroll: true })" in automation

    focus_function = re.search(
        r"function setupAutoNextFocus\(\) \{(?P<body>.*?)\n  \}",
        automation,
        flags=re.DOTALL,
    )
    assert focus_function
    body = focus_function.group("body")
    assert ".click(" not in body
    assert "requestSubmit" not in body
    assert ".submit(" not in body


def test_encounter_stays_three_step_one_confirm_and_no_fake_autosave():
    page = read("src/templates/doctor_queue/visit_quick.html")
    automation_base = read("src/templates/automation_base.html")
    css = read("src/static/css/queue-encounter-automation-v2.css")

    for title in (
        "شرح حال و معاینه",
        "ارزیابی و برنامه",
        "پیگیری بعد از ویزیت",
    ):
        assert page.count(title) >= 1
    assert page.count("confirm(") == 1
    assert "پایان ویزیت" in page
    assert "ذخیره پیش‌نویس" in page
    assert "Ctrl/⌘ + S" in page
    assert 'data-autosave="server"' not in page
    assert "localStorage" not in page
    assert "sessionStorage" not in page
    assert "queue-encounter-automation-v2.css" in automation_base
    assert "request.endpoint == 'doctor_queue.visit'" in automation_base
    assert ".encounter-workspace" in css
    assert "@media(max-width:700px)" in css


def test_queue_assets_and_canonical_aliases_are_available(queue_ui_app):
    _app, client = queue_ui_app
    css = client.get("/static/css/queue-encounter-automation-v2.css")
    assert css.status_code == 200
    assert css.data

    for path in ("/doctor-queue", "/doctor_queue"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code in {301, 302, 307, 308}
        assert "/doctor-queue/" in response.headers["Location"]


def test_touched_javascript_is_syntactically_valid_when_node_is_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed in this test environment")
    result = subprocess.run(
        [node, "--check", str(ROOT / "src/static/js/automation-v1.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
