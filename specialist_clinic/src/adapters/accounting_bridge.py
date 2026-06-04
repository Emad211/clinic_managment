"""Read-only bridge to the accounting app's database (clinic_new.db).

CRITICAL SAFETY RULES:
- This module NEVER writes to the accounting DB.
- The connection is opened with sqlite3 URI `mode=ro` (read-only). Any write
  attempt raises sqlite3.OperationalError instead of mutating the file.
- We never add/alter tables in the accounting DB.

It exposes patient lookup and a lightweight visit history so the specialist
app can pull demographics and activity in real time, linked by national_id.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Optional

from src.config.settings import Config


def _connect_ro() -> Optional[sqlite3.Connection]:
    """Open a read-only connection to the accounting DB, or None if unavailable."""
    path = Config.ACCOUNTING_DB_PATH
    if not path or not os.path.exists(path):
        return None
    try:
        # mode=ro => read-only live view (sees committed writes from the accounting app).
        uri = f"file:{path.replace(os.sep, '/')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 3000")
        return conn
    except Exception:
        return None


def is_available() -> bool:
    """True if the accounting DB exists and can be opened read-only."""
    conn = _connect_ro()
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1 FROM patients LIMIT 1")
        return True
    except Exception:
        return False
    finally:
        conn.close()


def search_patients(query: str, limit: int = 30) -> list[dict[str, Any]]:
    """Search accounting patients by name / national_id / phone."""
    q = (query or "").strip()
    conn = _connect_ro()
    if conn is None:
        return []
    try:
        like = f"%{q}%"
        if q:
            rows = conn.execute(
                """
                SELECT id, full_name, national_id, phone_number, gender, birthdate,
                       address, insurance_type, is_foreign
                FROM patients
                WHERE full_name LIKE ? OR COALESCE(national_id,'') LIKE ? OR COALESCE(phone_number,'') LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, full_name, national_id, phone_number, gender, birthdate,
                       address, insurance_type, is_foreign
                FROM patients
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_patient_by_national_id(national_id: str) -> Optional[dict[str, Any]]:
    if not national_id:
        return None
    conn = _connect_ro()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT id, full_name, national_id, phone_number, gender, birthdate,
                   address, insurance_type, insurance_expiry, is_foreign
            FROM patients WHERE national_id = ?
            """,
            (national_id,),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None
    finally:
        conn.close()


def get_patient_by_id(accounting_patient_id: int) -> Optional[dict[str, Any]]:
    conn = _connect_ro()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT id, full_name, national_id, phone_number, gender, birthdate,
                   address, insurance_type, insurance_expiry, is_foreign
            FROM patients WHERE id = ?
            """,
            (accounting_patient_id,),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None
    finally:
        conn.close()


def _chunks(seq, size=400):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def revenue_for_accounting_ids(ids: list[int], since: str | None = None,
                               until: str | None = None) -> dict[str, int]:
    """Sum accounting revenue for a set of patients (read-only).

    Mirrors the accounting app's definition (webapp manager.py):
      revenue = visits.price + injections.total_price + procedures.price,
      only from CLOSED invoices, excluding consumables, filtered by invoice.work_date.

    `since`/`until` are gregorian 'YYYY-MM-DD' bounds on invoices.work_date (inclusive).
    Returns {'visits','injections','procedures','total','invoices'}.
    """
    out = {'visits': 0, 'injections': 0, 'procedures': 0, 'total': 0, 'invoices': 0}
    ids = [int(x) for x in ids if x]
    if not ids:
        return out
    conn = _connect_ro()
    if conn is None:
        return out
    try:
        for chunk in _chunks(ids):
            ph = ",".join("?" * len(chunk))
            date_clause = ""
            params_tail = []
            if since:
                date_clause += " AND i.work_date >= ?"
                params_tail.append(since)
            if until:
                date_clause += " AND i.work_date <= ?"
                params_tail.append(until)

            v = conn.execute(
                f"""SELECT COALESCE(SUM(v.price),0) s FROM visits v
                    JOIN invoices i ON i.id = v.invoice_id AND i.status='closed'
                    WHERE v.patient_id IN ({ph}){date_clause}""",
                (*chunk, *params_tail)).fetchone()['s']
            inj = conn.execute(
                f"""SELECT COALESCE(SUM(inj.total_price),0) s FROM injections inj
                    JOIN invoices i ON i.id = inj.invoice_id AND i.status='closed'
                    WHERE inj.patient_id IN ({ph}){date_clause}""",
                (*chunk, *params_tail)).fetchone()['s']
            pr = conn.execute(
                f"""SELECT COALESCE(SUM(pr.price),0) s FROM procedures pr
                    JOIN invoices i ON i.id = pr.invoice_id AND i.status='closed'
                    WHERE pr.patient_id IN ({ph}){date_clause}""",
                (*chunk, *params_tail)).fetchone()['s']
            inv = conn.execute(
                f"""SELECT COUNT(*) c FROM invoices i
                    WHERE i.status='closed' AND i.patient_id IN ({ph}){date_clause}""",
                (*chunk, *params_tail)).fetchone()['c']
            out['visits'] += int(v or 0)
            out['injections'] += int(inj or 0)
            out['procedures'] += int(pr or 0)
            out['invoices'] += int(inv or 0)
        out['total'] = out['visits'] + out['injections'] + out['procedures']
        return out
    except Exception:
        return out
    finally:
        conn.close()


def daily_revenue_for_accounting_ids(ids: list[int], date_from: str, date_to: str) -> dict[str, int]:
    """Revenue per work_date (gregorian 'YYYY-MM-DD') for a trend chart. Returns {date: total}."""
    totals: dict[str, int] = {}
    ids = [int(x) for x in ids if x]
    if not ids:
        return totals
    conn = _connect_ro()
    if conn is None:
        return totals
    try:
        for chunk in _chunks(ids):
            ph = ",".join("?" * len(chunk))
            for table, col in (("visits", "price"), ("injections", "total_price"), ("procedures", "price")):
                rows = conn.execute(
                    f"""SELECT i.work_date d, COALESCE(SUM(t.{col}),0) s
                        FROM {table} t JOIN invoices i ON i.id = t.invoice_id AND i.status='closed'
                        WHERE t.patient_id IN ({ph}) AND i.work_date BETWEEN ? AND ?
                        GROUP BY i.work_date""",
                    (*chunk, date_from, date_to)).fetchall()
                for r in rows:
                    if r['d']:
                        totals[r['d']] = totals.get(r['d'], 0) + int(r['s'] or 0)
        return totals
    except Exception:
        return totals
    finally:
        conn.close()


def get_visit_history(accounting_patient_id: int, limit: int = 30) -> list[dict[str, Any]]:
    """Return recent visits for a patient from the accounting DB (real-time)."""
    if not accounting_patient_id:
        return []
    conn = _connect_ro()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT v.id, v.visit_date, v.doctor_name, v.price, v.insurance_type,
                   v.supplementary_insurance, v.invoice_id
            FROM visits v
            WHERE v.patient_id = ?
            ORDER BY v.visit_date DESC
            LIMIT ?
            """,
            (accounting_patient_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()
