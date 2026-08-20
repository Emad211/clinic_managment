"""Focused contracts for the manager Revenue & operational-value cockpit.

These tests protect the three invariants that make the cockpit safe to show a
manager (A0/A4):

1. A missing/stale/unreconciled financial snapshot is reported as *unavailable*
   with a true Persian reason — never degraded to a zero revenue figure.
2. The five A4 stages are independent populations, so a stage-to-stage rate is
   published only when the subset relation genuinely holds (a walk-in makes
   `attended` exceed `booked`, and no ">100%" ratio may reach the screen).
3. Appointment volume is a count, never money; every operational block is marked
   `value_provable: False`.

Part A exercises `RevenueCockpitService` in isolation with injected fakes (no DB,
no accounting bridge, fixed clock). Part B runs the real `AppointmentRepository`
aggregates on a throwaway specialist DB. Part C renders the real route through the
real service with money forced unavailable. Nothing here sends SMS or opens the
accounting DB.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.services.revenue_cockpit_service import (
    RevenueCockpitService,
    UNAVAILABLE_REASONS,
)
from src.services.revenue_service import RevenueService


ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 8, 20, 12, 0, 0)


def _clock():
    return FIXED_NOW


class _FakeRevenue:
    """Stands in for the single financial authority; returns a canned projection."""

    def __init__(self, projection):
        self._projection = projection

    def dashboard(self):
        return self._projection


class _FakeAppointments:
    """Count-only appointment aggregates with no database behind them."""

    def __init__(self, *, counts=None, lost=None, ahead=0):
        self._counts = counts or {}
        self._lost = lost or []
        self._ahead = ahead

    def outcome_counts(self, date_from, date_to):
        return dict(self._counts)

    def lost_opportunities(self, date_from, date_to, *, limit=20):
        # Copy so the service's in-place decoration cannot leak across tests.
        return [dict(row) for row in self._lost[:limit]]

    def scheduled_ahead_count(self, date_to):
        return self._ahead


def _service(projection, appointments=None):
    return RevenueCockpitService(
        revenue=_FakeRevenue(projection),
        appointments=appointments or _FakeAppointments(),
        clock=_clock,
    )


# --------------------------------------------------------------------------- #
# Part A — service composition (no DB)
# --------------------------------------------------------------------------- #

def test_money_unavailable_states_reason_and_never_zeroes():
    code = "ACCOUNTING_DATABASE_UNAVAILABLE"
    payload = _service(
        {
            "available": False,
            "error_code": code,
            "scope": {},
            "funnel": {},
        }
    ).cockpit()
    money = payload["money"]

    assert money["available"] is False
    assert money["error_code"] == code
    # The reason is the exact catalogued Persian text, not a stand-in.
    assert money["reason"] == UNAVAILABLE_REASONS[code]["text"]
    assert money["reason"].strip()
    assert money["reconcile_helps"] is False
    assert money["freshness_minutes"] == RevenueService.FRESHNESS_MINUTES == 15
    # The forbidden degradation: no zeroed money figure may appear at the top of
    # the money block when it is unavailable.
    for forbidden in ("month", "total", "trend", "enrolled"):
        assert forbidden not in money

    # Operations stay visible even when money is absent — the case a manager acts on.
    assert payload["operations"]["window"]["days"] == 30
    assert len(payload["funnel"]["stages"]) == 5


def test_unknown_error_code_falls_back_without_crashing():
    payload = _service(
        {"available": False, "error_code": "SOMETHING_NEW", "scope": {}, "funnel": {}}
    ).cockpit()
    money = payload["money"]
    # An uncatalogued code degrades to the generic revenue-error reason, still Persian,
    # still never a number.
    assert money["available"] is False
    assert money["reason"] == UNAVAILABLE_REASONS["DASHBOARD_REVENUE_ERROR"]["text"]
    assert money["reconcile_helps"] is False


def test_reconcile_flag_tracks_reason_table():
    payload = _service(
        {
            "available": False,
            "error_code": "FINANCIAL_RECONCILIATION_INCOMPLETE",
            "scope": {"missing_observations": 3, "eligible_invoices": 11},
            "funnel": {},
        }
    ).cockpit()
    money = payload["money"]
    assert money["reconcile_helps"] is True
    assert money["missing_observations"] == 3
    assert money["eligible_invoices"] == 11


def test_money_available_passes_through_authoritative_figures():
    projection = {
        "available": True,
        "enrolled": 42,
        "month": {"collected": 1_200_000, "total": 1_500_000},
        "total": {"collected": 9_000_000, "total": 10_000_000, "invoices": 30},
        "trend": {"labels": ["a", "b"], "billed_values": [1, 2], "collected_values": [1, 1]},
        "payer_review": {
            "safe_to_sum": True,
            "adjusted_collected": 8_800_000,
            "reviewed_invoices": 25,
            "pending_review": 0,
        },
        "scope": {"observation_age_minutes": 4, "policy_version": "REVENUE_V3"},
        "funnel": {"booked": 5, "attended": 5},
        "campaigns": {"rows": [], "safe_to_sum": False, "measurement_status": "READY"},
    }
    payload = _service(projection).cockpit()
    money = payload["money"]

    assert money["available"] is True
    assert money["enrolled"] == 42
    assert money["month"] == {"collected": 1_200_000, "total": 1_500_000}
    assert money["total"]["invoices"] == 30
    assert money["observation_age_minutes"] == 4
    assert money["policy_version"] == "REVENUE_V3"
    assert money["freshness_minutes"] == 15
    # campaigns comes from the projection, not the JOURNEY_LINK fallback, when present.
    assert payload["campaigns"]["measurement_status"] == "READY"


def test_funnel_suppresses_impossible_rate_but_keeps_valid_subset():
    # attended (12) > booked (10): a walk-in encounter with no linked appointment.
    funnel = {
        "booked": 10,
        "attended": 12,
        "service_completed": 9,
        "invoice_closed": 6,
        "collected": 6,
        "partially_collected": 2,
        "unpaid": 1,
    }
    payload = _service({"available": False, "error_code": "X", "scope": {}, "funnel": funnel}).cockpit()
    stages = {s["key"]: s for s in payload["funnel"]["stages"]}

    assert stages["booked"]["rate"] is None  # first stage has nothing to divide by
    assert stages["attended"]["rate"] is None  # 12/10 would be >100% → suppressed
    assert stages["attended"]["of_label"] == "نوبت رزروشده"
    assert stages["service_completed"]["rate"] == 75  # 9/12
    assert stages["invoice_closed"]["rate"] == 67  # 6/9 rounded
    assert stages["collected"]["rate"] == 100  # 6/6

    collection = {c["key"]: c for c in payload["funnel"]["collection"]}
    assert collection["collected"]["count"] == 6
    assert collection["unpaid"]["tone"] == "danger"
    assert payload["funnel"]["collection_total"] == 6 + 2 + 1
    assert payload["funnel"]["stages_are_independent"] is True


def test_operations_are_counts_only_with_derived_rates():
    counts = {
        "scheduled": 5,
        "done": 6,
        "no_show": 2,
        "cancelled": 2,
        "other": 0,
        "total": 15,
    }
    lost = [
        {
            "id": 1,
            "patient_link_id": 7,
            "scheduled_at": "2026-08-12 09:30:00",
            "status": "no_show",
            "appt_type": "visit",
            "patient_name": "بیمار الف",
            "phone_number": "0912",
        },
        {
            "id": 2,
            "patient_link_id": 8,
            "scheduled_at": "2026-08-10 11:00:00",
            "status": "cancelled",
            "appt_type": "lab",
            "patient_name": "بیمار ب",
            "phone_number": None,
        },
    ]
    payload = _service(
        {"available": False, "error_code": "X", "scope": {}, "funnel": {}},
        appointments=_FakeAppointments(counts=counts, lost=lost, ahead=4),
    ).cockpit()
    ops = payload["operations"]

    assert ops["decided"] == 10  # done + no_show + cancelled
    assert ops["attendance_rate"] == 60  # 6/10
    assert ops["lost"]["count"] == 4
    assert ops["lost"]["rate"] == 40  # 4/10
    assert ops["lost"]["value_provable"] is False
    assert ops["ahead"]["count"] == 4
    assert ops["ahead"]["value_provable"] is False

    # Lost rows are decorated for the drill-down, and a no-show maps to its label/tone.
    first = ops["lost"]["rows"][0]
    assert first["status_label"] == "عدم مراجعه"
    assert first["status_tone"] == "danger"
    assert first["scheduled_fa"]  # jalali formatting applied, non-empty


def test_campaigns_fall_back_to_journey_link_required_when_absent():
    payload = _service(
        {"available": False, "error_code": "X", "scope": {}, "funnel": {}}
    ).cockpit()
    campaigns = payload["campaigns"]
    assert campaigns["rows"] == []
    assert campaigns["safe_to_sum"] is False
    assert campaigns["measurement_status"] == "JOURNEY_LINK_REQUIRED"


# --------------------------------------------------------------------------- #
# fixtures for DB-backed tests
# --------------------------------------------------------------------------- #

@pytest.fixture()
def cockpit_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "cockpit.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "revenue-cockpit-test",
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


# --------------------------------------------------------------------------- #
# Part B — real appointment aggregates on a throwaway DB
# --------------------------------------------------------------------------- #

def test_appointment_aggregates_on_temp_db(cockpit_app):
    from src.adapters.sqlite.appointments_repo import AppointmentRepository
    from src.adapters.sqlite.core import get_db

    db = get_db()
    db.execute(
        "INSERT INTO patient_links (national_id, full_name, phone_number) "
        "VALUES (?, ?, ?)",
        ("COCKPIT01", "بیمار آزمایشی", "09120000000"),
    )
    db.commit()
    pid = db.execute(
        "SELECT id FROM patient_links WHERE national_id=?", ("COCKPIT01",)
    ).fetchone()["id"]

    repo = AppointmentRepository()
    # Four appointments inside the August window, one per stored status.
    in_window = {
        "done": "2026-08-05 09:00:00",
        "no_show": "2026-08-06 10:00:00",
        "cancelled": "2026-08-07 11:00:00",
    }
    for status, when in in_window.items():
        appt_id = repo.create(pid, scheduled_at=when, appt_type="visit")
        repo.set_status(appt_id, status)
    # One still-scheduled row inside the window.
    repo.create(pid, scheduled_at="2026-08-08 12:00:00", appt_type="visit")
    # A far-future scheduled row (ahead) and a far-past scheduled row (not ahead) —
    # dates chosen years away so the wall-clock `now` inside the aggregate is
    # unambiguous regardless of when the test runs.
    repo.create(pid, scheduled_at="2030-01-01 09:00:00", appt_type="checkup")
    repo.create(pid, scheduled_at="2020-01-01 09:00:00", appt_type="checkup")

    counts = repo.outcome_counts("2026-08-01", "2026-08-31")
    assert counts["done"] == 1
    assert counts["no_show"] == 1
    assert counts["cancelled"] == 1
    assert counts["scheduled"] == 1  # only the in-window scheduled row
    assert counts["total"] == 4  # far-future/far-past rows are outside the window

    lost = repo.lost_opportunities("2026-08-01", "2026-08-31", limit=20)
    assert {row["status"] for row in lost} == {"no_show", "cancelled"}
    assert all(row["patient_link_id"] == pid for row in lost)

    ahead = repo.scheduled_ahead_count("2031-12-31")
    assert ahead >= 1  # the 2030 scheduled row is ahead of now
    # The 2020 scheduled row is in the past → never counted as ahead.
    assert repo.scheduled_ahead_count("2019-12-31") == 0


# --------------------------------------------------------------------------- #
# Part C — the real route renders through the real service
# --------------------------------------------------------------------------- #

def test_cockpit_route_renders_end_to_end(cockpit_app):
    client = cockpit_app.test_client()
    _login(client)
    response = client.get("/revenue-cockpit/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # The always-present sections render regardless of the money branch.
    assert "درآمد و عملکرد" in html
    assert "قیفِ حضور تا وصول" in html
    assert "عملکردِ نوبت‌ها" in html
    assert "اقتصادِ کمپین‌ها" in html


def test_cockpit_route_renders_unavailable_money_branch(cockpit_app, monkeypatch):
    # Force the six-code unavailable projection so the never-zero template branch is
    # exercised deterministically, while the real RevenueCockpitService composition,
    # the real appointment aggregates and the real template all run.
    monkeypatch.setattr(
        RevenueService,
        "dashboard",
        lambda self: {
            "available": False,
            "error_code": "FINANCIAL_OBSERVATION_STALE",
            "scope": {"observation_age_minutes": 999, "eligible_invoices": 4},
            "funnel": {"booked": 3, "attended": 2, "collected": 1, "unpaid": 1},
        },
    )
    client = cockpit_app.test_client()
    _login(client)
    response = client.get("/revenue-cockpit/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "درآمد فعلاً قابل‌اثبات نیست" in html
    assert "FINANCIAL_OBSERVATION_STALE" in html
    assert UNAVAILABLE_REASONS["FINANCIAL_OBSERVATION_STALE"]["text"] in html
    # Operations + funnel are still on the page when money is unavailable.
    assert "قیفِ حضور تا وصول" in html
    assert "عملکردِ نوبت‌ها" in html


def test_cockpit_route_requires_login(cockpit_app):
    client = cockpit_app.test_client()
    response = client.get("/revenue-cockpit/", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/auth/login" in response.headers.get("Location", "")
