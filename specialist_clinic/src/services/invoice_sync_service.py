"""Invoice-sync consumer — the read-only seam between accounting and the clinical app.

ADR-0003 (D3+). Each pass polls the accounting DB **read-only** for recently-closed
invoices (via `accounting_bridge`, `mode=ro`) and records them in the specialist
ledger (`processed_invoices`) idempotently, mapping each to a local `patient_links`
row by national_id (or `pending_link` when the patient is not enrolled yet).

Phase 1 = populate the ledger only. The thank-you SMS / procedure-invite triggers are
wired in a later phase through the `on_invoice_processed` seam (a no-op here).

Guarantees: NEVER writes the accounting DB. Idempotent (UNIQUE accounting_invoice_id).
Fail-loud on READ — if the accounting read fails the exception propagates so the caller
does NOT advance the cursor (no skipped invoices). Outreach (thank-you / invite) is
DECOUPLED from the ledger via the `outreach_done` flag and retried on later passes until
it actually succeeds, so a transient enqueue failure never silently loses the SMS
(at-least-once; per-row guarded so one bad row blocks neither the cursor nor the rest).

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

# Free-text accounting procedure_type → follow-up invite event (keyword match). The
# accounting app stores procedure_type as free text, so we match by keyword; calibrate
# against real `SELECT DISTINCT procedure_type` data over time.
_PROCEDURE_KEYWORDS = (
    (("گوش", "شستشو"), "ear_wash_invite"),
    (("پانسمان", "بخیه", "دِرِسینگ", "درسینگ"), "wound_care_invite"),
)


def _procedure_event_key(description):
    """Map a free-text procedure/injection description to a follow-up event_key (or None)."""
    d = description or ""
    for keywords, event_key in _PROCEDURE_KEYWORDS:
        if any(k in d for k in keywords):
            return event_key
    return None


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
            # Outreach is DECOUPLED from the ledger idempotency key: gated on
            # `outreach_done`, not on `inserted`. A closed invoice is recorded once, but
            # its thank-you/invite is retried on later passes until it succeeds — so a
            # transient failure (e.g. a DB lock mid-enqueue) never silently loses the SMS.
            # enqueue is itself idempotent (engagement period_key). Per-row guarded so one
            # bad row blocks neither the cursor nor the other rows' outreach. (Freshly
            # inserted rows are outreach_done=0 by definition, so skip the extra read.)
            if plid and (inserted or not self.repo.outreach_done(inv_id)):
                try:
                    self.on_invoice_processed(plid, r)
                    self.repo.mark_outreach_done(inv_id)
                except Exception as e:  # deferred — retried next pass within the FLOOR window
                    print(f"[invoice-sync] outreach deferred for invoice {inv_id}: {e}")
            if inv_id > max_id:
                max_id = inv_id

        # Advance the cursor only after the batch processed without raising (fail-loud).
        if max_id > last_id:
            self.settings.set_setting(CURSOR_KEY, str(max_id))
        return {"fetched": len(rows), "new": new, "pending_link": pending, "cursor": max_id}

    def on_invoice_processed(self, patient_link_id, invoice):
        """Phase 2: invoice-triggered outreach via the physician approval queue.
        Enrolled patients only (the approval queue FKs to patient_links); walk-ins
        (patient_link_id is None) are skipped by design. Each event is enqueued once
        (idempotent period_key) and respects opt-out / no-phone / cooldown."""
        if not patient_link_id:
            return
        from src.services.engagement_service import EngagementService
        eng = EngagementService()
        inv_id = invoice.get("invoice_id")
        work_date = invoice.get("work_date") or ""
        # 1) Thank-you — once per patient per work_date (not per invoice).
        eng.enqueue_event_for_patient(patient_link_id, "thank_you", f"thank_you:{work_date}")
        # 2) Procedure follow-up invites — derived from the invoice's items (lazy read).
        seen = set()
        for it in accounting_bridge.fetch_invoice_items(inv_id):
            ev = _procedure_event_key(it.get("description") or "")
            if ev and ev not in seen:
                seen.add(ev)
                eng.enqueue_event_for_patient(
                    patient_link_id, ev, f"{ev}:{inv_id}", detail=it.get("description"))
