"""Accounting schema check (docs/03 §7). Runs at startup and hourly.

Two checks, both read-only (``PRAGMA table_xinfo`` and ``EXPLAIN QUERY PLAN``
execute nothing):

1. Every column the query contract reads exists. Extra columns are fine.
2. No contract query would scan a large table — a missing index on the
   accounting side would turn a 0.1 ms read into a long SHARED lock.

Any problem disables the bridge; the rest of the app keeps running.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .bridge import ReadSession
from .reader import QUERIES, SMALL_TABLES, sample_params

REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "invoices": frozenset({"id", "patient_id", "status", "work_date", "shift", "opened_at",
                           "closed_at", "opened_by", "total_amount"}),
    "visits": frozenset({"id", "invoice_id", "patient_id", "doctor_id", "work_date", "shift",
                         "visit_date", "price"}),
    "injections": frozenset({"id", "invoice_id", "patient_id", "service_id", "injection_type",
                             "nurse_id", "doctor_id", "total_price", "work_date"}),
    "procedures": frozenset({"id", "invoice_id", "patient_id", "procedure_type", "performer_type",
                             "doctor_id", "nurse_id", "price", "work_date"}),
    "invoice_item_payments": frozenset({"invoice_id", "item_type", "item_id", "payment_type",
                                        "is_paid", "updated_at"}),
    "patients": frozenset({"id", "name", "family_name", "national_id", "phone_number", "is_foreign"}),
    "user_active_shift": frozenset({"user_id", "active_shift", "work_date", "shift_started_at"}),
    "users": frozenset({"id", "username", "password_hash", "role", "full_name", "is_active",
                        "locked_until"}),
    "shift_staff": frozenset({"work_date", "shift", "doctor_id", "nurse_id"}),
    "activity_logs": frozenset({"id", "action_type", "invoice_id", "target_type", "target_id"}),
    "medical_staff": frozenset({"id", "full_name", "staff_type", "is_active"}),
    "nursing_services": frozenset({"id", "service_name", "is_active"}),
}

_SCAN = re.compile(r"^SCAN (?:TABLE )?(\w+)", re.IGNORECASE)


@dataclass
class SchemaReport:
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: dict[str, list[str]] = field(default_factory=dict)
    unsafe_plans: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (self.missing_tables or self.missing_columns or self.unsafe_plans)

    def summary(self) -> str:
        parts = []
        if self.missing_tables:
            parts.append("missing tables: " + ", ".join(self.missing_tables))
        for table, cols in self.missing_columns.items():
            parts.append(f"missing columns in {table}: " + ", ".join(cols))
        for name, lines in self.unsafe_plans.items():
            parts.append(f"{name} would scan: " + "; ".join(lines))
        return " | ".join(parts) or "ok"


def unsafe_plan_lines(s: ReadSession, name: str) -> list[str]:
    sql, params = sample_params(name)
    details = [row[-1] for row in s.fetch("EXPLAIN QUERY PLAN " + sql, params)]
    bad = []
    for detail in details:
        m = _SCAN.match(detail)
        if m and m.group(1) not in SMALL_TABLES:
            bad.append(detail)
    return bad


def check_schema(s: ReadSession) -> SchemaReport:
    report = SchemaReport()
    for table, required in REQUIRED_COLUMNS.items():
        # table_xinfo also lists generated columns (patients.full_name).
        present = {row[1] for row in s.fetch(f"PRAGMA table_xinfo({table})")}
        if not present:
            report.missing_tables.append(table)
            continue
        missing = sorted(required - present)
        if missing:
            report.missing_columns[table] = missing
    if report.missing_tables or report.missing_columns:
        return report  # plans cannot be prepared against a broken schema
    for name in QUERIES:
        bad = unsafe_plan_lines(s, name)
        if bad:
            report.unsafe_plans[name] = bad
    return report
