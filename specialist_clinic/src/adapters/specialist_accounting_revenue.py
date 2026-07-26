"""Strict read-only accounting projection for explicitly attributed specialist invoices."""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from src.adapters.accounting_path import accounting_db_path


class AccountingRevenueUnavailable(RuntimeError):
    pass


class AccountingRevenueSchemaError(RuntimeError):
    pass


def _connect() -> sqlite3.Connection:
    path = accounting_db_path()
    if not path or not os.path.isfile(path):
        raise AccountingRevenueUnavailable("accounting database is unavailable")
    try:
        uri = f"file:{path.replace(os.sep, '/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection
    except sqlite3.Error as exc:
        raise AccountingRevenueUnavailable(str(exc)) from exc


def _required_tables(connection: sqlite3.Connection) -> None:
    required = {
        "invoices",
        "visits",
        "injections",
        "procedures",
        "invoice_item_payments",
    }
    tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing = sorted(required - tables)
    if missing:
        raise AccountingRevenueSchemaError(
            "missing accounting revenue tables: " + ",".join(missing)
        )


def is_available() -> bool:
    try:
        connection = _connect()
        try:
            _required_tables(connection)
            connection.execute("SELECT 1 FROM invoices LIMIT 1")
            return True
        finally:
            connection.close()
    except (AccountingRevenueUnavailable, AccountingRevenueSchemaError):
        return False


def max_invoice_id(accounting_patient_id: int) -> int:
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT COALESCE(MAX(id),0) AS value FROM invoices WHERE patient_id=?",
            (int(accounting_patient_id),),
        ).fetchone()
        return int(row["value"] or 0)
    except sqlite3.Error as exc:
        raise AccountingRevenueSchemaError(str(exc)) from exc
    finally:
        connection.close()


def invoice_identity(accounting_invoice_id: int) -> dict | None:
    connection = _connect()
    try:
        row = connection.execute(
            """SELECT id AS invoice_id, patient_id, status, work_date,
                      opened_at, closed_at, total_amount
               FROM invoices WHERE id=?""",
            (int(accounting_invoice_id),),
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error as exc:
        raise AccountingRevenueSchemaError(str(exc)) from exc
    finally:
        connection.close()


def _chunks(values: list[int], size: int = 400):
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _normalize_invoice_ids(invoice_ids) -> list[int]:
    return sorted({int(value) for value in invoice_ids or [] if int(value) > 0})


def _date_clause(floor: str | None, until: str | None) -> tuple[str, list[Any]]:
    sql = ""
    params: list[Any] = []
    if floor:
        sql += " AND invoice.work_date>=?"
        params.append(str(floor))
    if until:
        sql += " AND invoice.work_date<=?"
        params.append(str(until))
    return sql, params


def revenue_for_invoice_ids(
    invoice_ids,
    floor: str | None = None,
    until: str | None = None,
) -> dict[str, int]:
    ids = _normalize_invoice_ids(invoice_ids)
    result = {
        "visits": 0,
        "injections": 0,
        "procedures": 0,
        "total": 0,
        "collected": 0,
        "invoices": 0,
    }
    if not ids:
        return result
    connection = _connect()
    try:
        _required_tables(connection)
        date_sql, date_params = _date_clause(floor, until)
        for chunk in _chunks(ids):
            marks = ",".join("?" for _ in chunk)
            for table, amount_column, item_type, key in (
                ("visits", "price", "visit", "visits"),
                ("injections", "total_price", "injection", "injections"),
                ("procedures", "price", "procedure", "procedures"),
            ):
                row = connection.execute(
                    f"""SELECT COALESCE(SUM(item.{amount_column}),0) AS billed,
                               COALESCE(SUM(
                                   CASE WHEN payment.is_paid=1
                                        THEN item.{amount_column} ELSE 0 END
                               ),0) AS collected
                        FROM {table} item
                        JOIN invoices invoice
                          ON invoice.id=item.invoice_id AND invoice.status='closed'
                        LEFT JOIN invoice_item_payments payment
                          ON payment.invoice_id=item.invoice_id
                         AND payment.item_type=? AND payment.item_id=item.id
                        WHERE invoice.id IN ({marks}){date_sql}""",
                    (item_type, *chunk, *date_params),
                ).fetchone()
                result[key] += int(row["billed"] or 0)
                result["collected"] += int(row["collected"] or 0)
            invoice_row = connection.execute(
                f"""SELECT COUNT(*) AS count FROM invoices invoice
                    WHERE invoice.status='closed'
                      AND invoice.id IN ({marks}){date_sql}""",
                (*chunk, *date_params),
            ).fetchone()
            result["invoices"] += int(invoice_row["count"] or 0)
        result["total"] = (
            result["visits"] + result["injections"] + result["procedures"]
        )
        return result
    except sqlite3.Error as exc:
        raise AccountingRevenueSchemaError(str(exc)) from exc
    finally:
        connection.close()


def daily_revenue_for_invoice_ids(
    invoice_ids,
    date_from: str,
    date_to: str,
) -> dict[str, dict[str, int]]:
    ids = _normalize_invoice_ids(invoice_ids)
    output: dict[str, dict[str, int]] = {}
    if not ids:
        return output
    connection = _connect()
    try:
        _required_tables(connection)
        for chunk in _chunks(ids):
            marks = ",".join("?" for _ in chunk)
            for table, amount_column, item_type in (
                ("visits", "price", "visit"),
                ("injections", "total_price", "injection"),
                ("procedures", "price", "procedure"),
            ):
                rows = connection.execute(
                    f"""SELECT invoice.work_date AS day,
                               COALESCE(SUM(item.{amount_column}),0) AS billed,
                               COALESCE(SUM(
                                   CASE WHEN payment.is_paid=1
                                        THEN item.{amount_column} ELSE 0 END
                               ),0) AS collected
                        FROM {table} item
                        JOIN invoices invoice
                          ON invoice.id=item.invoice_id AND invoice.status='closed'
                        LEFT JOIN invoice_item_payments payment
                          ON payment.invoice_id=item.invoice_id
                         AND payment.item_type=? AND payment.item_id=item.id
                        WHERE invoice.id IN ({marks})
                          AND invoice.work_date BETWEEN ? AND ?
                        GROUP BY invoice.work_date""",
                    (item_type, *chunk, str(date_from), str(date_to)),
                ).fetchall()
                for row in rows:
                    bucket = output.setdefault(
                        str(row["day"]), {"billed": 0, "collected": 0}
                    )
                    bucket["billed"] += int(row["billed"] or 0)
                    bucket["collected"] += int(row["collected"] or 0)
        return output
    except sqlite3.Error as exc:
        raise AccountingRevenueSchemaError(str(exc)) from exc
    finally:
        connection.close()


def collected_by_invoice_ids(invoice_ids) -> dict[int, int]:
    ids = _normalize_invoice_ids(invoice_ids)
    output = {invoice_id: 0 for invoice_id in ids}
    if not ids:
        return output
    connection = _connect()
    try:
        _required_tables(connection)
        for chunk in _chunks(ids):
            marks = ",".join("?" for _ in chunk)
            for table, amount_column, item_type in (
                ("visits", "price", "visit"),
                ("injections", "total_price", "injection"),
                ("procedures", "price", "procedure"),
            ):
                rows = connection.execute(
                    f"""SELECT invoice.id AS invoice_id,
                               COALESCE(SUM(
                                   CASE WHEN payment.is_paid=1
                                        THEN item.{amount_column} ELSE 0 END
                               ),0) AS collected
                        FROM {table} item
                        JOIN invoices invoice
                          ON invoice.id=item.invoice_id AND invoice.status='closed'
                        LEFT JOIN invoice_item_payments payment
                          ON payment.invoice_id=item.invoice_id
                         AND payment.item_type=? AND payment.item_id=item.id
                        WHERE invoice.id IN ({marks})
                        GROUP BY invoice.id""",
                    (item_type, *chunk),
                ).fetchall()
                for row in rows:
                    key = int(row["invoice_id"])
                    output[key] = output.get(key, 0) + int(row["collected"] or 0)
        return output
    except sqlite3.Error as exc:
        raise AccountingRevenueSchemaError(str(exc)) from exc
    finally:
        connection.close()
