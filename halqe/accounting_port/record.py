"""Read-only accounting visit-history projection for the clinical record.

This module is part of the ``accounting_port`` boundary.  It always uses the
SELECT-only ``accounting_read`` alias and returns DTOs rather than ORM rows.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from django.db import connections
from pydantic import BaseModel


class AccountingVisitHistoryDTO(BaseModel):
    visit_id: int
    invoice_id: Optional[int] = None
    visit_date: datetime
    work_date: Optional[date] = None
    doctor_name: Optional[str] = None
    price: int
    status: Optional[str] = None


def get_patient_visit_history(
    *,
    accounting_patient_id: int,
    tenant_id: int,
    limit: int = 100,
) -> list[AccountingVisitHistoryDTO]:
    """Return newest accounting visit rows for one patient and tenant."""
    safe_limit = max(1, min(int(limit), 500))
    with connections["accounting_read"].cursor() as cursor:
        cursor.execute(
            """
            SELECT v.id, v.invoice_id, v.visit_date, v.work_date,
                   v.doctor_name, v.price, v.status
            FROM accounting.visits v
            WHERE v.tenant_id = %s
              AND v.patient_id = %s
            ORDER BY v.visit_date DESC, v.id DESC
            LIMIT %s
            """,
            [int(tenant_id), int(accounting_patient_id), safe_limit],
        )
        return [
            AccountingVisitHistoryDTO(
                visit_id=int(row[0]),
                invoice_id=int(row[1]) if row[1] is not None else None,
                visit_date=row[2],
                work_date=row[3],
                doctor_name=row[4],
                price=int(row[5] or 0),
                status=row[6],
            )
            for row in cursor.fetchall()
        ]
