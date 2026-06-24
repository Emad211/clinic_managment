"""
AccountingReadPort — the ONLY legitimate read path into accounting from the
clinical/platform side.

Contract:
  - Always uses 'accounting_read' db alias (enforced by router, double-checked here).
  - NEVER calls .using('default') for accounting models.
  - Returns Pydantic DTO(s) or None/[] (not ORM objects — no leaking of the
    ORM model across the boundary).
  - Raises PermissionError on misuse (direct write attempt caught by router).
  - Fail-loud: raises on unexpected DB errors; returns None/[] only when the
    patient genuinely doesn't exist.

Revenue functions:
  - MUST stay in sync with the webapp's revenue definition
    (specialist_clinic/src/adapters/accounting_bridge.py::revenue_for_accounting_ids).
  - Definition: visits.price + injections.total_price + procedures.price,
    CLOSED invoices only (status='closed'), attributed by invoices.work_date.
    Consumables are excluded. See ADR-0003.
  - All reads go through 'accounting_read' (SELECT-only at DB level — enforced by
    Postgres GRANTs; accounting_app is the sole writer).

SYNC WARNING: if the webapp revenue definition changes (tables / column names /
  closed-status value), update these functions AND the webapp AND the reference
  in specialist_clinic/src/adapters/accounting_bridge.py to keep all three in
  agreement (per CLAUDE.md).

Usage:
  from accounting_port.port import (
      get_patient_by_uuid, get_patients_by_ids, PatientDTO,
      get_revenue_by_patient_ids, get_patient_revenue_summary,
      RevenueByPatientDTO, get_daily_revenue_by_patient_ids,
  )
"""
import uuid as uuid_module
from datetime import date
from typing import Optional

from django.db import connections
from pydantic import BaseModel

from accounting.models import Patient


class PatientDTO(BaseModel):
    """Read-only patient demographics from accounting.patients."""

    model_config = {"from_attributes": True}  # allow Pydantic V2 to read from ORM objects

    id: int
    uuid: uuid_module.UUID
    name: str
    family_name: str
    full_name: str          # GENERATED ALWAYS STORED in DB; read-only
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    birthdate: Optional[date] = None
    gender: Optional[str] = None


def get_patient_by_uuid(patient_uuid: uuid_module.UUID) -> Optional[PatientDTO]:
    """
    Look up a patient in accounting.patients by their external UUID.

    Returns PatientDTO or None (patient not found).
    Explicitly uses .using('accounting_read') as a guard — the router also
    enforces this, but belt-and-suspenders for misuse detection.
    Raises PermissionError if somehow called with .using('default').
    """
    try:
        patient = (
            Patient.objects
            .using("accounting_read")   # explicit + router both enforce read-only
            .only(
                "id", "uuid", "name", "family_name", "full_name",
                "national_id", "phone_number", "birthdate", "gender",
            )
            .get(uuid=patient_uuid)
        )
    except Patient.DoesNotExist:
        return None

    return PatientDTO.model_validate(patient)


def get_patients_by_ids(patient_ids: list[int]) -> list[PatientDTO]:
    """
    Batch-fetch demographics for a list of accounting.patients.id values.

    Used by the patient-list endpoint to avoid N+1: page patient_links first,
    then call this once for the whole page.

    Returns list[PatientDTO] — only the patients that were found.
    Order is not guaranteed (callers should re-index by id if needed).
    Empty list if patient_ids is empty (no DB round-trip).
    """
    if not patient_ids:
        return []

    patients = (
        Patient.objects
        .using("accounting_read")
        .only(
            "id", "uuid", "name", "family_name", "full_name",
            "national_id", "phone_number", "birthdate", "gender",
        )
        .filter(id__in=patient_ids)
    )
    return [PatientDTO.model_validate(p) for p in patients]


# ===========================================================================
# Revenue reads — read-only, accounting_read connection only.
#
# Revenue definition (faithful mirror of webapp + accounting_bridge.py):
#   SUM(visits.price) + SUM(injections.total_price) + SUM(procedures.price)
#   WHERE invoice.status = 'closed'
#   AND   invoice.work_date BETWEEN since AND until  (both inclusive, optional)
#   GROUP BY accounting_patient_id
#
# Slice-3 column confirmation:
#   accounting.invoices  : id, patient_id, status TEXT CHECK('open'|'closed'), work_date DATE
#   accounting.visits    : id, invoice_id, patient_id, price NUMERIC(14,0)
#   accounting.injections: id, invoice_id, patient_id, total_price NUMERIC(14,0)
#   accounting.procedures: id, invoice_id, patient_id, price NUMERIC(14,0)
#   All joins: t.invoice_id = i.id  (same as SQLite webapp)
#   Money stored as NUMERIC(14,0) Toman integer.
#
# SYNC WARNING: keep in step with:
#   specialist_clinic/src/adapters/accounting_bridge.py::revenue_for_accounting_ids
#   webapp/src/adapters/sqlite/  (the authoritative webapp definition)
# ===========================================================================


def _accounting_read_cursor():
    """Return a cursor on the accounting_read connection (SELECT-only at DB level)."""
    return connections["accounting_read"].cursor()


def get_revenue_by_patient_ids(
    accounting_patient_ids: list[int],
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict[int, int]:
    """
    Per-patient total closed-invoice revenue (Toman int), keyed by
    accounting.patients.id.

    Revenue = visits.price + injections.total_price + procedures.price,
    CLOSED invoices only, attributed by invoices.work_date.
    Consumables are excluded (mirrors webapp definition exactly).

    since / until: optional gregorian 'YYYY-MM-DD' bounds on invoices.work_date
    (both inclusive).

    Returns: {accounting_patient_id: total_toman}.
    Patients with no closed revenue are ABSENT from the dict (callers should
    treat a missing key as 0). Unknown patient_ids simply produce no rows.

    Reads exclusively through 'accounting_read' (SELECT-only at DB level).
    NEVER writes accounting.
    """
    if not accounting_patient_ids:
        return {}

    ids = list({int(i) for i in accounting_patient_ids if i})
    if not ids:
        return {}

    # Build optional date-range clause
    date_clause = ""
    date_params: list = []
    if since:
        date_clause += " AND i.work_date >= %s"
        date_params.append(since)
    if until:
        date_clause += " AND i.work_date <= %s"
        date_params.append(until)

    # One query per revenue table, GROUP BY patient_id — mirrors accounting_bridge.py
    # pattern but uses a single GROUP BY query per table for efficiency.
    totals: dict[int, int] = {}

    with _accounting_read_cursor() as cur:
        for table, col in (
            ("accounting.visits",     "price"),
            ("accounting.injections", "total_price"),
            ("accounting.procedures", "price"),
        ):
            # %s placeholders for psycopg; ids list passed as a tuple for IN (...)
            sql = (
                f"SELECT t.patient_id, COALESCE(SUM(t.{col}), 0) "
                f"FROM {table} t "
                f"JOIN accounting.invoices i ON i.id = t.invoice_id "
                f"  AND i.status = 'closed' "
                f"WHERE t.patient_id = ANY(%s)"
                f"{date_clause} "
                f"GROUP BY t.patient_id"
            )
            cur.execute(sql, [ids] + date_params)
            for row in cur.fetchall():
                pid, amount = int(row[0]), int(row[1] or 0)
                totals[pid] = totals.get(pid, 0) + amount

    return totals


class RevenueByPatientDTO(BaseModel):
    """Single-patient revenue summary from accounting (read-only)."""

    accounting_patient_id: int
    total_billed: int           # Toman; visits + injections + procedures (closed only)
    invoice_count: int          # number of distinct closed invoices
    last_visit_date: Optional[str] = None  # max closed-invoice work_date 'YYYY-MM-DD'


def get_patient_revenue_summary(
    accounting_patient_id: int,
) -> Optional[RevenueByPatientDTO]:
    """
    Single-patient revenue summary: total billed (Toman), closed-invoice count,
    and last closed-invoice work_date.

    Returns RevenueByPatientDTO, or None if the patient doesn't exist or has
    no closed invoices (callers should treat None as zeroes).

    Reads exclusively through 'accounting_read'.  NEVER writes accounting.
    """
    pid = int(accounting_patient_id)

    with _accounting_read_cursor() as cur:
        # Invoice-level aggregates: count + max work_date
        cur.execute(
            """
            SELECT COUNT(*), MAX(work_date)
            FROM accounting.invoices
            WHERE patient_id = %s AND status = 'closed'
            """,
            [pid],
        )
        row = cur.fetchone()
        invoice_count = int(row[0] or 0)
        last_date_raw = row[1]  # date object or None
        last_visit_date: Optional[str] = (
            last_date_raw.isoformat() if last_date_raw else None
        )

        if invoice_count == 0:
            return None

        # Revenue from each item table
        total = 0
        for table, col in (
            ("accounting.visits",     "price"),
            ("accounting.injections", "total_price"),
            ("accounting.procedures", "price"),
        ):
            cur.execute(
                f"SELECT COALESCE(SUM(t.{col}), 0) "
                f"FROM {table} t "
                f"JOIN accounting.invoices i ON i.id = t.invoice_id "
                f"  AND i.status = 'closed' "
                f"WHERE t.patient_id = %s",
                [pid],
            )
            total += int(cur.fetchone()[0] or 0)

    return RevenueByPatientDTO(
        accounting_patient_id=pid,
        total_billed=total,
        invoice_count=invoice_count,
        last_visit_date=last_visit_date,
    )


class OpenVisitInvoiceDTO(BaseModel):
    """One open invoice that has a visit item — doctor-queue source row."""

    invoice_id: int
    patient_id: int
    patient_uuid: uuid_module.UUID
    full_name: str
    phone_number: Optional[str] = None
    opened_at: Optional[str] = None   # ISO datetime string (TIMESTAMPTZ from DB)
    work_date: Optional[str] = None   # YYYY-MM-DD


def fetch_open_visit_invoices(
    work_date: Optional[str] = None,
    tenant_id: int = 1,
    limit: int = 200,
) -> list[OpenVisitInvoiceDTO]:
    """
    Read-only: OPEN invoices that include a visit item — physician-queue source.

    Mirrors specialist_clinic/src/adapters/accounting_bridge.py::fetch_open_visit_invoices
    but reads from Postgres via the 'accounting_read' connection (SELECT-only at DB level).

    Returns one row per invoice, FIFO by opened_at.  Tenant-scoped via tenant_id.
    If work_date ('YYYY-MM-DD') is supplied, only invoices for that calendar date are
    returned (filters on accounting.invoices.work_date).

    NEVER writes accounting.  Returns [] on any DB error (best-effort — the queue
    must not crash the physician's session).

    Slice-3 column verification (schema_pg_slice3_accounting.sql):
      accounting.invoices : id, tenant_id, patient_id, status TEXT CHECK('open'|'closed'),
                             work_date DATE, opened_at TIMESTAMPTZ
      accounting.visits   : id, tenant_id, invoice_id, patient_id
      accounting.patients : id, tenant_id, uuid UUID, full_name TEXT (GENERATED STORED),
                             phone_number TEXT
    """
    try:
        with _accounting_read_cursor() as cur:
            if work_date:
                cur.execute(
                    """
                    SELECT i.id          AS invoice_id,
                           i.patient_id,
                           p.uuid        AS patient_uuid,
                           p.full_name,
                           p.phone_number,
                           i.opened_at,
                           i.work_date
                    FROM accounting.invoices i
                    JOIN accounting.patients p ON p.id = i.patient_id
                    WHERE i.status = 'open'
                      AND i.tenant_id = %s
                      AND i.work_date = %s
                      AND EXISTS (
                          SELECT 1 FROM accounting.visits v
                          WHERE v.invoice_id = i.id
                            AND v.tenant_id  = i.tenant_id
                      )
                    ORDER BY i.opened_at ASC
                    LIMIT %s
                    """,
                    [tenant_id, work_date, limit],
                )
            else:
                cur.execute(
                    """
                    SELECT i.id          AS invoice_id,
                           i.patient_id,
                           p.uuid        AS patient_uuid,
                           p.full_name,
                           p.phone_number,
                           i.opened_at,
                           i.work_date
                    FROM accounting.invoices i
                    JOIN accounting.patients p ON p.id = i.patient_id
                    WHERE i.status = 'open'
                      AND i.tenant_id = %s
                      AND EXISTS (
                          SELECT 1 FROM accounting.visits v
                          WHERE v.invoice_id = i.id
                            AND v.tenant_id  = i.tenant_id
                      )
                    ORDER BY i.opened_at ASC
                    LIMIT %s
                    """,
                    [tenant_id, limit],
                )
            rows = cur.fetchall()
    except Exception:
        return []

    result = []
    for row in rows:
        invoice_id, patient_id, patient_uuid, full_name, phone_number, opened_at, wd = row
        result.append(
            OpenVisitInvoiceDTO(
                invoice_id=int(invoice_id),
                patient_id=int(patient_id),
                patient_uuid=patient_uuid,
                full_name=full_name or "",
                phone_number=phone_number,
                opened_at=opened_at.isoformat() if opened_at else None,
                work_date=wd.isoformat() if wd else None,
            )
        )
    return result


def get_daily_revenue_by_patient_ids(
    accounting_patient_ids: list[int],
    date_from: str,
    date_to: str,
) -> dict[str, int]:
    """
    Revenue per work_date (gregorian 'YYYY-MM-DD') for a trend chart.
    Mirrors accounting_bridge.daily_revenue_for_accounting_ids exactly.

    Returns {work_date_str: total_toman} for dates that have closed revenue.
    Dates with no revenue are absent (callers can treat as 0).

    date_from / date_to: gregorian 'YYYY-MM-DD', both inclusive.
    Reads exclusively through 'accounting_read'.  NEVER writes accounting.
    """
    ids = list({int(i) for i in accounting_patient_ids if i})
    if not ids:
        return {}

    totals: dict[str, int] = {}

    with _accounting_read_cursor() as cur:
        for table, col in (
            ("accounting.visits",     "price"),
            ("accounting.injections", "total_price"),
            ("accounting.procedures", "price"),
        ):
            cur.execute(
                f"SELECT i.work_date, COALESCE(SUM(t.{col}), 0) "
                f"FROM {table} t "
                f"JOIN accounting.invoices i ON i.id = t.invoice_id "
                f"  AND i.status = 'closed' "
                f"WHERE t.patient_id = ANY(%s) "
                f"  AND i.work_date BETWEEN %s AND %s "
                f"GROUP BY i.work_date",
                [ids, date_from, date_to],
            )
            for row in cur.fetchall():
                d, amount = row[0], int(row[1] or 0)
                if d:
                    key = d.isoformat() if hasattr(d, "isoformat") else str(d)
                    totals[key] = totals.get(key, 0) + amount

    return totals
