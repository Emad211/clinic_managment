from __future__ import annotations

from argparse import Namespace

import start


def test_missing_accounting_connection_does_not_block_settings_ui_startup():
    report = {
        "checks": [
            {
                "name": "accounting_bridge_read_only",
                "ok": False,
                "required": True,
            },
            {"name": "database_integrity", "ok": True, "required": True},
        ]
    }

    assert start._startup_blockers(report) == []


def test_non_configurable_preflight_failure_still_blocks_startup():
    report = {
        "checks": [
            {"name": "database_integrity", "ok": False, "required": True},
            {
                "name": "accounting_bridge_read_only",
                "ok": False,
                "required": True,
            },
        ]
    }

    assert [item["name"] for item in start._startup_blockers(report)] == [
        "database_integrity"
    ]


def test_second_launch_opens_existing_clinic_instead_of_starting_again(
    monkeypatch,
):
    opened: list[int] = []
    monkeypatch.setattr(start, "_clinic_is_live", lambda _port: True)
    monkeypatch.setattr(
        start,
        "_launch_browser",
        lambda port: opened.append(port) or True,
    )

    result = start._serve(
        Namespace(host="127.0.0.1", port=8090, no_browser=False)
    )

    assert result == 0
    assert opened == [8090]


def test_second_launch_respects_no_browser(monkeypatch):
    monkeypatch.setattr(start, "_clinic_is_live", lambda _port: True)
    monkeypatch.setattr(
        start,
        "_launch_browser",
        lambda _port: (_ for _ in ()).throw(AssertionError("must not open")),
    )

    result = start._serve(
        Namespace(host="127.0.0.1", port=8090, no_browser=True)
    )

    assert result == 0


def test_browser_waits_for_live_endpoint(monkeypatch):
    probes = iter((False, False, True))
    opened: list[int] = []
    monkeypatch.setattr(start, "_clinic_is_live", lambda _port: next(probes))
    monkeypatch.setattr(start.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        start,
        "_launch_browser",
        lambda port: opened.append(port) or True,
    )

    assert start._open_browser_when_live(8090, timeout=2) is True
    assert opened == [8090]


def test_windows_browser_launch_uses_shell(monkeypatch):
    from src import app

    opened: list[str] = []
    monkeypatch.setattr(app.os, "name", "nt")
    monkeypatch.setattr(
        app.os,
        "startfile",
        lambda url: opened.append(url),
        raising=False,
    )

    assert app.open_browser(port=8123) is True
    assert opened == ["http://127.0.0.1:8123/"]
