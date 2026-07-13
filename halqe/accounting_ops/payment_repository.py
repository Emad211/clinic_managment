"""Item-payment persistence for the accounting write-side.

The production Flask app tracks payment per invoice item.  This first migration
slice supports visit rows only; other item families stay fail-closed until their
pricing and payment semantics are ported together.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from psycopg import Connection


class PaymentRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    def get_visit_item(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        visit_id: int,
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT v.id, v.price
            FROM accounting.visits v
            WHERE v.tenant_id=%s AND v.invoice_id=%s AND v.id=%s
            FOR UPDATE
            """,
            (tenant_id, invoice_id, visit_id),
        ).fetchone()

    def set_item_payment(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        item_type: str,
        item_id: int,
        payment_type: Optional[str],
        is_paid: bool,
    ) -> dict[str, Any]:
        return self.conn.execute(
            """
            INSERT INTO accounting.invoice_item_payments AS p
                (tenant_id, invoice_id, item_type, item_id, payment_type, is_paid)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, invoice_id, item_type, item_id)
            DO UPDATE SET
                payment_type=EXCLUDED.payment_type,
                is_paid=EXCLUDED.is_paid,
                updated_at=now()
            RETURNING invoice_id, item_type, item_id, payment_type,
                      is_paid, updated_at
            """,
            (
                tenant_id,
                invoice_id,
                item_type,
                item_id,
                payment_type,
                is_paid,
            ),
        ).fetchone()

    def settle_all_visits(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        payment_type: str,
    ) -> int:
        rows = self.conn.execute(
            """
            INSERT INTO accounting.invoice_item_payments AS p
                (tenant_id, invoice_id, item_type, item_id, payment_type, is_paid)
            SELECT v.tenant_id, v.invoice_id, 'visit', v.id, %s, TRUE
            FROM accounting.visits v
            WHERE v.tenant_id=%s AND v.invoice_id=%s
            ON CONFLICT (tenant_id, invoice_id, item_type, item_id)
            DO UPDATE SET
                payment_type=EXCLUDED.payment_type,
                is_paid=TRUE,
                updated_at=now()
            RETURNING id
            """,
            (payment_type, tenant_id, invoice_id),
        ).fetchall()
        return len(rows)

    def unpaid_visit_items(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
    ) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT v.id AS item_id, 'visit' AS item_type,
                   'ویزیت' AS description, v.price AS amount
            FROM accounting.visits v
            LEFT JOIN accounting.invoice_item_payments p
              ON p.tenant_id=v.tenant_id
             AND p.invoice_id=v.invoice_id
             AND p.item_type='visit'
             AND p.item_id=v.id
            WHERE v.tenant_id=%s AND v.invoice_id=%s
              AND COALESCE(p.is_paid, FALSE)=FALSE
            ORDER BY v.id
            """,
            (tenant_id, invoice_id),
        ).fetchall()

    def summary_for_invoice(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT i.id AS invoice_id,
                   COALESCE(SUM(v.price),0) AS total_amount,
                   COALESCE(SUM(CASE WHEN p.is_paid THEN v.price ELSE 0 END),0)
                       AS paid_amount,
                   COUNT(v.id)>0 AND BOOL_AND(COALESCE(p.is_paid,FALSE))
                       AS all_items_paid,
                   CASE
                     WHEN COUNT(v.id)>0
                      AND BOOL_AND(COALESCE(p.is_paid,FALSE))
                      AND COUNT(DISTINCT p.payment_type)=1
                     THEN MIN(p.payment_type)
                     ELSE NULL
                   END AS payment_type
            FROM accounting.invoices i
            LEFT JOIN accounting.visits v
              ON v.tenant_id=i.tenant_id AND v.invoice_id=i.id
            LEFT JOIN accounting.invoice_item_payments p
              ON p.tenant_id=v.tenant_id
             AND p.invoice_id=v.invoice_id
             AND p.item_type='visit'
             AND p.item_id=v.id
            WHERE i.tenant_id=%s AND i.id=%s
            GROUP BY i.id
            """,
            (tenant_id, invoice_id),
        ).fetchone()
        if not row:
            return {
                "total_amount": 0,
                "paid_amount": 0,
                "remaining_amount": 0,
                "all_items_paid": False,
                "payment_type": None,
            }
        total = int(row["total_amount"] or 0)
        paid = int(row["paid_amount"] or 0)
        return {
            "total_amount": total,
            "paid_amount": paid,
            "remaining_amount": max(0, total - paid),
            "all_items_paid": bool(row["all_items_paid"]),
            "payment_type": row.get("payment_type"),
        }

    def summaries_for_invoices(
        self,
        *,
        tenant_id: int,
        invoice_ids: Iterable[int],
    ) -> dict[int, dict[str, Any]]:
        ids = [int(value) for value in invoice_ids]
        if not ids:
            return {}
        rows = self.conn.execute(
            """
            SELECT i.id AS invoice_id,
                   COALESCE(SUM(v.price),0) AS total_amount,
                   COALESCE(SUM(CASE WHEN p.is_paid THEN v.price ELSE 0 END),0)
                       AS paid_amount,
                   COUNT(v.id)>0 AND BOOL_AND(COALESCE(p.is_paid,FALSE))
                       AS all_items_paid,
                   CASE
                     WHEN COUNT(v.id)>0
                      AND BOOL_AND(COALESCE(p.is_paid,FALSE))
                      AND COUNT(DISTINCT p.payment_type)=1
                     THEN MIN(p.payment_type)
                     ELSE NULL
                   END AS payment_type
            FROM accounting.invoices i
            LEFT JOIN accounting.visits v
              ON v.tenant_id=i.tenant_id AND v.invoice_id=i.id
            LEFT JOIN accounting.invoice_item_payments p
              ON p.tenant_id=v.tenant_id
             AND p.invoice_id=v.invoice_id
             AND p.item_type='visit'
             AND p.item_id=v.id
            WHERE i.tenant_id=%s AND i.id=ANY(%s)
            GROUP BY i.id
            """,
            (tenant_id, ids),
        ).fetchall()
        out: dict[int, dict[str, Any]] = {}
        for row in rows:
            total = int(row["total_amount"] or 0)
            paid = int(row["paid_amount"] or 0)
            out[int(row["invoice_id"])] = {
                "total_amount": total,
                "paid_amount": paid,
                "remaining_amount": max(0, total - paid),
                "all_items_paid": bool(row["all_items_paid"]),
                "payment_type": row.get("payment_type"),
            }
        return out
