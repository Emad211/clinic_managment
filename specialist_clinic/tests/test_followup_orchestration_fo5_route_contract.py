from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask
from werkzeug.exceptions import NotFound

from src.api.unified_followups import (
    _contact_callback_value,
    _require_structured_contact_flag,
)
from src.common.utils import jalali_to_gregorian_str
from src.services.followup_orchestration.structured_contact_service import (
    FollowupStructuredContactError,
)


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]


def _flag_app(*, routing: bool) -> Flask:
    app = Flask(__name__)
    app.config.update(
        FOLLOWUP_UNIFIED_WORKLIST_READONLY=True,
        FOLLOWUP_UNIFIED_WORKLIST_ACTIONS=True,
        FOLLOWUP_AUTO_ROUTING=routing,
        FOLLOWUP_STRUCTURED_CONTACT=True,
    )
    return app


def test_structured_contact_guard_requires_routing_kill_switch():
    with _flag_app(routing=False).test_request_context("/"):
        with pytest.raises(NotFound):
            _require_structured_contact_flag()

    with _flag_app(routing=True).test_request_context("/"):
        _require_structured_contact_flag()


def test_callback_form_parses_jalali_date_and_time_server_side():
    app = Flask(__name__)
    with app.test_request_context(
        "/",
        method="POST",
        data={
            "callback_date": "1405/05/14",
            "callback_time": "11:30",
        },
    ):
        expected_date = jalali_to_gregorian_str("1405/05/14")
        assert _contact_callback_value() == f"{expected_date} 11:30:00"

    with app.test_request_context(
        "/",
        method="POST",
        data={"callback_date": "1405/05/14", "callback_time": ""},
    ):
        with pytest.raises(FollowupStructuredContactError) as incomplete:
            _contact_callback_value()
        assert incomplete.value.code == "INVALID_CALLBACK_AT"

    with app.test_request_context(
        "/",
        method="POST",
        data={"callback_date": "تاریخ نامعتبر", "callback_time": "11:30"},
    ):
        with pytest.raises(FollowupStructuredContactError) as invalid:
            _contact_callback_value()
        assert invalid.value.code == "INVALID_CALLBACK_AT"


def test_contact_ui_uses_existing_jalali_date_control():
    api = (
        SPECIALIST_ROOT / "src" / "api" / "unified_followups.py"
    ).read_text(encoding="utf-8")
    partial = (
        SPECIALIST_ROOT / "src" / "templates" / "followups" /
        "_structured_contact_detail.html"
    ).read_text(encoding="utf-8")

    assert "and routing_enabled" in api
    assert "jalali_to_gregorian_str" in api
    assert 'name="callback_date"' in partial
    assert 'class="jdate"' in partial
    assert 'name="callback_time"' in partial
    assert 'type="time"' in partial
    assert 'type="datetime-local"' not in partial
