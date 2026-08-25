"""Fix #6 — visibility-only open-invoice hint for booked appointments.

Owner decision: *visibility only*. A booked specialist appointment reaches the
physician queue only if the accounting app already has an OPEN visit invoice for
that patient today. This service tags today's scheduled appointments with a
3-state hint (has / none / unknown) so the front desk knows to open the
accounting invoice first — WITHOUT creating any revenue, Encounter, attribution,
link, or write to either database.

These tests exercise the pure service on plain dicts and monkeypatch
``accounting_bridge.fetch_open_visit_invoices`` — no real DB, no accounting DB,
no SMS. The A0/A4 rule under test: an unavailable/failed bridge must render as
``unknown`` and NEVER as a fabricated ``none``/zero gap.

Run from the specialist_clinic directory:
    .venv/Scripts/python.exe -m pytest tests/test_appointment_invoice_visibility.py -v
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

_SPECIALIST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SPECIALIST_ROOT not in sys.path:
    sys.path.insert(0, _SPECIALIST_ROOT)

import pytest

from src.adapters import accounting_bridge
from src.adapters.accounting_bridge import (
    AccountingBridgeError,
    AccountingBridgeQueryError,
    AccountingBridgeUnavailable,
)
from src.services.appointment_invoice_visibility import AppointmentInvoiceVisibility


TODAY = "2026-06-20"
YESTERDAY = "2026-06-19"


def _appt(nid=None, *, status="scheduled", day=TODAY, appt_id=1):
    """A minimal appointment dict shaped like AppointmentRepository.list_range()."""
    return {
        "id": appt_id,
        "national_id": nid,
        "status": status,
        "scheduled_at": f"{day} 10:30:00",
        "patient_name": "بیمار آزمون",
    }


# ---------------------------------------------------------------------------
# 3-state core: has / none / unknown
# ---------------------------------------------------------------------------

class TestThreeStateAnnotation:

    def test_has_when_open_invoice_matches_national_id(self, monkeypatch):
        monkeypatch.setattr(
            accounting_bridge, "fetch_open_visit_invoices",
            lambda work_date=None, limit=200: [{"national_id": "111"}],
        )
        appts = [_appt("111")]
        summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)
        assert appts[0]["invoice_visibility"] == "has"
        assert summary == {"has": 1, "none": 0, "unknown": 0, "considered": 1}

    def test_none_when_bridge_answers_but_no_open_invoice(self, monkeypatch):
        """Bridge reachable, this national_id absent from today's open invoices
        → a REAL gap, must be 'none' (not unknown)."""
        monkeypatch.setattr(
            accounting_bridge, "fetch_open_visit_invoices",
            lambda work_date=None, limit=200: [{"national_id": "999"}],
        )
        appts = [_appt("111")]
        summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)
        assert appts[0]["invoice_visibility"] == "none"
        assert summary == {"has": 0, "none": 1, "unknown": 0, "considered": 1}

    def test_none_when_bridge_returns_empty(self, monkeypatch):
        """Empty list is a legitimate 'no open visit invoices' answer, not a failure."""
        monkeypatch.setattr(
            accounting_bridge, "fetch_open_visit_invoices",
            lambda work_date=None, limit=200: [],
        )
        appts = [_appt("111")]
        summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)
        assert appts[0]["invoice_visibility"] == "none"
        assert summary["none"] == 1

    def test_unknown_when_appointment_has_no_national_id(self, monkeypatch):
        """No identity to match on → unknown, never a fabricated gap."""
        monkeypatch.setattr(
            accounting_bridge, "fetch_open_visit_invoices",
            lambda work_date=None, limit=200: [{"national_id": "111"}],
        )
        for nid in (None, "", "   "):
            appts = [_appt(nid)]
            summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)
            assert appts[0]["invoice_visibility"] == "unknown", f"nid={nid!r}"
            assert summary == {"has": 0, "none": 0, "unknown": 1, "considered": 1}


# ---------------------------------------------------------------------------
# A0/A4: bridge unavailable/failed must be 'unknown', NEVER 'none'/zero
# ---------------------------------------------------------------------------

class TestBridgeFailureIsUnknownNotGap:

    @pytest.mark.parametrize("exc", [
        AccountingBridgeUnavailable("db missing"),
        AccountingBridgeQueryError("read failed"),
        AccountingBridgeError("base failure"),
    ])
    def test_bridge_raise_marks_all_today_unknown(self, monkeypatch, exc):
        def raiser(work_date=None, limit=200):
            raise exc
        monkeypatch.setattr(accounting_bridge, "fetch_open_visit_invoices", raiser)

        appts = [_appt("111"), _appt("222", appt_id=2)]
        summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)

        assert all(a["invoice_visibility"] == "unknown" for a in appts)
        assert summary == {"has": 0, "none": 0, "unknown": 2, "considered": 2}
        # The A0/A4 invariant, stated bluntly: a broken bridge is not a gap.
        assert summary["none"] == 0

    def test_unavailable_is_a_subclass_caught_by_base(self):
        assert issubclass(AccountingBridgeUnavailable, AccountingBridgeError)
        assert issubclass(AccountingBridgeQueryError, AccountingBridgeError)


# ---------------------------------------------------------------------------
# Scope: only TODAY's SCHEDULED appointments are considered/mutated
# ---------------------------------------------------------------------------

class TestScopeOnlyTodayScheduled:

    def test_non_today_appointment_is_untouched(self, monkeypatch):
        monkeypatch.setattr(
            accounting_bridge, "fetch_open_visit_invoices",
            lambda work_date=None, limit=200: [{"national_id": "111"}],
        )
        appts = [_appt("111", day=YESTERDAY)]
        summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)
        assert "invoice_visibility" not in appts[0]
        assert summary == {"has": 0, "none": 0, "unknown": 0, "considered": 0}

    def test_non_scheduled_today_appointment_is_untouched(self, monkeypatch):
        monkeypatch.setattr(
            accounting_bridge, "fetch_open_visit_invoices",
            lambda work_date=None, limit=200: [{"national_id": "111"}],
        )
        for status in ("done", "no_show", "cancelled"):
            appts = [_appt("111", status=status)]
            summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)
            assert "invoice_visibility" not in appts[0], status
            assert summary["considered"] == 0, status

    def test_bridge_not_called_when_no_today_scheduled(self, monkeypatch):
        """No relevant appointments → the bridge is never even queried."""
        calls = []

        def spy(work_date=None, limit=200):
            calls.append(work_date)
            return []
        monkeypatch.setattr(accounting_bridge, "fetch_open_visit_invoices", spy)

        appts = [_appt("111", day=YESTERDAY), _appt("222", status="done", appt_id=2)]
        summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)
        assert calls == [], "bridge must not be queried when nothing is due"
        assert summary["considered"] == 0

    def test_mixed_cohort_counts_and_query_uses_today(self, monkeypatch):
        """A realistic mix; also asserts the bridge is filtered by today's date."""
        calls = []

        def spy(work_date=None, limit=200):
            calls.append(work_date)
            return [{"national_id": "111"}, {"national_id": ""}]
        monkeypatch.setattr(accounting_bridge, "fetch_open_visit_invoices", spy)

        appts = [
            _appt("111", appt_id=1),                    # has
            _appt("222", appt_id=2),                    # none
            _appt(None, appt_id=3),                     # unknown (no nid)
            _appt("333", day=YESTERDAY, appt_id=4),     # skipped (not today)
            _appt("444", status="done", appt_id=5),     # skipped (not scheduled)
        ]
        summary = AppointmentInvoiceVisibility().annotate(appts, today=TODAY)

        assert calls == [TODAY], "bridge must be filtered by today's work_date"
        assert summary == {"has": 1, "none": 1, "unknown": 1, "considered": 3}
        assert appts[0]["invoice_visibility"] == "has"
        assert appts[1]["invoice_visibility"] == "none"
        assert appts[2]["invoice_visibility"] == "unknown"
        assert "invoice_visibility" not in appts[3]
        assert "invoice_visibility" not in appts[4]


# ---------------------------------------------------------------------------
# Purity: the service performs no DB access beyond the (monkeypatched) bridge
# ---------------------------------------------------------------------------

class TestPurityNoWrites:

    def test_empty_input_returns_zero_summary_without_calling_bridge(self, monkeypatch):
        def boom(work_date=None, limit=200):
            raise AssertionError("bridge must not be called for empty input")
        monkeypatch.setattr(accounting_bridge, "fetch_open_visit_invoices", boom)
        summary = AppointmentInvoiceVisibility().annotate([], today=TODAY)
        assert summary == {"has": 0, "none": 0, "unknown": 0, "considered": 0}

    def test_service_never_opens_a_real_connection(self, monkeypatch):
        """Guard: annotate() must go through fetch_open_visit_invoices only and
        never open its own accounting connection (_connect_ro)."""
        opened = []
        if hasattr(accounting_bridge, "_connect_ro"):
            def tripwire(*a, **k):
                opened.append(True)
                raise AssertionError("annotate() must not open a raw RO connection")
            monkeypatch.setattr(accounting_bridge, "_connect_ro", tripwire)
        monkeypatch.setattr(
            accounting_bridge, "fetch_open_visit_invoices",
            lambda work_date=None, limit=200: [{"national_id": "111"}],
        )
        AppointmentInvoiceVisibility().annotate([_appt("111")], today=TODAY)
        assert opened == []
