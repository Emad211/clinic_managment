"""Strict per-invoice accounting snapshot for specialist financial reconciliation.

The accounting database is opened with SQLite ``mode=ro`` and ``query_only=ON``.
No schema migration, status update, payment write, or sidecar creation is allowed here.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from typing import Any

from src.adapters.accounting_path import accounting_db_path


class AccountingInvoiceUnavailable(RuntimeError):
    pass


class AccountingInvoiceSchemaError(RuntimeError):
    pass


def _connect() -> sqlite3.Connection:
    path = accounting_db_path()
    if not path or not os.path.isfile(path):
        raise AccountingInvoiceUnavailable("accounting database is unavailable")
    try:
        uri = f"file:{path.replace(os.sep, '/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection
    except sqlite3.Error as exc:
        raise AccountingInvoiceUnavailable(str(exc)) from exc


def _assert_schema(connection: sqlite3.Connection) -> None:
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
        raise AccountingInvoiceSchemaError(
            "missing accounting invoice tables: " + ",".join(missing)
        )


def is_available() -> bool:
    try:
        connection = _connect()
        try:
            _assert_schema(connection)
            return True
        finally:
            connection.close()
    except (AccountingInvoiceUnavailable, AccountingInvoiceSchemaError):
        return False


def _category(
    connection: sqlite3.Connection,
    *,
    invoice_id: int,
    table: str,
    amount_column: str,
    item_type: str,
) -> dict[str, int]:
    row = connection.execute(
        f"""SELECT COUNT(*) AS item_count,
                   COALESCE(SUM(item.{amount_column}),0) AS billed,
                   COALESCE(SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM invoice_item_payments payment
                       WHERE payment.invoice_id=item.invoice_id
                         AND payment.item_type=?
                         AND payment.item_id=item.id
                         AND payment.is_paid=1
                   ) THEN item.{amount_column} ELSE 0 END),0) AS collected,
                   COALESCE(SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM invoice_item_payments payment
                       WHERE payment.invoice_id=item.invoice_id
                         AND payment.item_type=?
                         AND payment.item_id=item.id
                         AND payment.is_paid=1
                   ) THEN 1 ELSE 0 END),0) AS paid_count
            FROM {table} item WHERE item.invoice_id=?""",
        (item_type, item_type, int(invoice_id)),
    ).fetchone()
    return {
        "item_count": int(row["item_count"] or 0),
        "billed": int(row["billed"] or 0),
        "collected": int(row["collected"] or 0),
        "paid_count": int(row["paid_count"] or 0),
    }


def invoice_financial_snapshot(accounting_invoice_id: int) -> dict[str, Any]:
    invoice_id = int(accounting_invoice_id)
    if invoice_id <= 0:
        raise ValueError("accounting_invoice_id must be positive")
    connection = _connect()
    try:
        _assert_schema(connection)
        invoice = connection.execute(
            """SELECT id AS invoice_id, patient_id, status, work_date,
                      opened_at, closed_at, total_amount
               FROM invoices WHERE id=?""",
            (invoice_id,),
        ).fetchone()
        if not invoice:
            raise LookupError("accounting invoice not found")

        visits = _category(
            connection,
            invoice_id=invoice_id,
            table="visits",
            amount_column="price",
            item_type="visit",
        )
        injections = _category(
            connection,
            invoice_id=invoice_id,
            table="injections",
            amount_column="total_price",
            item_type="injection",
        )
        procedures = _category(
            connection,
            invoice_id=invoice_id,
            table="procedures",
            amount_column="price",
            item_type="procedure",
        )

        billed = visits["billed"] + injections["billed"] + procedures["billed"]
        collected = (
            visits["collected"]
            + injections["collected"]
            + procedures["collected"]
        )
        item_count = (
            visits["item_count"]
            + injections["item_count"]
            + procedures["item_count"]
        )
        paid_count = (
            visits["paid_count"]
            + injections["paid_count"]
            + procedures["paid_count"]
        )
        status = str(invoice["status"] or "").strip().lower()
        if status != "closed":
            collection_state = "WAITING_FOR_INVOICE_CLOSURE"
        elif item_count == 0:
            collection_state = "CLOSED_NO_BILLABLE_ITEMS"
        elif collected <= 0:
            collection_state = "UNPAID"
        elif collected < billed:
            collection_state = "PARTIALLY_COLLECTED"
        else:
            collection_state = "COLLECTED"

        payload = {
            "accounting_invoice_id": invoice_id,
            "accounting_patient_id": int(invoice["patient_id"]),
            "invoice_status": status or "unknown",
            "work_date": invoice["work_date"],
            "opened_at": invoice["opened_at"],
            "closed_at": invoice["closed_at"],
            "source_total_amount": (
                int(invoice["total_amount"])
                if invoice["total_amount"] is not None
                else None
            ),
            "visits_billed": visits["billed"],
            "injections_billed": injections["billed"],
            "procedures_billed": procedures["billed"],
            "billed_amount": billed,
            "visits_collected": visits["collected"],
            "injections_collected": injections["collected"],
            "procedures_collected": procedures["collected"],
            "collected_amount": collected,
            "billable_item_count": item_count,
            "paid_item_count": paid_count,
            "collection_state": collection_state,
            "payment_evidence": "ITEM_PAID_FLAGS",
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        payload["source_fingerprint"] = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        return payload
    except sqlite3.Error as exc:
        raise AccountingInvoiceSchemaError(str(exc)) from exc
    finally:
        connection.close()
