from __future__ import annotations

import time
from dataclasses import replace

import pytest

from src.app import create_app
from src.config.settings import load_settings


@pytest.fixture
def settings(tmp_path, acc_db):
    return replace(load_settings(tmp_path), accounting_db_path=str(acc_db))


def test_healthz_identifies_app(settings):
    app = create_app(settings, start_background=False)
    resp = app.test_client().get("/healthz")
    assert resp.status_code == 200 and resp.get_json()["app"] == "peygiri-panel"


def test_health_is_local_only_and_reports_bridge(settings):
    app = create_app(settings, start_background=False)
    app.extensions["peygiri"].monitor.check_now()
    client = app.test_client()
    body = client.get("/health").get_json()
    assert body["bridge"]["state"] == "ok" and body["bridge"]["enabled"] is True
    assert client.get("/health", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 403


def test_index_renders_rtl_status(settings):
    app = create_app(settings, start_background=False)
    app.extensions["peygiri"].monitor.check_now()
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'dir="rtl"' in html and "متصل" in html


def test_runs_without_accounting_path(tmp_path):
    app = create_app(load_settings(tmp_path), start_background=False)
    assert app.extensions["peygiri"].monitor.check_now().state == "disabled"
    html = app.test_client().get("/").get_data(as_text=True)
    assert "غیرفعال" in html and "db_path" in html


def test_background_thread_starts_and_stops(settings):
    app = create_app(settings, start_background=True)
    rt = app.extensions["peygiri"]
    deadline = time.monotonic() + 3
    while rt.monitor.status.state == "unchecked" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert rt.monitor.status.state == "ok"
    rt.shutdown(timeout=2)
    assert all(not t.is_alive() for t in rt.threads)
