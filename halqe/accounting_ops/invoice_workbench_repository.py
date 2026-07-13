"""Persistence adapter for full accounting invoice projections and corrections."""
from __future__ import annotations

from typing import Any, Optional

from psycopg import Connection, sql


_ITEM_TABLES = {
    "visit": "visits",
    "injection": "injections",
    "procedure": "procedures",
    "consumable": "consumables_ledger",
}


class InvoiceWorkbenchRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    def invoice_header(
        self, *, tenant_id: int, invoice_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT i.id, i.tenant_id, i.patient_id, i.status, i.pricing_version,
                   i.insurance_type, i.supplementary_insurance,
                   i.total_amount, i.work_date, i.shift,
                   i.opened_at, i.closed_at, i.opened_by, i.opened_by_name,
                   i.closed_by, i.closed_by_name,
                   p.uuid AS patient_uuid, p.full_name AS patient_full_name,
                   p.national_id, p.phone_number
            FROM accounting.invoices i
            JOIN accounting.patients p
              ON p.tenant_id=i.tenant_id AND p.id=i.patient_id
            WHERE i.tenant_id=%s AND i.id=%s
            """,
            (tenant_id, invoice_id),
        ).fetchone()

    def invoice_items(
        self, *, tenant_id: int, invoice_id: int
    ) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            WITH item AS (
                SELECT v.tenant_id, v.invoice_id, 'visit'::text AS item_type,
                       v.id AS item_id, 'ویزیت'::text AS description,
                       1::numeric AS quantity,
                       v.price::numeric AS recorded_amount,
                       v.price::numeric AS patient_amount,
                       0::numeric AS insurance_amount,
                       FALSE AS covered_by_insurance,
                       'doctor'::text AS performer_type,
                       v.doctor_id AS performer_id,
                       d.full_name AS performer_name,
                       v.visit_date AS occurred_at,
                       v.notes
                FROM accounting.visits v
                LEFT JOIN accounting.medical_staff d
                  ON d.tenant_id=v.tenant_id AND d.id=v.doctor_id

                UNION ALL

                SELECT i.tenant_id, i.invoice_id, 'injection'::text,
                       i.id, i.injection_type, i.count::numeric,
                       i.total_price::numeric,
                       COALESCE(i.patient_amount, i.total_price)::numeric,
                       COALESCE(i.insurance_amount, 0)::numeric,
                       i.covered_by_insurance,
                       CASE WHEN i.nurse_id IS NOT NULL THEN 'nurse' ELSE 'doctor' END,
                       COALESCE(i.nurse_id, i.doctor_id),
                       COALESCE(n.full_name, d.full_name),
                       i.injection_date,
                       i.notes
                FROM accounting.injections i
                LEFT JOIN accounting.medical_staff d
                  ON d.tenant_id=i.tenant_id AND d.id=i.doctor_id
                LEFT JOIN accounting.medical_staff n
                  ON n.tenant_id=i.tenant_id AND n.id=i.nurse_id

                UNION ALL

                SELECT p.tenant_id, p.invoice_id, 'procedure'::text,
                       p.id, p.procedure_type, 1::numeric,
                       p.price::numeric,
                       COALESCE(p.patient_amount, p.price)::numeric,
                       COALESCE(p.insurance_amount, 0)::numeric,
                       p.covered_by_insurance,
                       p.performer_type,
                       p.performer_id,
                       s.full_name,
                       p.procedure_date,
                       p.notes
                FROM accounting.procedures p
                LEFT JOIN accounting.medical_staff s
                  ON s.tenant_id=p.tenant_id AND s.id=p.performer_id

                UNION ALL

                SELECT c.tenant_id, c.invoice_id, 'consumable'::text,
                       c.id, c.item_name, c.quantity,
                       c.total_cost::numeric,
                       c.total_cost::numeric,
                       0::numeric,
                       FALSE,
                       CASE WHEN c.nurse_id IS NOT NULL THEN 'nurse' ELSE 'doctor' END,
                       COALESCE(c.nurse_id, c.doctor_id),
                       COALESCE(n.full_name, d.full_name),
                       c.usage_date,
                       c.notes
                FROM accounting.consumables_ledger c
                LEFT JOIN accounting.medical_staff d
                  ON d.tenant_id=c.tenant_id AND d.id=c.doctor_id
                LEFT JOIN accounting.medical_staff n
                  ON n.tenant_id=c.tenant_id AND n.id=c.nurse_id
            )
            SELECT item.item_type, item.item_id, item.description,
                   item.quantity, item.recorded_amount, item.patient_amount,
                   item.insurance_amount, item.covered_by_insurance,
                   item.performer_type, item.performer_id, item.performer_name,
                   item.occurred_at, item.notes,
                   pay.payment_type, COALESCE(pay.is_paid,FALSE) AS is_paid,
                   pay.updated_at AS payment_updated_at
            FROM item
            LEFT JOIN accounting.invoice_item_payments pay
              ON pay.tenant_id=item.tenant_id
             AND pay.invoice_id=item.invoice_id
             AND pay.item_type=item.item_type
             AND pay.item_id=item.item_id
            WHERE item.tenant_id=%s AND item.invoice_id=%s
            ORDER BY item.occurred_at, item.item_type, item.item_id
            """,
            (tenant_id, invoice_id),
        ).fetchall()

    def item_for_update(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        item_type: str,
        item_id: int,
    ) -> Optional[dict[str, Any]]:
        if item_type not in _ITEM_TABLES:
            return None
        table = sql.Identifier("accounting", _ITEM_TABLES[item_type])
        amount_column = {
            "visit": "price",
            "injection": "patient_amount",
            "procedure": "patient_amount",
            "consumable": "total_cost",
        }[item_type]
        fallback_column = {
            "visit": "price",
            "injection": "total_price",
            "procedure": "price",
            "consumable": "total_cost",
        }[item_type]
        query = sql.SQL(
            """
            SELECT id, invoice_id,
                   COALESCE({amount_column}, {fallback_column}, 0) AS patient_amount
            FROM {table}
            WHERE tenant_id=%s AND invoice_id=%s AND id=%s
            FOR UPDATE
            """
        ).format(
            amount_column=sql.Identifier(amount_column),
            fallback_column=sql.Identifier(fallback_column),
            table=table,
        )
        return self.conn.execute(
            query,
            (tenant_id, invoice_id, item_id),
        ).fetchone()

    def visit_has_children(
        self, *, tenant_id: int, visit_id: int
    ) -> bool:
        return bool(
            self.conn.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM accounting.visit_items
                    WHERE tenant_id=%s AND visit_id=%s
                ) AS exists
                """,
                (tenant_id, visit_id),
            ).fetchone()["exists"]
        )

    def delete_payment(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        item_type: str,
        item_id: int,
    ) -> None:
        self.conn.execute(
            """
            DELETE FROM accounting.invoice_item_payments
            WHERE tenant_id=%s AND invoice_id=%s
              AND item_type=%s AND item_id=%s
            """,
            (tenant_id, invoice_id, item_type, item_id),
        )

    def delete_item(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        item_type: str,
        item_id: int,
    ) -> bool:
        if item_type not in _ITEM_TABLES:
            return False
        table = sql.Identifier("accounting", _ITEM_TABLES[item_type])
        query = sql.SQL(
            "DELETE FROM {table} WHERE tenant_id=%s AND invoice_id=%s AND id=%s"
        ).format(table=table)
        result = self.conn.execute(query, (tenant_id, invoice_id, item_id))
        return result.rowcount == 1
