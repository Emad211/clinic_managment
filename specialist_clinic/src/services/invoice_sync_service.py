"""Invoice-sync consumer — the read-only seam between accounting and the clinical app.

ADR-0003 (D3+). Each pass polls the accounting DB **read-only** for recently-closed
invoices (via `accounting_bridge`, `mode=ro`) and records them in the specialist
ledger (`processed_invoices`) idempotently, mapping each to a local `patient_links`
row by national_id (or `pending_link` when the patient is not enrolled yet).

Phase 1 = populate the ledger only. The thank-you SMS / procedure-invite triggers are
wired in a later phase through the `on_invoice_processed` seam (a no-op here).

Guarantees: NEVER writes the accounting DB. Idempotent (UNIQUE accounting_invoice_id).
Fail-loud — if the read fails, the exception propagates so the caller does NOT advance
the cursor (no silent data loss).

Cursor: `invoice_sync_last_id` in the settings table = the highest accounting invoice
id consumed. The query also re-checks the last FLOOR_DAYS by `closed_at` to catch a
late-closed, low-id invoice (de-duplicated by the ledger).
"""
from datetime import timedelta

from src.adapters import accounting_bridge
from src.adapters.sqlite.invoice_sync_repo import InvoiceSyncRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.sms_repo import SmsRepository
from src.common.utils import iran_now

CURSOR_KEY = "invoice_sync_last_id"
FLOOR_DAYS = 30          # reconciliation window for late-closed low-id invoices
BATCH_LIMIT = 500


class InvoiceSyncService:
    def __init__(self):
        self.repo = InvoiceSyncRepository()
        self.patients = PatientRepository()
        self.settings = SmsRepository()  # generic key/value settings accessor

    def run(self, limit: int = BATCH_LIMIT) -> dict:
        """One read-only sync pass. Returns {'fetched','new','pending_link','cursor'}."""
        try:
            last_id = int(self.settings.get_setting(CURSOR_KEY, "0") or "0")
        except (TypeError, ValueError):
            last_id = 0
        floor = (iran_now() - timedelta(days=FLOOR_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

        rows = accounting_bridge.fetch_closed_invoices(last_id=last_id, floor_date=floor, limit=limit)
        new = pending = 0
        max_id = last_id
        for r in rows:
            inv_id = r.get("invoice_id")
            if inv_id is None:
                continue
            nid = (r.get("national_id") or "").strip() or None
            link = self.patients.get_by_national_id(nid) if nid else None
            plid = link["id"] if link else None
            status = "applied" if plid else "pending_link"
            inserted = self.repo.record(
                accounting_invoice_id=inv_id, patient_link_id=plid, national_id=nid,
                full_name=r.get("full_name"), work_date=r.get("work_date"),
                closed_at=r.get("closed_at"), total_amount=r.get("total_amount"),
                status=status,
            )
            if inserted:
                new += 1
                if not plid:
                    pending += 1
                self.on_invoice_processed(plid, r)  # seam — Phase 2 (thank-you / invite)
            if inv_id > max_id:
                max_id = inv_id

        # Advance the cursor only after the batch processed without raising (fail-loud).
        if max_id > last_id:
            self.settings.set_setting(CURSOR_KEY, str(max_id))
        return {"fetched": len(rows), "new": new, "pending_link": pending, "cursor": max_id}

    def on_invoice_processed(self, patient_link_id, invoice):
        """Seam for Phase 2 (thank-you SMS / procedure invite). No-op in Phase 1."""
        return
