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
