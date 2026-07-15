from __future__ import annotations

from typing import Any

from accounting_ops.import_context import ImportContext


def target_money(ctx: ImportContext) -> dict[str, int]:
    def ids(table: str) -> list[int]:
        return [
            target_id
            for (source_table, _), target_id in ctx.id_map.items()
            if source_table == table
        ]

    invoice_ids = ids("invoices")
    visit_ids = ids("visits")
    injection_ids = ids("injections")
    procedure_ids = ids("procedures")
    consumable_ids = ids("consumables_ledger")

    def invoice_sum(status: str | None = None) -> int:
        if not invoice_ids:
            return 0
        sql = (
            "SELECT COALESCE(SUM(total_amount),0) AS value "
            "FROM accounting.invoices WHERE tenant_id=%s AND id=ANY(%s::bigint[])"
        )
        params: list[Any] = [ctx.tenant_id, invoice_ids]
        if status:
            sql += " AND status=%s"
            params.append(status)
        return int(ctx.conn.execute(sql, tuple(params)).fetchone()["value"] or 0)

    def item_sum(table: str, column: str, item_ids: list[int], where: str = "") -> int:
        if not item_ids:
            return 0
        row = ctx.conn.execute(
            f"SELECT COALESCE(SUM({column}),0) AS value FROM {table} "
            "WHERE tenant_id=%s AND id=ANY(%s::bigint[]) " + where,
            (ctx.tenant_id, item_ids),
        ).fetchone()
        return int(row["value"] or 0)

    if invoice_ids:
        payment_row = ctx.conn.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE is_paid) AS paid,
                   COUNT(*) FILTER (WHERE NOT is_paid) AS unpaid
            FROM accounting.invoice_item_payments
            WHERE tenant_id=%s AND invoice_id=ANY(%s::bigint[])
            """,
            (ctx.tenant_id, invoice_ids),
        ).fetchone()
    else:
        payment_row = {"total": 0, "paid": 0, "unpaid": 0}

    visit_raw = item_sum("accounting.visits", "price", visit_ids)
    nursing_raw = item_sum("accounting.injections", "total_price", injection_ids)
    procedure_raw = item_sum("accounting.procedures", "price", procedure_ids)
    return {
        "invoice_total_all": invoice_sum(),
        "invoice_total_open": invoice_sum("open"),
        "invoice_total_closed": invoice_sum("closed"),
        "visit_raw": visit_raw,
        "nursing_raw": nursing_raw,
        "procedure_raw": procedure_raw,
        "consumables_all": item_sum(
            "accounting.consumables_ledger", "total_cost", consumable_ids
        ),
        "consumables_center": item_sum(
            "accounting.consumables_ledger",
            "total_cost",
            consumable_ids,
            "AND NOT patient_provided AND NOT is_exception",
        ),
        "payments_total": int(payment_row["total"] or 0),
        "payments_paid": int(payment_row["paid"] or 0),
        "payments_unpaid": int(payment_row["unpaid"] or 0),
        "operating_revenue_raw": visit_raw + nursing_raw + procedure_raw,
    }
