from __future__ import annotations

from typing import Any, Mapping, Sequence

from accounting_ops.import_context import _TARGET_COLUMNS


def read_target(
    cursor,
    *,
    tenant_id: int,
    table: str,
    key: str,
) -> dict[str, Any] | None:
    columns = _TARGET_COLUMNS.get(table)
    if columns is None:
        return None
    rendered = ", ".join(columns)
    if table == "accounting.invoice_item_payments":
        try:
            invoice_id, item_type, item_id = key.split(":", 2)
        except ValueError:
            return None
        cursor.execute(
            f"SELECT {rendered} FROM {table} "
            "WHERE tenant_id=%s AND invoice_id=%s AND item_type=%s AND item_id=%s",
            [tenant_id, int(invoice_id), item_type, int(item_id)],
        )
    else:
        try:
            target_id = int(key)
        except ValueError:
            return None
        cursor.execute(
            f"SELECT {rendered} FROM {table} WHERE tenant_id=%s AND id=%s",
            [tenant_id, target_id],
        )
    row = cursor.fetchone()
    return dict(zip(columns, row)) if row else None


def _ids(entries: Sequence[Mapping[str, Any]], source_table: str) -> list[int]:
    return [
        int(entry["target_key"])
        for entry in entries
        if entry["source_table"] == source_table
    ]


def target_money(cursor, *, tenant_id: int, entries) -> dict[str, int]:
    invoice_ids = _ids(entries, "invoices")
    visit_ids = _ids(entries, "visits")
    injection_ids = _ids(entries, "injections")
    procedure_ids = _ids(entries, "procedures")
    consumable_ids = _ids(entries, "consumables_ledger")

    def invoice_sum(status: str | None = None) -> int:
        if not invoice_ids:
            return 0
        sql = (
            "SELECT COALESCE(SUM(total_amount),0) FROM accounting.invoices "
            "WHERE tenant_id=%s AND id=ANY(%s::bigint[])"
        )
        params: list[Any] = [tenant_id, invoice_ids]
        if status:
            sql += " AND status=%s"
            params.append(status)
        cursor.execute(sql, params)
        return int(cursor.fetchone()[0] or 0)

    def item_sum(table: str, column: str, ids: list[int], extra: str = "") -> int:
        if not ids:
            return 0
        cursor.execute(
            f"SELECT COALESCE(SUM({column}),0) FROM {table} "
            "WHERE tenant_id=%s AND id=ANY(%s::bigint[]) " + extra,
            [tenant_id, ids],
        )
        return int(cursor.fetchone()[0] or 0)

    if invoice_ids:
        cursor.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE is_paid),
                   COUNT(*) FILTER (WHERE NOT is_paid)
            FROM accounting.invoice_item_payments
            WHERE tenant_id=%s AND invoice_id=ANY(%s::bigint[])
            """,
            [tenant_id, invoice_ids],
        )
        payment_total, paid, unpaid = cursor.fetchone()
    else:
        payment_total = paid = unpaid = 0

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
        "payments_total": int(payment_total or 0),
        "payments_paid": int(paid or 0),
        "payments_unpaid": int(unpaid or 0),
        "operating_revenue_raw": visit_raw + nursing_raw + procedure_raw,
    }


def invoice_children(cursor, *, tenant_id: int, invoice_ids: list[int]) -> dict[str, set[str]]:
    result = {
        "visits": set(),
        "injections": set(),
        "procedures": set(),
        "consumables_ledger": set(),
        "invoice_item_payments": set(),
    }
    if not invoice_ids:
        return result
    for source_table, target_table in (
        ("visits", "accounting.visits"),
        ("injections", "accounting.injections"),
        ("procedures", "accounting.procedures"),
        ("consumables_ledger", "accounting.consumables_ledger"),
    ):
        cursor.execute(
            f"SELECT id FROM {target_table} "
            "WHERE tenant_id=%s AND invoice_id=ANY(%s::bigint[])",
            [tenant_id, invoice_ids],
        )
        result[source_table] = {str(row[0]) for row in cursor.fetchall()}
    cursor.execute(
        """
        SELECT invoice_id,item_type,item_id
        FROM accounting.invoice_item_payments
        WHERE tenant_id=%s AND invoice_id=ANY(%s::bigint[])
        """,
        [tenant_id, invoice_ids],
    )
    result["invoice_item_payments"] = {
        f"{row[0]}:{row[1]}:{row[2]}" for row in cursor.fetchall()
    }
    return result
