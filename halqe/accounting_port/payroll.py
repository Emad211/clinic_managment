"""Read-only payroll calculator preserving the Flask accounting oracle."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from django.db import connections, transaction


def _decimal(value: Any, default: str = "0") -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal(default)


def _legacy_default(value: Any, default: str) -> Decimal:
    """Mirror ``legacy_value or default`` including zero selecting the default."""
    number = _decimal(value)
    return number if number != 0 else Decimal(default)


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.001")))


class AccountingPayrollRepository:
    def __init__(self, cursor, *, tenant_id: int):
        self.cursor = cursor
        self.tenant_id = tenant_id

    @classmethod
    def calculate_read_only(
        cls,
        *,
        tenant_id: int,
        date_from: date,
        date_to: date,
        staff_id: Optional[int] = None,
        staff_type: Optional[str] = None,
        shift: Optional[str] = None,
    ) -> dict[str, Any]:
        with transaction.atomic(using="accounting_read"):
            with connections["accounting_read"].cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, true)",
                    [str(tenant_id)],
                )
                return cls(cursor, tenant_id=tenant_id).calculate(
                    date_from=date_from,
                    date_to=date_to,
                    staff_id=staff_id,
                    staff_type=staff_type,
                    shift=shift,
                )

    def _scalar(self, query: str, params: list[Any]) -> Decimal:
        self.cursor.execute(query, params)
        row = self.cursor.fetchone()
        return _decimal(row[0] if row else 0)

    def _staff(
        self, *, staff_id: Optional[int], staff_type: Optional[str]
    ) -> list[dict[str, Any]]:
        clauses = ["m.tenant_id=%s", "m.is_active=TRUE"]
        params: list[Any] = [self.tenant_id]
        if staff_id:
            clauses.append("m.id=%s")
            params.append(staff_id)
        if staff_type:
            clauses.append("m.staff_type=%s")
            params.append(staff_type)
        self.cursor.execute(
            f"""
            SELECT m.id, m.full_name, m.staff_type,
                   ps.base_morning, ps.base_evening, ps.base_night,
                   ps.visit_fee, ps.injection_percent, ps.procedure_percent,
                   ps.tax_percent, ps.nursing_percent,
                   ps.nurse_procedure_percent
            FROM accounting.medical_staff m
            LEFT JOIN accounting.payroll_settings ps
              ON ps.tenant_id=m.tenant_id AND ps.staff_id=m.id
            WHERE {' AND '.join(clauses)}
            ORDER BY m.staff_type, m.full_name, m.id
            """,
            params,
        )
        columns = [column[0] for column in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def _shift_counts(
        self,
        *,
        person_id: int,
        person_type: str,
        date_from: date,
        date_to: date,
        shift: Optional[str],
    ) -> dict[str, int]:
        shift_clause = " AND actual.shift=%s" if shift else ""
        params: list[Any]
        if person_type == "doctor":
            query = f"""
                SELECT actual.shift, COUNT(*)::bigint
                FROM (
                    SELECT DISTINCT v.work_date, v.shift
                    FROM accounting.visits v
                    WHERE v.tenant_id=%s AND v.doctor_id=%s
                      AND v.work_date BETWEEN %s AND %s
                ) actual
                WHERE actual.shift IS NOT NULL {shift_clause}
                GROUP BY actual.shift
            """
            params = [self.tenant_id, person_id, date_from, date_to]
        else:
            query = f"""
                SELECT actual.shift, COUNT(*)::bigint
                FROM (
                    SELECT DISTINCT v.work_date, v.shift
                    FROM accounting.visits v
                    JOIN accounting.invoices inv
                      ON inv.tenant_id=v.tenant_id AND inv.id=v.invoice_id
                    WHERE v.tenant_id=%s AND v.work_date BETWEEN %s AND %s
                      AND (
                        EXISTS (
                          SELECT 1 FROM accounting.injections n
                          WHERE n.tenant_id=v.tenant_id
                            AND n.invoice_id=inv.id AND n.nurse_id=%s
                        ) OR EXISTS (
                          SELECT 1 FROM accounting.procedures p
                          WHERE p.tenant_id=v.tenant_id
                            AND p.invoice_id=inv.id AND p.nurse_id=%s
                        )
                      )
                ) actual
                WHERE actual.shift IS NOT NULL {shift_clause}
                GROUP BY actual.shift
            """
            params = [self.tenant_id, date_from, date_to, person_id, person_id]
        if shift:
            params.append(shift)
        self.cursor.execute(query, params)
        return {str(row[0]): int(row[1]) for row in self.cursor.fetchall()}

    def calculate(
        self,
        *,
        date_from: date,
        date_to: date,
        staff_id: Optional[int],
        staff_type: Optional[str],
        shift: Optional[str],
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        total_gross = Decimal("0")
        total_tax = Decimal("0")
        total_net = Decimal("0")
        shift_sql = " AND {alias}.shift=%s" if shift else ""

        for person in self._staff(staff_id=staff_id, staff_type=staff_type):
            person_id = int(person["id"])
            person_type = str(person["staff_type"])
            details: list[dict[str, Any]] = []
            gross = Decimal("0")
            tax = Decimal("0")

            counts = self._shift_counts(
                person_id=person_id,
                person_type=person_type,
                date_from=date_from,
                date_to=date_to,
                shift=shift,
            )
            base_by_shift = {
                "morning": _decimal(person.get("base_morning")),
                "evening": _decimal(person.get("base_evening")),
                "night": _decimal(person.get("base_night")),
            }
            labels = {"morning": "شیفت صبح", "evening": "شیفت عصر", "night": "شیفت شب"}
            for key in ("morning", "evening", "night"):
                count = counts.get(key, 0)
                amount = base_by_shift[key] * count
                if count:
                    details.append({
                        "code": f"shift_{key}", "label": labels[key],
                        "count": count, "unit_price": _money(base_by_shift[key]),
                        "total": _money(amount),
                    })
                gross += amount

            if person_type == "doctor":
                visit_fee = _legacy_default(person.get("visit_fee"), "20000")
                params: list[Any] = [self.tenant_id, person_id, date_from, date_to]
                extra = shift_sql.format(alias="v")
                if shift:
                    params.append(shift)
                visits = self._scalar(
                    f"""
                    SELECT COUNT(*)::numeric
                    FROM accounting.visits v
                    JOIN accounting.invoices i
                      ON i.tenant_id=v.tenant_id AND i.id=v.invoice_id
                    WHERE v.tenant_id=%s AND v.doctor_id=%s
                      AND v.work_date BETWEEN %s AND %s
                      AND i.status='closed' {extra}
                    """,
                    params,
                )
                visit_total = visits * visit_fee
                if visits:
                    details.append({
                        "code": "visits", "label": "ویزیت",
                        "count": int(visits), "unit_price": _money(visit_fee),
                        "total": _money(visit_total),
                    })
                gross += visit_total

                injection_percent = _legacy_default(person.get("injection_percent"), "30")
                params = [self.tenant_id, person_id, date_from, date_to]
                extra = shift_sql.format(alias="n")
                if shift:
                    params.append(shift)
                injection_base = self._scalar(
                    f"""
                    SELECT COALESCE(SUM(n.total_price),0)::numeric
                    FROM accounting.injections n
                    JOIN accounting.invoices i
                      ON i.tenant_id=n.tenant_id AND i.id=n.invoice_id
                    WHERE n.tenant_id=%s AND n.doctor_id=%s
                      AND n.work_date BETWEEN %s AND %s AND i.status='closed'
                      AND EXISTS (
                        SELECT 1 FROM accounting.visits v
                        WHERE v.tenant_id=n.tenant_id AND v.invoice_id=n.invoice_id
                          AND v.doctor_id=n.doctor_id
                      ) {extra}
                    """,
                    params,
                )
                injection_total = injection_base * injection_percent / Decimal("100")
                if injection_total:
                    details.append({
                        "code": "doctor_nursing_share",
                        "label": f"سهم تزریقات ({_money(injection_percent)}٪)",
                        "count": 1, "unit_price": _money(injection_base),
                        "total": _money(injection_total),
                    })
                gross += injection_total

                procedure_percent = _legacy_default(person.get("procedure_percent"), "40")
                params = [self.tenant_id, person_id, date_from, date_to]
                extra = shift_sql.format(alias="p")
                if shift:
                    params.append(shift)
                procedure_base = self._scalar(
                    f"""
                    SELECT COALESCE(SUM(p.price),0)::numeric
                    FROM accounting.procedures p
                    JOIN accounting.invoices i
                      ON i.tenant_id=p.tenant_id AND i.id=p.invoice_id
                    WHERE p.tenant_id=%s AND p.doctor_id=%s
                      AND p.work_date BETWEEN %s AND %s AND i.status='closed' {extra}
                    """,
                    params,
                )
                procedure_total = procedure_base * procedure_percent / Decimal("100")
                if procedure_total:
                    details.append({
                        "code": "doctor_procedure_share",
                        "label": f"سهم کار عملی ({_money(procedure_percent)}٪)",
                        "count": 1, "unit_price": _money(procedure_base),
                        "total": _money(procedure_total),
                    })
                gross += procedure_total

                tax_percent = _legacy_default(person.get("tax_percent"), "10")
                tax = gross * tax_percent / Decimal("100")
                details.append({
                    "code": "tax", "label": f"کسر مالیات ({_money(tax_percent)}٪)",
                    "count": 1, "unit_price": _money(gross), "total": -_money(tax),
                })
            else:
                nursing_percent = _legacy_default(person.get("nursing_percent"), "6")
                params = [self.tenant_id, person_id, date_from, date_to]
                extra = shift_sql.format(alias="n")
                if shift:
                    params.append(shift)
                nursing_base = self._scalar(
                    f"""
                    SELECT COALESCE(SUM(n.total_price),0)::numeric
                    FROM accounting.injections n
                    JOIN accounting.invoices i
                      ON i.tenant_id=n.tenant_id AND i.id=n.invoice_id
                    WHERE n.tenant_id=%s AND n.nurse_id=%s
                      AND n.work_date BETWEEN %s AND %s AND i.status='closed' {extra}
                    """,
                    params,
                )
                nursing_total = nursing_base * nursing_percent / Decimal("100")
                if nursing_total:
                    details.append({
                        "code": "nurse_nursing_share",
                        "label": f"سهم خدمات پرستاری ({_money(nursing_percent)}٪)",
                        "count": 1, "unit_price": _money(nursing_base),
                        "total": _money(nursing_total),
                    })
                gross += nursing_total

                procedure_percent = _legacy_default(person.get("nurse_procedure_percent"), "35")
                params = [self.tenant_id, person_id, date_from, date_to]
                extra = shift_sql.format(alias="p")
                if shift:
                    params.append(shift)
                procedure_base = self._scalar(
                    f"""
                    SELECT COALESCE(SUM(p.price),0)::numeric
                    FROM accounting.procedures p
                    JOIN accounting.invoices i
                      ON i.tenant_id=p.tenant_id AND i.id=p.invoice_id
                    WHERE p.tenant_id=%s AND p.nurse_id=%s
                      AND p.work_date BETWEEN %s AND %s AND i.status='closed' {extra}
                    """,
                    params,
                )
                procedure_total = procedure_base * procedure_percent / Decimal("100")
                if procedure_total:
                    details.append({
                        "code": "nurse_procedure_share",
                        "label": f"سهم کار عملی پرستار ({_money(procedure_percent)}٪)",
                        "count": 1, "unit_price": _money(procedure_base),
                        "total": _money(procedure_total),
                    })
                gross += procedure_total

            net = gross - tax
            results.append({
                "id": person_id,
                "name": person["full_name"],
                "staff_type": person_type,
                "type_label": "پزشک" if person_type == "doctor" else "پرستار",
                "shift_counts": {
                    "morning": counts.get("morning", 0),
                    "evening": counts.get("evening", 0),
                    "night": counts.get("night", 0),
                },
                "details": details,
                "gross_salary": _money(gross),
                "tax_amount": _money(tax),
                "net_salary": _money(net),
            })
            total_gross += gross
            total_tax += tax
            total_net += net

        return {
            "date_from": date_from,
            "date_to": date_to,
            "summary": {
                "staff_count": len(results),
                "gross_salary": _money(total_gross),
                "tax_amount": _money(total_tax),
                "net_salary": _money(total_net),
            },
            "rows": results,
        }
