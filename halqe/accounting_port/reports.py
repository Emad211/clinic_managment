"""SELECT-only financial reporting port for the unified accounting dashboard.

The legacy Flask application remains the behavioural oracle. In particular,
``operating_revenue`` is the sum of closed visit, nursing/injection and procedure
raw prices; consumables are intentionally reported separately and never folded
into revenue.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from django.db import connections, transaction


def _dict_rows(cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _dict_row(cursor) -> dict[str, Any]:
    columns = [column[0] for column in cursor.description]
    row = cursor.fetchone()
    return dict(zip(columns, row)) if row else {}


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _plain_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: _plain(value) for key, value in row.items()} for row in rows]


class AccountingReportsRepository:
    """Read model using the physically SELECT-only ``accounting_read`` alias."""

    def __init__(self, cursor, *, tenant_id: int):
        self.cursor = cursor
        self.tenant_id = tenant_id

    @classmethod
    def load(
        cls,
        *,
        tenant_id: int,
        date_from: date,
        date_to: date,
        invoice_filters: Optional[dict[str, Any]] = None,
        service_filters: Optional[dict[str, Any]] = None,
        invoice_limit: int = 200,
        service_limit: int = 300,
    ) -> dict[str, Any]:
        with transaction.atomic(using="accounting_read"):
            with connections["accounting_read"].cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, true)",
                    [str(tenant_id)],
                )
                repo = cls(cursor, tenant_id=tenant_id)
                return {
                    "overview": repo.overview(date_from=date_from, date_to=date_to),
                    "invoices": repo.invoices(
                        date_from=date_from,
                        date_to=date_to,
                        filters=invoice_filters or {},
                        limit=invoice_limit,
                    ),
                    "services": repo.services(
                        date_from=date_from,
                        date_to=date_to,
                        filters=service_filters or {},
                        limit=service_limit,
                    ),
                }

    @classmethod
    def overview_only(cls, *, tenant_id: int, date_from: date, date_to: date):
        return cls.load(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            invoice_limit=12,
            service_limit=1,
        )["overview"]

    @classmethod
    def invoices_only(
        cls,
        *,
        tenant_id: int,
        date_from: date,
        date_to: date,
        filters: dict[str, Any],
        limit: int,
    ):
        with transaction.atomic(using="accounting_read"):
            with connections["accounting_read"].cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, true)",
                    [str(tenant_id)],
                )
                return cls(cursor, tenant_id=tenant_id).invoices(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                    limit=limit,
                )

    @classmethod
    def services_only(
        cls,
        *,
        tenant_id: int,
        date_from: date,
        date_to: date,
        filters: dict[str, Any],
        limit: int,
    ):
        with transaction.atomic(using="accounting_read"):
            with connections["accounting_read"].cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, true)",
                    [str(tenant_id)],
                )
                return cls(cursor, tenant_id=tenant_id).services(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                    limit=limit,
                )

    def overview(self, *, date_from: date, date_to: date) -> dict[str, Any]:
        params = [self.tenant_id, date_from, date_to]
        self.cursor.execute(
            """
            SELECT
                COUNT(*)::bigint AS total,
                COUNT(*) FILTER (WHERE status='open')::bigint AS open,
                COUNT(*) FILTER (WHERE status='closed')::bigint AS closed,
                COUNT(DISTINCT patient_id)::bigint AS unique_patients,
                COALESCE(SUM(total_amount), 0)::numeric AS total_liability
            FROM accounting.invoices
            WHERE tenant_id=%s AND work_date BETWEEN %s AND %s
            """,
            params,
        )
        invoice_summary = _dict_row(self.cursor)

        self.cursor.execute(
            """
            WITH source AS (
                SELECT 'visit'::text AS kind, v.id, v.price::numeric AS amount
                FROM accounting.visits v
                JOIN accounting.invoices i
                  ON i.tenant_id=v.tenant_id AND i.id=v.invoice_id
                WHERE v.tenant_id=%s AND v.work_date BETWEEN %s AND %s
                  AND i.status='closed'
                UNION ALL
                SELECT 'nursing', n.id, n.total_price::numeric
                FROM accounting.injections n
                JOIN accounting.invoices i
                  ON i.tenant_id=n.tenant_id AND i.id=n.invoice_id
                WHERE n.tenant_id=%s AND n.work_date BETWEEN %s AND %s
                  AND i.status='closed'
                UNION ALL
                SELECT 'procedure', p.id, p.price::numeric
                FROM accounting.procedures p
                JOIN accounting.invoices i
                  ON i.tenant_id=p.tenant_id AND i.id=p.invoice_id
                WHERE p.tenant_id=%s AND p.work_date BETWEEN %s AND %s
                  AND i.status='closed'
            )
            SELECT kind, COUNT(*)::bigint AS count,
                   COALESCE(SUM(amount), 0)::numeric AS amount
            FROM source GROUP BY kind ORDER BY kind
            """,
            params * 3,
        )
        source_rows = {row["kind"]: row for row in _dict_rows(self.cursor)}
        revenue = {
            kind: {
                "count": int(source_rows.get(kind, {}).get("count") or 0),
                "amount": int(source_rows.get(kind, {}).get("amount") or 0),
            }
            for kind in ("visit", "nursing", "procedure")
        }
        revenue["operating_revenue"] = sum(
            revenue[kind]["amount"] for kind in ("visit", "nursing", "procedure")
        )

        self.cursor.execute(
            """
            SELECT COUNT(*)::bigint AS count,
                   COALESCE(SUM(c.total_cost), 0)::numeric AS amount
            FROM accounting.consumables_ledger c
            JOIN accounting.invoices i
              ON i.tenant_id=c.tenant_id AND i.id=c.invoice_id
            WHERE c.tenant_id=%s AND c.work_date BETWEEN %s AND %s
              AND i.status='closed'
              AND c.patient_provided=FALSE AND c.is_exception=FALSE
            """,
            params,
        )
        consumables = _dict_row(self.cursor)

        self.cursor.execute(
            """
            SELECT
                COUNT(*)::bigint AS items,
                COUNT(*) FILTER (WHERE p.is_paid)::bigint AS paid_items,
                COUNT(*) FILTER (WHERE NOT p.is_paid)::bigint AS unpaid_items
            FROM accounting.invoice_item_payments p
            JOIN accounting.invoices i
              ON i.tenant_id=p.tenant_id AND i.id=p.invoice_id
            WHERE p.tenant_id=%s AND i.work_date BETWEEN %s AND %s
            """,
            params,
        )
        payments = _dict_row(self.cursor)

        self.cursor.execute(
            """
            WITH days AS (
                SELECT generate_series(%s::date, %s::date, interval '1 day')::date AS day
            ), visit AS (
                SELECT v.work_date AS day, COUNT(*)::bigint AS count,
                       COALESCE(SUM(v.price),0)::numeric AS amount
                FROM accounting.visits v
                JOIN accounting.invoices i ON i.tenant_id=v.tenant_id AND i.id=v.invoice_id
                WHERE v.tenant_id=%s AND v.work_date BETWEEN %s AND %s AND i.status='closed'
                GROUP BY v.work_date
            ), nursing AS (
                SELECT n.work_date AS day, COUNT(*)::bigint AS count,
                       COALESCE(SUM(n.total_price),0)::numeric AS amount
                FROM accounting.injections n
                JOIN accounting.invoices i ON i.tenant_id=n.tenant_id AND i.id=n.invoice_id
                WHERE n.tenant_id=%s AND n.work_date BETWEEN %s AND %s AND i.status='closed'
                GROUP BY n.work_date
            ), procedures AS (
                SELECT p.work_date AS day, COUNT(*)::bigint AS count,
                       COALESCE(SUM(p.price),0)::numeric AS amount
                FROM accounting.procedures p
                JOIN accounting.invoices i ON i.tenant_id=p.tenant_id AND i.id=p.invoice_id
                WHERE p.tenant_id=%s AND p.work_date BETWEEN %s AND %s AND i.status='closed'
                GROUP BY p.work_date
            ), consumables AS (
                SELECT c.work_date AS day, COUNT(*)::bigint AS count,
                       COALESCE(SUM(c.total_cost),0)::numeric AS amount
                FROM accounting.consumables_ledger c
                JOIN accounting.invoices i ON i.tenant_id=c.tenant_id AND i.id=c.invoice_id
                WHERE c.tenant_id=%s AND c.work_date BETWEEN %s AND %s AND i.status='closed'
                  AND c.patient_provided=FALSE AND c.is_exception=FALSE
                GROUP BY c.work_date
            )
            SELECT d.day,
                   COALESCE(v.count,0)::bigint AS visits,
                   COALESCE(n.count,0)::bigint AS nursing,
                   COALESCE(p.count,0)::bigint AS procedures,
                   COALESCE(c.count,0)::bigint AS consumables,
                   (COALESCE(v.amount,0)+COALESCE(n.amount,0)+COALESCE(p.amount,0))::numeric
                       AS operating_revenue,
                   COALESCE(c.amount,0)::numeric AS consumables_cost
            FROM days d
            LEFT JOIN visit v ON v.day=d.day
            LEFT JOIN nursing n ON n.day=d.day
            LEFT JOIN procedures p ON p.day=d.day
            LEFT JOIN consumables c ON c.day=d.day
            ORDER BY d.day
            """,
            [
                date_from, date_to,
                self.tenant_id, date_from, date_to,
                self.tenant_id, date_from, date_to,
                self.tenant_id, date_from, date_to,
                self.tenant_id, date_from, date_to,
            ],
        )
        daily = _plain_rows(_dict_rows(self.cursor))

        self.cursor.execute(
            """
            SELECT i.id, i.work_date, i.opened_at, i.closed_at, i.status,
                   i.total_amount, i.insurance_type, i.supplementary_insurance,
                   COALESCE(i.opened_by_name, i.opened_by) AS opened_by_name,
                   COALESCE(i.closed_by_name, i.closed_by) AS closed_by_name,
                   p.full_name AS patient_name
            FROM accounting.invoices i
            JOIN accounting.patients p
              ON p.tenant_id=i.tenant_id AND p.id=i.patient_id
            WHERE i.tenant_id=%s AND i.work_date BETWEEN %s AND %s
            ORDER BY i.opened_at DESC, i.id DESC LIMIT 12
            """,
            params,
        )
        recent = _plain_rows(_dict_rows(self.cursor))

        self.cursor.execute(
            """
            SELECT DISTINCT insurance_type
            FROM accounting.invoices
            WHERE tenant_id=%s AND insurance_type IS NOT NULL
            ORDER BY insurance_type
            """,
            [self.tenant_id],
        )
        insurances = [row[0] for row in self.cursor.fetchall()]
        self.cursor.execute(
            """
            SELECT DISTINCT opened_by,
                   COALESCE(MAX(opened_by_name), opened_by) AS full_name
            FROM accounting.invoices
            WHERE tenant_id=%s AND opened_by IS NOT NULL
            GROUP BY opened_by ORDER BY full_name
            """,
            [self.tenant_id],
        )
        reception_users = [
            {"username": row[0], "full_name": row[1]} for row in self.cursor.fetchall()
        ]

        return {
            "date_from": date_from,
            "date_to": date_to,
            "invoices": {key: _plain(value) for key, value in invoice_summary.items()},
            "revenue": revenue,
            "consumables": {key: _plain(value) for key, value in consumables.items()},
            "payments": {key: _plain(value) for key, value in payments.items()},
            "daily": daily,
            "recent_invoices": recent,
            "filters": {
                "insurances": insurances,
                "reception_users": reception_users,
            },
        }

    def invoices(
        self,
        *,
        date_from: date,
        date_to: date,
        filters: dict[str, Any],
        limit: int,
    ) -> dict[str, Any]:
        clauses = ["i.tenant_id=%s", "i.work_date BETWEEN %s AND %s"]
        params: list[Any] = [self.tenant_id, date_from, date_to]
        if filters.get("status"):
            clauses.append("i.status=%s")
            params.append(filters["status"])
        if filters.get("insurance_type"):
            clauses.append("i.insurance_type=%s")
            params.append(filters["insurance_type"])
        if filters.get("reception_user"):
            clauses.append("i.opened_by=%s")
            params.append(filters["reception_user"])
        where = " AND ".join(clauses)

        self.cursor.execute(
            f"""
            SELECT i.id, i.work_date, i.opened_at, i.closed_at, i.status,
                   i.total_amount, i.insurance_type, i.supplementary_insurance,
                   i.opened_by, COALESCE(i.opened_by_name, i.opened_by) AS opened_by_name,
                   i.closed_by, COALESCE(i.closed_by_name, i.closed_by) AS closed_by_name,
                   p.full_name AS patient_name
            FROM accounting.invoices i
            JOIN accounting.patients p
              ON p.tenant_id=i.tenant_id AND p.id=i.patient_id
            WHERE {where}
            ORDER BY i.opened_at DESC, i.id DESC LIMIT %s
            """,
            [*params, limit],
        )
        rows = _plain_rows(_dict_rows(self.cursor))
        return {
            "date_from": date_from,
            "date_to": date_to,
            "summary": {
                "total": len(rows),
                "open": sum(row["status"] == "open" for row in rows),
                "closed": sum(row["status"] == "closed" for row in rows),
                "total_amount": sum(int(row["total_amount"] or 0) for row in rows),
            },
            "rows": rows,
        }

    def services(
        self,
        *,
        date_from: date,
        date_to: date,
        filters: dict[str, Any],
        limit: int,
    ) -> dict[str, Any]:
        clauses = ["work_date BETWEEN %s AND %s"]
        params: list[Any] = [date_from, date_to]
        if filters.get("service_type"):
            clauses.append("service_type=%s")
            params.append(filters["service_type"])
        if filters.get("shift"):
            clauses.append("shift=%s")
            params.append(filters["shift"])
        if filters.get("staff_id"):
            clauses.append("(doctor_id=%s OR nurse_id=%s)")
            params.extend([filters["staff_id"], filters["staff_id"]])
        where = " AND ".join(clauses)

        self.cursor.execute(
            f"""
            WITH item AS (
                SELECT 'visit'::text AS service_type, v.id, v.invoice_id,
                       v.work_date, v.visit_date AS occurred_at,
                       p.full_name AS patient_name, 'ویزیت'::text AS service_name,
                       1::numeric AS quantity, v.price::numeric AS amount,
                       v.price::numeric AS patient_amount, 0::numeric AS insurance_amount,
                       v.doctor_id, v.nurse_id, v.doctor_name AS staff_name,
                       'doctor'::text AS performer_type, v.shift, v.reception_user,
                       TRUE AS included_in_revenue,
                       FALSE AS patient_provided, FALSE AS is_exception
                FROM accounting.visits v
                JOIN accounting.invoices i ON i.tenant_id=v.tenant_id AND i.id=v.invoice_id
                JOIN accounting.patients p ON p.tenant_id=v.tenant_id AND p.id=v.patient_id
                WHERE v.tenant_id=%s AND i.status='closed'
                UNION ALL
                SELECT 'nursing', n.id, n.invoice_id, n.work_date, n.injection_date,
                       p.full_name, n.injection_type, n.count::numeric, n.total_price::numeric,
                       COALESCE(n.patient_amount,n.total_price)::numeric,
                       COALESCE(n.insurance_amount,0)::numeric,
                       n.doctor_id, n.nurse_id, COALESCE(ns.full_name,ds.full_name),
                       CASE WHEN n.nurse_id IS NOT NULL THEN 'nurse' ELSE 'doctor' END,
                       n.shift, n.reception_user, TRUE, FALSE, FALSE
                FROM accounting.injections n
                JOIN accounting.invoices i ON i.tenant_id=n.tenant_id AND i.id=n.invoice_id
                JOIN accounting.patients p ON p.tenant_id=n.tenant_id AND p.id=n.patient_id
                LEFT JOIN accounting.medical_staff ns ON ns.tenant_id=n.tenant_id AND ns.id=n.nurse_id
                LEFT JOIN accounting.medical_staff ds ON ds.tenant_id=n.tenant_id AND ds.id=n.doctor_id
                WHERE n.tenant_id=%s AND i.status='closed'
                UNION ALL
                SELECT 'procedure', pr.id, pr.invoice_id, pr.work_date, pr.procedure_date,
                       p.full_name, pr.procedure_type, 1::numeric, pr.price::numeric,
                       COALESCE(pr.patient_amount,pr.price)::numeric,
                       COALESCE(pr.insurance_amount,0)::numeric,
                       pr.doctor_id, pr.nurse_id, COALESCE(ns.full_name,ds.full_name),
                       pr.performer_type, pr.shift, pr.reception_user, TRUE, FALSE, FALSE
                FROM accounting.procedures pr
                JOIN accounting.invoices i ON i.tenant_id=pr.tenant_id AND i.id=pr.invoice_id
                JOIN accounting.patients p ON p.tenant_id=pr.tenant_id AND p.id=pr.patient_id
                LEFT JOIN accounting.medical_staff ns ON ns.tenant_id=pr.tenant_id AND ns.id=pr.nurse_id
                LEFT JOIN accounting.medical_staff ds ON ds.tenant_id=pr.tenant_id AND ds.id=pr.doctor_id
                WHERE pr.tenant_id=%s AND i.status='closed'
                UNION ALL
                SELECT 'consumable', c.id, c.invoice_id, c.work_date, c.usage_date,
                       p.full_name, c.item_name, c.quantity::numeric, c.total_cost::numeric,
                       c.total_cost::numeric, 0::numeric,
                       c.doctor_id, c.nurse_id, COALESCE(ns.full_name,ds.full_name),
                       CASE WHEN c.nurse_id IS NOT NULL THEN 'nurse' ELSE NULL END,
                       c.shift, c.reception_user, FALSE, c.patient_provided, c.is_exception
                FROM accounting.consumables_ledger c
                JOIN accounting.invoices i ON i.tenant_id=c.tenant_id AND i.id=c.invoice_id
                JOIN accounting.patients p ON p.tenant_id=c.tenant_id AND p.id=c.patient_id
                LEFT JOIN accounting.medical_staff ns ON ns.tenant_id=c.tenant_id AND ns.id=c.nurse_id
                LEFT JOIN accounting.medical_staff ds ON ds.tenant_id=c.tenant_id AND ds.id=c.doctor_id
                WHERE c.tenant_id=%s AND i.status='closed'
            )
            SELECT * FROM item WHERE {where}
            ORDER BY occurred_at DESC, service_type, id DESC LIMIT %s
            """,
            [self.tenant_id] * 4 + params + [limit],
        )
        rows = _plain_rows(_dict_rows(self.cursor))
        visible = [
            row for row in rows
            if row["service_type"] != "consumable"
            or (not row["patient_provided"] and not row["is_exception"])
        ]
        by_type: dict[str, dict[str, int]] = {}
        for row in visible:
            bucket = by_type.setdefault(row["service_type"], {"count": 0, "amount": 0})
            bucket["count"] += 1
            bucket["amount"] += int(row["amount"] or 0)
        return {
            "date_from": date_from,
            "date_to": date_to,
            "summary": by_type,
            "rows": visible,
        }
