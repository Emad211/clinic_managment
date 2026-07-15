from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db import connections, transaction


def _rows(cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [
        {
            key: (
                int(value)
                if isinstance(value, Decimal) and value == value.to_integral_value()
                else float(value) if isinstance(value, Decimal) else value
            )
            for key, value in zip(columns, row)
        }
        for row in cursor.fetchall()
    ]


def _row(cursor) -> dict[str, Any]:
    rows = _rows(cursor)
    return rows[0] if rows else {}


class AccountingAuditRepository:
    @classmethod
    def search(
        cls,
        *,
        tenant_id: int,
        date_from: date,
        date_to: date,
        page: int,
        page_size: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        with transaction.atomic(using="accounting_read"):
            with connections["accounting_read"].cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, true)",
                    [str(tenant_id)],
                )
                return cls(cursor, tenant_id=tenant_id)._search(
                    date_from=date_from,
                    date_to=date_to,
                    page=page,
                    page_size=page_size,
                    filters=filters,
                )

    def __init__(self, cursor, *, tenant_id: int):
        self.cursor = cursor
        self.tenant_id = tenant_id

    def _where(
        self,
        *,
        date_from: date,
        date_to: date,
        filters: dict[str, Any],
    ) -> tuple[str, list[Any]]:
        clauses = [
            "a.tenant_id=%s",
            "a.created_at >= %s::date",
            "a.created_at < %s::date",
        ]
        params: list[Any] = [self.tenant_id, date_from, date_to + timedelta(days=1)]
        exact = {
            "user_id": "a.user_id",
            "action_type": "a.action_type",
            "action_category": "a.action_category",
            "invoice_id": "a.invoice_id",
            "patient_id": "a.patient_id",
        }
        for key, column in exact.items():
            value = filters.get(key)
            if value not in (None, ""):
                clauses.append(f"{column}=%s")
                params.append(value)
        search = filters.get("search_text")
        if search:
            clauses.append(
                "(" 
                "COALESCE(a.description,'') ILIKE %s OR "
                "COALESCE(a.patient_name,'') ILIKE %s OR "
                "COALESCE(a.target_name,'') ILIKE %s OR "
                "COALESCE(a.username,'') ILIKE %s OR "
                "a.action_type ILIKE %s"
                ")"
            )
            pattern = f"%{search}%"
            params.extend([pattern] * 5)
        return " AND ".join(clauses), params

    def _search(
        self,
        *,
        date_from: date,
        date_to: date,
        page: int,
        page_size: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        where, params = self._where(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
        )
        self.cursor.execute(
            f"SELECT COUNT(*)::bigint AS total FROM accounting.activity_logs a WHERE {where}",
            params,
        )
        total = int(_row(self.cursor).get("total") or 0)
        offset = (page - 1) * page_size
        self.cursor.execute(
            f"""
            SELECT a.id,a.created_at,a.user_id,
                   COALESCE(a.username,u.username,'system') AS username,
                   COALESCE(u.full_name,a.username,'system') AS user_full_name,
                   a.action_type,a.action_category,a.description,
                   a.target_type,a.target_id,a.target_name,
                   a.invoice_id,a.patient_id,a.patient_name,a.amount,
                   LEFT(a.old_value,1000) AS old_value,
                   LEFT(a.new_value,1000) AS new_value,
                   a.ip_address,LEFT(a.user_agent,300) AS user_agent
            FROM accounting.activity_logs a
            LEFT JOIN platform.users u
              ON u.tenant_id=a.tenant_id AND u.id=a.user_id
            WHERE {where}
            ORDER BY a.created_at DESC,a.id DESC
            LIMIT %s OFFSET %s
            """,
            [*params, page_size, offset],
        )
        rows = _rows(self.cursor)

        self.cursor.execute(
            f"""
            SELECT action_category,COUNT(*)::bigint AS count
            FROM accounting.activity_logs a
            WHERE {where}
            GROUP BY action_category
            ORDER BY count DESC,action_category
            """,
            params,
        )
        category_summary = _rows(self.cursor)

        self.cursor.execute(
            """
            SELECT DISTINCT a.action_type
            FROM accounting.activity_logs a
            WHERE a.tenant_id=%s
            ORDER BY a.action_type
            """,
            [self.tenant_id],
        )
        action_types = [row[0] for row in self.cursor.fetchall()]
        self.cursor.execute(
            """
            SELECT DISTINCT a.action_category
            FROM accounting.activity_logs a
            WHERE a.tenant_id=%s
            ORDER BY a.action_category
            """,
            [self.tenant_id],
        )
        action_categories = [row[0] for row in self.cursor.fetchall()]
        self.cursor.execute(
            """
            SELECT DISTINCT a.user_id,
                   COALESCE(a.username,u.username,'system') AS username,
                   COALESCE(u.full_name,a.username,'system') AS full_name
            FROM accounting.activity_logs a
            LEFT JOIN platform.users u
              ON u.tenant_id=a.tenant_id AND u.id=a.user_id
            WHERE a.tenant_id=%s
            ORDER BY full_name,username
            """,
            [self.tenant_id],
        )
        users = _rows(self.cursor)
        return {
            "date_from": date_from,
            "date_to": date_to,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "rows": rows,
            "category_summary": category_summary,
            "filter_options": {
                "action_types": action_types,
                "action_categories": action_categories,
                "users": users,
            },
        }
