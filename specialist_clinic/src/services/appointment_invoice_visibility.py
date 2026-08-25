"""Visibility-only bridge between a booked appointment and accounting.

Fix #6 (owner decision: *visibility only*). A booked specialist appointment has
**no in-app path to a visit/revenue** unless the accounting app has already
opened an invoice with a visit item for that patient on that day — the physician
queue is built entirely from open accounting invoices. When the front desk books
in the specialist app but forgets to open the accounting invoice, the visit
silently never reaches the doctor queue. This service makes that gap *visible*
without ever closing it automatically.

Contract (A0/A4 — do not weaken):
    * This is a READ-ONLY label. It creates **no revenue, no CareEncounter, no
      attribution, no appointment link, and writes nothing** — to either
      database. It only tags each of *today's* scheduled appointments with a
      3-state hint so the front desk knows to open the accounting invoice first.
    * The three states are deliberate and must never collapse into each other:
        - ``has``     : an OPEN accounting visit invoice exists today for this
                        patient's national_id.
        - ``none``    : the accounting bridge answered and this national_id is
                        NOT among today's open visit invoices — a real gap.
        - ``unknown`` : the accounting bridge is unavailable / failed, OR the
                        appointment has no national_id to match on. We do NOT
                        know, so we must NOT imply a gap (never render as
                        ``none``/zero). This is the A0/A4 "unavailable is not
                        zero" rule applied to a visibility surface.
    * Matching is by ``national_id`` only, and only for a *label*. It is not an
      attribution and never links the appointment to an invoice or Encounter.
"""
from __future__ import annotations

from typing import Any, Iterable

from src.adapters import accounting_bridge
from src.adapters.accounting_bridge import AccountingBridgeError


class AppointmentInvoiceVisibility:
    """Annotate today's scheduled appointments with an open-invoice hint."""

    HAS = "has"
    NONE = "none"
    UNKNOWN = "unknown"

    def annotate(
        self,
        appointments: Iterable[dict[str, Any]],
        *,
        today: str,
    ) -> dict[str, int]:
        """Tag each of *today's* scheduled appointments with ``invoice_visibility``.

        Returns a small summary: ``{'has', 'none', 'unknown', 'considered'}``.
        Mutates the dicts in-place (adds ``invoice_visibility``) but performs no
        database writes of any kind.
        """
        todays = [
            appt
            for appt in appointments
            if str(appt.get("status") or "") == "scheduled"
            and str(appt.get("scheduled_at") or "")[:10] == today
        ]
        summary = {"has": 0, "none": 0, "unknown": 0, "considered": len(todays)}
        if not todays:
            return summary

        try:
            open_invoices = accounting_bridge.fetch_open_visit_invoices(
                work_date=today
            )
        except AccountingBridgeError:
            # Unavailable/failed bridge is NOT "no invoice". Never fabricate a gap.
            for appt in todays:
                appt["invoice_visibility"] = self.UNKNOWN
            summary["unknown"] = len(todays)
            return summary

        open_national_ids = {
            str(row.get("national_id") or "").strip()
            for row in open_invoices
            if str(row.get("national_id") or "").strip()
        }
        for appt in todays:
            national_id = str(appt.get("national_id") or "").strip()
            if not national_id:
                # No identity to match on => unknown, not a gap.
                appt["invoice_visibility"] = self.UNKNOWN
                summary["unknown"] += 1
            elif national_id in open_national_ids:
                appt["invoice_visibility"] = self.HAS
                summary["has"] += 1
            else:
                appt["invoice_visibility"] = self.NONE
                summary["none"] += 1
        return summary
