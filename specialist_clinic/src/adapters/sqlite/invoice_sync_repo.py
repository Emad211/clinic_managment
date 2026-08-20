"""Repository for the accounting invoice-sync ledger (`processed_invoices`).

ADR-0003 (D3+): the specialist app polls the accounting DB **read-only** for recently
closed invoices and records them here idempotently (the seam that lets the care-loop
react to a closed visit/procedure). ALL SQL for this aggregate lives here. The
accounting DB is NEVER written — it is read via `accounting_bridge` with `mode=ro`.

Idempotency key: `accounting_invoice_id` (UNIQUE) + `INSERT OR IGNORE`. Because a
closed invoice is an immutable, one-way state in the accounting app (no reopen/delete
path exists), recording it once is sufficient.
"""
from src.adapters.sqlite.core import get_db


class InvoiceSyncRepository:

    def record(self, *, accounting_invoice_id: int, patient_link_id, national_id,
               full_name, work_date, closed_at, total_amount, status: str) -> bool:
        """Idempotent insert of one processed invoice. Returns True if a NEW row was
        inserted, False if this accounting_invoice_id was already recorded."""
        db = get_db()
        cur = db.execute(
            """INSERT OR IGNORE INTO processed_invoices
                 (accounting_invoice_id, patient_link_id, national_id, full_name,
                  work_date, closed_at, total_amount, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (accounting_invoice_id, patient_link_id, national_id, full_name,
             work_date, closed_at, total_amount, status),
        )
        db.commit()
        return cur.rowcount > 0

    def outreach_done(self, accounting_invoice_id: int) -> bool:
        """True if invoice-triggered outreach (thank-you / invite) already completed for
        this invoice. Lets outreach be retried independently of the ledger insert."""
        row = get_db().execute(
            "SELECT outreach_done FROM processed_invoices WHERE accounting_invoice_id=?",
            (accounting_invoice_id,)).fetchone()
        return bool(row and row["outreach_done"])

    def mark_outreach_done(self, accounting_invoice_id: int) -> None:
        """Mark outreach complete so it is not retried on the next sync pass."""
        db = get_db()
        db.execute(
            "UPDATE processed_invoices SET outreach_done=1 WHERE accounting_invoice_id=?",
            (accounting_invoice_id,))
        db.commit()

    def reconcile_pending_links(self) -> int:
        """Attach old ledger rows after the matching patient is enrolled locally."""
        db = get_db()
        cursor = db.execute(
            """UPDATE processed_invoices
               SET patient_link_id=(
                       SELECT patient.id FROM patient_links patient
                       WHERE patient.national_id=processed_invoices.national_id
                         AND patient.is_active=1
                       ORDER BY patient.id LIMIT 1
                   ),
                   status='applied'
               WHERE status='pending_link'
                 AND patient_link_id IS NULL
                 AND national_id IS NOT NULL
                 AND EXISTS (
                       SELECT 1 FROM patient_links patient
                       WHERE patient.national_id=processed_invoices.national_id
                         AND patient.is_active=1
                   )"""
        )
        db.commit()
        return int(cursor.rowcount or 0)

    def pending_outreach(self, limit: int = 500) -> list[dict]:
        """Durable retry queue, independent from the accounting polling cursor."""
        rows = get_db().execute(
            """SELECT accounting_invoice_id AS invoice_id,
                      patient_link_id, national_id, full_name, work_date,
                      closed_at, total_amount, status
               FROM processed_invoices
               WHERE patient_link_id IS NOT NULL AND outreach_done=0
               ORDER BY accounting_invoice_id ASC
               LIMIT ?""",
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    def max_processed_id(self) -> int:
        db = get_db()
        row = db.execute(
            "SELECT COALESCE(MAX(accounting_invoice_id), 0) AS m FROM processed_invoices"
        ).fetchone()
        return int(row["m"] or 0)

    def count(self) -> int:
        db = get_db()
        return int(db.execute("SELECT COUNT(*) c FROM processed_invoices").fetchone()["c"])

    def recent(self, limit: int = 50) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM processed_invoices ORDER BY accounting_invoice_id DESC LIMIT ?",
            (limit,)).fetchall()]
