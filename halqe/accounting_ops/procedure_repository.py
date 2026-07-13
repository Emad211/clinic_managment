"""PostgreSQL adapter for procedure catalogues and financial snapshots."""
from __future__ import annotations

from typing import Any, Optional

from psycopg import Connection


class ProcedureRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    def list_tariffs(self, *, tenant_id: int) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, name, unit_price
            FROM accounting.procedure_tariffs
            WHERE tenant_id=%s AND is_active=TRUE
            ORDER BY name, id
            """,
            (tenant_id,),
        ).fetchall()

    def get_tariff(
        self, *, tenant_id: int, tariff_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, name, unit_price
            FROM accounting.procedure_tariffs
            WHERE tenant_id=%s AND id=%s AND is_active=TRUE
            """,
            (tenant_id, tariff_id),
        ).fetchone()

    def create_procedure(
        self,
        *,
        tenant_id: int,
        patient_id: int,
        invoice_id: int,
        procedure_type: str,
        price: int,
        patient_amount: int,
        insurance_amount: int,
        covered_by_insurance: bool,
        performer_type: str,
        performer_id: int,
        work_date,
        shift: str,
        reception_user: str,
        notes: Optional[str],
        doctor_id: Optional[int],
        nurse_id: Optional[int],
    ) -> int:
        row = self.conn.execute(
            """
            INSERT INTO accounting.procedures
                (tenant_id, patient_id, procedure_type, shift, work_date,
                 price, patient_amount, insurance_amount, covered_by_insurance,
                 reception_user, notes, invoice_id, performer_type,
                 performer_id, doctor_id, nurse_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                patient_id,
                procedure_type,
                shift,
                work_date,
                price,
                patient_amount,
                insurance_amount,
                covered_by_insurance,
                reception_user,
                notes,
                invoice_id,
                performer_type,
                performer_id,
                doctor_id,
                nurse_id,
            ),
        ).fetchone()
        return int(row["id"])
