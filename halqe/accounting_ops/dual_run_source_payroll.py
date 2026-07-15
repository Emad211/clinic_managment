from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import Any

from accounting_ops.import_common import SourceDatabaseError


def _decimal(value: Any, default: str = "0") -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal(default)


def _legacy_default(value: Any, default: str) -> Decimal:
    number = _decimal(value)
    return number if number != 0 else Decimal(default)


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.001")))


def _scalar(db: sqlite3.Connection, query: str, params: list[Any]) -> Decimal:
    row = db.execute(query, params).fetchone()
    return _decimal(row[0] if row else 0)


def _shift_clause(alias: str, shift: str | None) -> tuple[str, list[Any]]:
    return (f" AND {alias}.shift=?", [shift]) if shift else ("", [])


def load_legacy_payroll(
    *,
    sqlite_path: str | Path,
    date_from: date,
    date_to: date,
    shift: str | None,
) -> dict[str, Any]:
    path = Path(sqlite_path).expanduser().absolute()
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    try:
        db = sqlite3.connect(uri, uri=True)
        db.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise SourceDatabaseError("Cannot open legacy payroll snapshot") from exc
    try:
        tables = {
            str(row[0])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not {"medical_staff", "payroll_settings"} <= tables:
            raise SourceDatabaseError("Legacy payroll tables are missing")
        staff = db.execute(
            """
            SELECT m.id,m.full_name,m.staff_type,
                   ps.base_morning,ps.base_evening,ps.base_night,
                   ps.visit_fee,ps.injection_percent,ps.procedure_percent,
                   ps.tax_percent,ps.nursing_percent,ps.nurse_procedure_percent
            FROM medical_staff m
            LEFT JOIN payroll_settings ps ON ps.staff_id=m.id
            WHERE COALESCE(m.is_active,1)=1
            ORDER BY m.staff_type,m.full_name,m.id
            """
        ).fetchall()
        start, end = date_from.isoformat(), date_to.isoformat()
        rows: list[dict[str, Any]] = []
        total_gross = Decimal("0")
        total_tax = Decimal("0")
        total_net = Decimal("0")

        for person in staff:
            person_id = int(person["id"])
            person_type = str(person["staff_type"])
            details: list[dict[str, Any]] = []
            gross = Decimal("0")
            tax = Decimal("0")

            clause, shift_params = _shift_clause("actual", shift)
            if person_type == "doctor":
                count_rows = db.execute(
                    f"""
                    SELECT actual.shift,COUNT(*)
                    FROM (
                        SELECT DISTINCT work_date,shift
                        FROM visits
                        WHERE doctor_id=? AND work_date BETWEEN ? AND ?
                    ) actual
                    WHERE actual.shift IS NOT NULL {clause}
                    GROUP BY actual.shift
                    """,
                    [person_id, start, end, *shift_params],
                ).fetchall()
            else:
                count_rows = db.execute(
                    f"""
                    SELECT actual.shift,COUNT(*)
                    FROM (
                        SELECT DISTINCT v.work_date,v.shift
                        FROM visits v
                        JOIN invoices i ON i.id=v.invoice_id
                        WHERE v.work_date BETWEEN ? AND ?
                          AND (
                            EXISTS (SELECT 1 FROM injections n
                                    WHERE n.invoice_id=i.id AND n.nurse_id=?)
                            OR EXISTS (SELECT 1 FROM procedures p
                                       WHERE p.invoice_id=i.id AND p.nurse_id=?)
                          )
                    ) actual
                    WHERE actual.shift IS NOT NULL {clause}
                    GROUP BY actual.shift
                    """,
                    [start, end, person_id, person_id, *shift_params],
                ).fetchall()
            counts = {str(row[0]): int(row[1]) for row in count_rows}
            base_by_shift = {
                "morning": _decimal(person["base_morning"]),
                "evening": _decimal(person["base_evening"]),
                "night": _decimal(person["base_night"]),
            }
            for key in ("morning", "evening", "night"):
                count = counts.get(key, 0)
                amount = base_by_shift[key] * count
                if count:
                    details.append({
                        "code": f"shift_{key}",
                        "count": count,
                        "unit_price": _money(base_by_shift[key]),
                        "total": _money(amount),
                    })
                gross += amount

            if person_type == "doctor":
                clause, extra = _shift_clause("v", shift)
                visits = _scalar(
                    db,
                    f"""
                    SELECT COUNT(*) FROM visits v
                    JOIN invoices i ON i.id=v.invoice_id
                    WHERE v.doctor_id=? AND v.work_date BETWEEN ? AND ?
                      AND i.status='closed' {clause}
                    """,
                    [person_id, start, end, *extra],
                )
                visit_fee = _legacy_default(person["visit_fee"], "20000")
                visit_total = visits * visit_fee
                if visits:
                    details.append({
                        "code": "visits", "count": int(visits),
                        "unit_price": _money(visit_fee), "total": _money(visit_total),
                    })
                gross += visit_total

                clause, extra = _shift_clause("n", shift)
                injection_base = _scalar(
                    db,
                    f"""
                    SELECT COALESCE(SUM(n.total_price),0)
                    FROM injections n JOIN invoices i ON i.id=n.invoice_id
                    WHERE n.doctor_id=? AND n.work_date BETWEEN ? AND ?
                      AND i.status='closed'
                      AND EXISTS (SELECT 1 FROM visits v
                                  WHERE v.invoice_id=n.invoice_id
                                    AND v.doctor_id=n.doctor_id) {clause}
                    """,
                    [person_id, start, end, *extra],
                )
                percent = _legacy_default(person["injection_percent"], "30")
                total = injection_base * percent / Decimal("100")
                if total:
                    details.append({
                        "code": "doctor_nursing_share", "count": 1,
                        "unit_price": _money(injection_base), "total": _money(total),
                    })
                gross += total

                clause, extra = _shift_clause("p", shift)
                procedure_base = _scalar(
                    db,
                    f"""
                    SELECT COALESCE(SUM(p.price),0)
                    FROM procedures p JOIN invoices i ON i.id=p.invoice_id
                    WHERE p.doctor_id=? AND p.work_date BETWEEN ? AND ?
                      AND i.status='closed' {clause}
                    """,
                    [person_id, start, end, *extra],
                )
                percent = _legacy_default(person["procedure_percent"], "40")
                total = procedure_base * percent / Decimal("100")
                if total:
                    details.append({
                        "code": "doctor_procedure_share", "count": 1,
                        "unit_price": _money(procedure_base), "total": _money(total),
                    })
                gross += total
                tax = gross * _legacy_default(person["tax_percent"], "10") / Decimal("100")
                details.append({
                    "code": "tax", "count": 1,
                    "unit_price": _money(gross), "total": -_money(tax),
                })
            else:
                clause, extra = _shift_clause("n", shift)
                base = _scalar(
                    db,
                    f"""
                    SELECT COALESCE(SUM(n.total_price),0)
                    FROM injections n JOIN invoices i ON i.id=n.invoice_id
                    WHERE n.nurse_id=? AND n.work_date BETWEEN ? AND ?
                      AND i.status='closed' {clause}
                    """,
                    [person_id, start, end, *extra],
                )
                total = base * _legacy_default(person["nursing_percent"], "6") / Decimal("100")
                if total:
                    details.append({
                        "code": "nurse_nursing_share", "count": 1,
                        "unit_price": _money(base), "total": _money(total),
                    })
                gross += total

                clause, extra = _shift_clause("p", shift)
                base = _scalar(
                    db,
                    f"""
                    SELECT COALESCE(SUM(p.price),0)
                    FROM procedures p JOIN invoices i ON i.id=p.invoice_id
                    WHERE p.nurse_id=? AND p.work_date BETWEEN ? AND ?
                      AND i.status='closed' {clause}
                    """,
                    [person_id, start, end, *extra],
                )
                total = base * _legacy_default(
                    person["nurse_procedure_percent"], "35"
                ) / Decimal("100")
                if total:
                    details.append({
                        "code": "nurse_procedure_share", "count": 1,
                        "unit_price": _money(base), "total": _money(total),
                    })
                gross += total

            net = gross - tax
            rows.append({
                "id": person_id,
                "staff_type": person_type,
                "shift_counts": {
                    "morning": counts.get("morning", 0),
                    "evening": counts.get("evening", 0),
                    "night": counts.get("night", 0),
                },
                "details": sorted(details, key=lambda item: item["code"]),
                "gross_salary": _money(gross),
                "tax_amount": _money(tax),
                "net_salary": _money(net),
            })
            total_gross += gross
            total_tax += tax
            total_net += net

        return {
            "summary": {
                "staff_count": len(rows),
                "gross_salary": _money(total_gross),
                "tax_amount": _money(total_tax),
                "net_salary": _money(total_net),
            },
            "rows": rows,
        }
    finally:
        db.close()
