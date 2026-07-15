from __future__ import annotations

from datetime import date
from typing import Any

from django.db import connections, transaction

from accounting_port.payroll import AccountingPayrollRepository


def _dict_rows(cursor) -> list[dict[str, Any]]:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _shift(alias: str, value: str | None) -> tuple[str, list[Any]]:
    return (f" AND {alias}.shift=%s", [value]) if value else ("", [])


class AccountingDualRunRepository:
    @classmethod
    def load(
        cls,
        *,
        tenant_id: int,
        source_id: str,
        date_from: date,
        date_to: date,
        shift: str | None,
    ) -> dict[str, Any]:
        with transaction.atomic(using="accounting_read"):
            with connections["accounting_read"].cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, true)",
                    [str(tenant_id)],
                )
                clause, shift_params = _shift("i", shift)
                cursor.execute(
                    f"""
                    SELECT i.work_date,COALESCE(i.shift,'unknown') AS shift,
                           COALESCE(i.insurance_type,'unknown') AS insurance_type,
                           i.status,COALESCE(i.total_amount,0) AS amount
                    FROM accounting.invoices i
                    WHERE i.tenant_id=%s AND i.work_date BETWEEN %s AND %s {clause}
                    ORDER BY i.work_date,i.id
                    """,
                    [tenant_id, date_from, date_to, *shift_params],
                )
                invoices = _dict_rows(cursor)

                events: list[dict[str, Any]] = []
                specs = (
                    ("visit", "visits", "price", "FALSE"),
                    ("nursing", "injections", "total_price", "FALSE"),
                    ("procedure", "procedures", "price", "FALSE"),
                    (
                        "consumable",
                        "consumables_ledger",
                        "total_cost",
                        "(NOT e.patient_provided AND NOT e.is_exception)",
                    ),
                )
                for kind, table, amount_column, center_expression in specs:
                    clause, shift_params = _shift("e", shift)
                    cursor.execute(
                        f"""
                        SELECT %s AS kind,e.work_date,
                               COALESCE(e.shift,'unknown') AS shift,
                               COALESCE(i.insurance_type,'unknown') AS insurance_type,
                               i.status AS invoice_status,
                               COALESCE(e.{amount_column},0) AS amount,
                               {center_expression} AS center_supplied
                        FROM accounting.{table} e
                        JOIN accounting.invoices i
                          ON i.tenant_id=e.tenant_id AND i.id=e.invoice_id
                        WHERE e.tenant_id=%s AND e.work_date BETWEEN %s AND %s {clause}
                        ORDER BY e.work_date,e.id
                        """,
                        [kind, tenant_id, date_from, date_to, *shift_params],
                    )
                    events.extend(_dict_rows(cursor))

                clause, shift_params = _shift("i", shift)
                cursor.execute(
                    f"""
                    SELECT i.work_date,COALESCE(i.shift,'unknown') AS shift,
                           COALESCE(i.insurance_type,'unknown') AS insurance_type,
                           p.is_paid
                    FROM accounting.invoice_item_payments p
                    JOIN accounting.invoices i
                      ON i.tenant_id=p.tenant_id AND i.id=p.invoice_id
                    WHERE p.tenant_id=%s AND i.work_date BETWEEN %s AND %s {clause}
                    ORDER BY i.work_date,p.invoice_id,p.item_type,p.item_id
                    """,
                    [tenant_id, date_from, date_to, *shift_params],
                )
                payments = _dict_rows(cursor)

                cursor.execute(
                    """
                    SELECT source_key,target_key
                    FROM accounting.accounting_import_ledger
                    WHERE tenant_id=%s AND source_id=%s
                      AND source_table='medical_staff'
                      AND target_table='accounting.medical_staff'
                    ORDER BY source_key
                    """,
                    [tenant_id, source_id],
                )
                staff_map: dict[int, int] = {}
                for source_key, target_key in cursor.fetchall():
                    try:
                        source_staff = int(str(source_key))
                        target_staff = int(str(target_key))
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Medical staff ledger keys must be integer IDs") from exc
                    if source_staff in staff_map:
                        raise ValueError("Duplicate medical staff source mapping in ledger")
                    staff_map[source_staff] = target_staff

                payroll = AccountingPayrollRepository(
                    cursor, tenant_id=tenant_id
                ).calculate(
                    date_from=date_from,
                    date_to=date_to,
                    staff_id=None,
                    staff_type=None,
                    shift=shift,
                )
                return {
                    "invoices": invoices,
                    "events": events,
                    "payments": payments,
                    "staff_map": staff_map,
                    "payroll": payroll,
                }
