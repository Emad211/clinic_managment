"""Per-item payment persistence for the accounting write-side.

Amounts in this projection are the patient's liability, not raw billed revenue:

* visit      -> ``visits.price`` (the migrated visit patient share)
* injection  -> ``injections.patient_amount`` with recorded-price fallback
* procedure  -> ``procedures.price`` (still blocked by the service until ported)
* consumable -> ``consumables_ledger.total_cost``

Every close transition still requires an explicit paid row for every item,
including insurance-covered zero-liability items, matching the Flask oracle.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from psycopg import Connection


_ITEM_TYPES = frozenset({"visit", "injection", "procedure", "consumable"})

_ITEM_STREAM = """
    SELECT v.tenant_id, v.invoice_id, 'visit'::text AS item_type,
           v.id AS item_id, 'ویزیت'::text AS description,
           v.price::numeric AS amount
    FROM accounting.visits v

    UNION ALL

    SELECT i.tenant_id, i.invoice_id, 'injection'::text,
           i.id, i.injection_type,
           COALESCE(i.patient_amount, i.total_price)::numeric
    FROM accounting.injections i

    UNION ALL

    SELECT p.tenant_id, p.invoice_id, 'procedure'::text,
           p.id, p.procedure_type, p.price::numeric
    FROM accounting.procedures p

    UNION ALL

    SELECT c.tenant_id, c.invoice_id, 'consumable'::text,
           c.id, c.item_name, c.total_cost::numeric
    FROM accounting.consumables_ledger c
"""


class PaymentRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    def get_item(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        item_type: str,
        item_id: int,
    ) -> Optional[dict[str, Any]]:
        if item_type not in _ITEM_TYPES:
            return None
        return self.conn.execute(
            f"""
            WITH item AS ({_ITEM_STREAM})
            SELECT item_id AS id, item_type, description, amount
            FROM item
            WHERE tenant_id=%s AND invoice_id=%s
              AND item_type=%s AND item_id=%s
            FOR UPDATE
            """,
            (tenant_id, invoice_id, item_type, item_id),
        ).fetchone()

    def get_visit_item(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        visit_id: int,
    ) -> Optional[dict[str, Any]]:
        """Compatibility wrapper retained for first-slice callers/tests."""
        return self.get_item(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_type="visit",
            item_id=visit_id,
        )

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

    def settle_item_types(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        payment_type: str,
        item_types: Iterable[str],
    ) -> int:
        allowed = sorted(set(item_types) & _ITEM_TYPES)
        if not allowed:
            return 0
        rows = self.conn.execute(
            f"""
            WITH item AS ({_ITEM_STREAM})
            INSERT INTO accounting.invoice_item_payments AS p
                (tenant_id, invoice_id, item_type, item_id, payment_type, is_paid)
            SELECT tenant_id, invoice_id, item_type, item_id, %s, TRUE
            FROM item
            WHERE tenant_id=%s AND invoice_id=%s
              AND item_type=ANY(%s)
            ON CONFLICT (tenant_id, invoice_id, item_type, item_id)
            DO UPDATE SET
                payment_type=EXCLUDED.payment_type,
                is_paid=TRUE,
                updated_at=now()
            RETURNING id
            """,
            (payment_type, tenant_id, invoice_id, allowed),
        ).fetchall()
        return len(rows)

    def settle_all_visits(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        payment_type: str,
    ) -> int:
        return self.settle_item_types(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            payment_type=payment_type,
            item_types={"visit"},
        )

    def unpaid_items(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        item_types: Optional[Iterable[str]] = None,
    ) -> list[dict[str, Any]]:
        allowed = sorted(set(item_types or _ITEM_TYPES) & _ITEM_TYPES)
        if not allowed:
            return []
        return self.conn.execute(
            f"""
            WITH item AS ({_ITEM_STREAM})
            SELECT item.item_id, item.item_type, item.description, item.amount
            FROM item
            LEFT JOIN accounting.invoice_item_payments pay
              ON pay.tenant_id=item.tenant_id
             AND pay.invoice_id=item.invoice_id
             AND pay.item_type=item.item_type
             AND pay.item_id=item.item_id
            WHERE item.tenant_id=%s AND item.invoice_id=%s
              AND item.item_type=ANY(%s)
              AND COALESCE(pay.is_paid, FALSE)=FALSE
            ORDER BY item.item_type, item.item_id
            """,
            (tenant_id, invoice_id, allowed),
        ).fetchall()

    def unpaid_visit_items(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
    ) -> list[dict[str, Any]]:
        return self.unpaid_items(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item_types={"visit"},
        )

    def summary_for_invoice(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            f"""
            WITH item AS ({_ITEM_STREAM})
            SELECT inv.id AS invoice_id,
                   COALESCE(SUM(item.amount),0) AS total_amount,
                   COALESCE(SUM(CASE WHEN pay.is_paid THEN item.amount ELSE 0 END),0)
                       AS paid_amount,
                   COUNT(item.item_id)>0
                     AND BOOL_AND(COALESCE(pay.is_paid,FALSE)) AS all_items_paid,
                   CASE
                     WHEN COUNT(item.item_id)>0
                      AND BOOL_AND(COALESCE(pay.is_paid,FALSE))
                      AND COUNT(DISTINCT pay.payment_type)=1
                     THEN MIN(pay.payment_type)
                     ELSE NULL
                   END AS payment_type
            FROM accounting.invoices inv
            LEFT JOIN item
              ON item.tenant_id=inv.tenant_id AND item.invoice_id=inv.id
            LEFT JOIN accounting.invoice_item_payments pay
              ON pay.tenant_id=item.tenant_id
             AND pay.invoice_id=item.invoice_id
             AND pay.item_type=item.item_type
             AND pay.item_id=item.item_id
            WHERE inv.tenant_id=%s AND inv.id=%s
            GROUP BY inv.id
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
            f"""
            WITH item AS ({_ITEM_STREAM})
            SELECT inv.id AS invoice_id,
                   COALESCE(SUM(item.amount),0) AS total_amount,
                   COALESCE(SUM(CASE WHEN pay.is_paid THEN item.amount ELSE 0 END),0)
                       AS paid_amount,
                   COUNT(item.item_id)>0
                     AND BOOL_AND(COALESCE(pay.is_paid,FALSE)) AS all_items_paid,
                   CASE
                     WHEN COUNT(item.item_id)>0
                      AND BOOL_AND(COALESCE(pay.is_paid,FALSE))
                      AND COUNT(DISTINCT pay.payment_type)=1
                     THEN MIN(pay.payment_type)
                     ELSE NULL
                   END AS payment_type
            FROM accounting.invoices inv
            LEFT JOIN item
              ON item.tenant_id=inv.tenant_id AND item.invoice_id=inv.id
            LEFT JOIN accounting.invoice_item_payments pay
              ON pay.tenant_id=item.tenant_id
             AND pay.invoice_id=item.invoice_id
             AND pay.item_type=item.item_type
             AND pay.item_id=item.item_id
            WHERE inv.tenant_id=%s AND inv.id=ANY(%s)
            GROUP BY inv.id
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
