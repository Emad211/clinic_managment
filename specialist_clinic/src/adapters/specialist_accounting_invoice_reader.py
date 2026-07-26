"""Strict per-invoice accounting snapshot for specialist financial reconciliation.

The accounting database is opened with SQLite ``mode=ro`` and ``query_only=ON``.
No schema migration, status update, payment write, or sidecar creation is allowed here.

A7 additionally separates only what the accounting rows explicitly prove: cash, card,
insurance, and unknown paid amounts. An unpaid amount is not assigned to patient or
insurer unless accounting carries such evidence. Legacy schemas that do not yet expose
payment types remain readable, but all paid amounts are classified as unknown rather
than guessed.
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


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


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

    required_columns = {
        "invoices": {"id", "patient_id", "status", "work_date", "opened_at", "closed_at", "total_amount"},
        "visits": {"id", "invoice_id", "price"},
        "injections": {"id", "invoice_id", "total_price"},
        "procedures": {"id", "invoice_id", "price"},
        "invoice_item_payments": {"invoice_id", "item_type", "item_id", "is_paid"},
    }
    for table, expected in required_columns.items():
        absent = sorted(expected - _table_columns(connection, table))
        if absent:
            raise AccountingInvoiceSchemaError(
                f"missing accounting columns in {table}: " + ",".join(absent)
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
    payment_type_available: bool,
) -> dict[str, int]:
    payment_type = (
        "lower(trim(COALESCE(payment.payment_type,'')))"
        if payment_type_available
        else "''"
    )
    row = connection.execute(
        f"""SELECT COUNT(*) AS item_count,
                    COALESCE(SUM(item.{amount_column}),0) AS billed,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        THEN item.{amount_column} ELSE 0 END),0) AS collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        THEN 1 ELSE 0 END),0) AS paid_count,
                    COALESCE(SUM(CASE WHEN COALESCE(payment.is_paid,0)<>1
                        THEN item.{amount_column} ELSE 0 END),0) AS unpaid,
                    COALESCE(SUM(CASE WHEN COALESCE(payment.is_paid,0)<>1
                        THEN 1 ELSE 0 END),0) AS unpaid_count,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type}='cash'
                        THEN item.{amount_column} ELSE 0 END),0) AS cash_collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type}='card'
                        THEN item.{amount_column} ELSE 0 END),0) AS card_collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type}='insurance'
                        THEN item.{amount_column} ELSE 0 END),0) AS insurance_collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type} NOT IN ('cash','card','insurance')
                        THEN item.{amount_column} ELSE 0 END),0) AS unknown_collected,
                    COALESCE(SUM(CASE WHEN payment.is_paid=1
                        AND {payment_type} NOT IN ('cash','card','insurance')
                        THEN 1 ELSE 0 END),0) AS unknown_type_count
             FROM {table} item
             LEFT JOIN invoice_item_payments payment
               ON payment.invoice_id=item.invoice_id
              AND payment.item_type=?
              AND payment.item_id=item.id
             WHERE item.invoice_id=?""",
        (item_type, int(invoice_id)),
    ).fetchone()
    return {
        "item_count": int(row["item_count"] or 0),
        "billed": int(row["billed"] or 0),
        "collected": int(row["collected"] or 0),
        "paid_count": int(row["paid_count"] or 0),
        "unpaid": int(row["unpaid"] or 0),
        "unpaid_count": int(row["unpaid_count"] or 0),
        "cash_collected": int(row["cash_collected"] or 0),
        "card_collected": int(row["card_collected"] or 0),
        "insurance_collected": int(row["insurance_collected"] or 0),
        "unknown_collected": int(row["unknown_collected"] or 0),
        "unknown_type_count": int(row["unknown_type_count"] or 0),
    }


def invoice_financial_snapshot(accounting_invoice_id: int) -> dict[str, Any]:
    invoice_id = int(accounting_invoice_id)
    if invoice_id <= 0:
        raise ValueError("accounting_invoice_id must be positive")
    connection = _connect()
    try:
        _assert_schema(connection)
        invoice_columns = _table_columns(connection, "invoices")
        payment_columns = _table_columns(connection, "invoice_item_payments")
        insurance_select = (
            "insurance_type" if "insurance_type" in invoice_columns
            else "NULL AS insurance_type"
        )
        supplementary_select = (
            "supplementary_insurance"
            if "supplementary_insurance" in invoice_columns
            else "NULL AS supplementary_insurance"
        )
        payment_type_available = "payment_type" in payment_columns

        invoice = connection.execute(
            f"""SELECT id AS invoice_id,patient_id,status,work_date,
                       opened_at,closed_at,total_amount,{insurance_select},
                       {supplementary_select}
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
            payment_type_available=payment_type_available,
        )
        injections = _category(
            connection,
            invoice_id=invoice_id,
            table="injections",
            amount_column="total_price",
            item_type="injection",
            payment_type_available=payment_type_available,
        )
        procedures = _category(
            connection,
            invoice_id=invoice_id,
            table="procedures",
            amount_column="price",
            item_type="procedure",
            payment_type_available=payment_type_available,
        )
        categories = (visits, injections, procedures)
        billed = sum(category["billed"] for category in categories)
        collected = sum(category["collected"] for category in categories)
        item_count = sum(category["item_count"] for category in categories)
        paid_count = sum(category["paid_count"] for category in categories)
        unpaid_count = sum(category["unpaid_count"] for category in categories)
        cash_collected = sum(category["cash_collected"] for category in categories)
        card_collected = sum(category["card_collected"] for category in categories)
        insurance_collected = sum(
            category["insurance_collected"] for category in categories
        )
        unknown_collected = sum(
            category["unknown_collected"] for category in categories
        )
        unpaid_amount = sum(category["unpaid"] for category in categories)
        unknown_type_count = sum(
            category["unknown_type_count"] for category in categories
        )
        if (
            cash_collected
            + card_collected
            + insurance_collected
            + unknown_collected
            != collected
        ):
            raise AccountingInvoiceSchemaError(
                "payer breakdown does not equal collected amount"
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
            "insurance_type": invoice["insurance_type"],
            "supplementary_insurance": invoice["supplementary_insurance"],
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
            "unpaid_item_count": unpaid_count,
            "collection_state": collection_state,
            "payment_evidence": "ITEM_PAID_FLAGS",
            "patient_cash_collected": cash_collected,
            "patient_card_collected": card_collected,
            "insurance_collected": insurance_collected,
            "unknown_collected": unknown_collected,
            "unpaid_amount": unpaid_amount,
            "unknown_payment_type_count": unknown_type_count,
            "payer_breakdown_evidence": (
                "ACCOUNTING_ITEM_PAYMENT_TYPE_V1"
                if payment_type_available
                else "LEGACY_UNAVAILABLE"
            ),
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
