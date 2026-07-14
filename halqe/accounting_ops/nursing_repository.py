"""PostgreSQL adapter for nursing services, consumables and shift staff."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from psycopg import Connection


class NursingRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    # --------------------------------------------------------------- catalogues
    def list_nursing_services(self, *, tenant_id: int) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, service_name, unit_price
            FROM accounting.nursing_services
            WHERE tenant_id=%s AND is_active=TRUE
            ORDER BY service_name, id
            """,
            (tenant_id,),
        ).fetchall()

    def list_consumable_tariffs(
        self, *, tenant_id: int, category: Optional[str] = None
    ) -> list[dict[str, Any]]:
        if category:
            return self.conn.execute(
                """
                SELECT id, name, default_price, category
                FROM accounting.consumable_tariffs
                WHERE tenant_id=%s AND is_active=TRUE AND category=%s
                ORDER BY name, id
                """,
                (tenant_id, category),
            ).fetchall()
        return self.conn.execute(
            """
            SELECT id, name, default_price, category
            FROM accounting.consumable_tariffs
            WHERE tenant_id=%s AND is_active=TRUE
            ORDER BY category, name, id
            """,
            (tenant_id,),
        ).fetchall()

    def get_nursing_service(
        self, *, tenant_id: int, service_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, service_name, unit_price
            FROM accounting.nursing_services
            WHERE tenant_id=%s AND id=%s AND is_active=TRUE
            """,
            (tenant_id, service_id),
        ).fetchone()

    # -------------------------------------------------------------------- staff
    def list_active_staff(
        self, *, tenant_id: int, staff_type: Optional[str] = None
    ) -> list[dict[str, Any]]:
        if staff_type:
            return self.conn.execute(
                """
                SELECT id, full_name, staff_type
                FROM accounting.medical_staff
                WHERE tenant_id=%s AND is_active=TRUE AND staff_type=%s
                ORDER BY full_name, id
                """,
                (tenant_id, staff_type),
            ).fetchall()
        return self.conn.execute(
            """
            SELECT id, full_name, staff_type
            FROM accounting.medical_staff
            WHERE tenant_id=%s AND is_active=TRUE
            ORDER BY staff_type, full_name, id
            """,
            (tenant_id,),
        ).fetchall()

    def get_active_staff_member(
        self,
        *,
        tenant_id: int,
        staff_id: int,
        staff_type: str,
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, full_name, staff_type
            FROM accounting.medical_staff
            WHERE tenant_id=%s AND id=%s AND staff_type=%s AND is_active=TRUE
            """,
            (tenant_id, staff_id, staff_type),
        ).fetchone()

    def get_active_staff(
        self,
        *,
        tenant_id: int,
        staff_id: int,
        staff_type: str,
    ) -> Optional[dict[str, Any]]:
        """Stable singular lookup used by invoice and nursing command services."""
        return self.get_active_staff_member(
            tenant_id=tenant_id,
            staff_id=staff_id,
            staff_type=staff_type,
        )

    def shift_staff(
        self, *, tenant_id: int, work_date, shift: str
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT s.id, s.work_date, s.shift, s.doctor_id, s.nurse_id,
                   d.full_name AS doctor_name, n.full_name AS nurse_name,
                   s.updated_at
            FROM accounting.shift_staff s
            LEFT JOIN accounting.medical_staff d
              ON d.tenant_id=s.tenant_id AND d.id=s.doctor_id
            LEFT JOIN accounting.medical_staff n
              ON n.tenant_id=s.tenant_id AND n.id=s.nurse_id
            WHERE s.tenant_id=%s AND s.work_date=%s AND s.shift=%s
            """,
            (tenant_id, work_date, shift),
        ).fetchone()

    def set_shift_staff(
        self,
        *,
        tenant_id: int,
        work_date,
        shift: str,
        doctor_id: Optional[int],
        nurse_id: Optional[int],
    ) -> dict[str, Any]:
        self.conn.execute(
            """
            INSERT INTO accounting.shift_staff AS s
                (tenant_id, work_date, shift, doctor_id, nurse_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, work_date, shift) DO UPDATE SET
                doctor_id=EXCLUDED.doctor_id,
                nurse_id=EXCLUDED.nurse_id,
                updated_at=now()
            """,
            (tenant_id, work_date, shift, doctor_id, nurse_id),
        )
        return self.shift_staff(
            tenant_id=tenant_id,
            work_date=work_date,
            shift=shift,
        )

    # ------------------------------------------------------------------ invoice
    def invoice_context(
        self, *, tenant_id: int, invoice_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, patient_id, status, pricing_version, insurance_type,
                   supplementary_insurance, work_date, shift, total_amount
            FROM accounting.invoices
            WHERE tenant_id=%s AND id=%s
            FOR UPDATE
            """,
            (tenant_id, invoice_id),
        ).fetchone()

    def nursing_coverage(
        self, *, tenant_id: int, insurance_type: str
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT nursing_covers, nursing_tariff
            FROM accounting.visit_tariffs
            WHERE tenant_id=%s AND insurance_type=%s
              AND is_active=TRUE AND is_supplementary=FALSE
            LIMIT 1
            """,
            (tenant_id, insurance_type),
        ).fetchone()

    def excluded_nursing_service_ids(
        self, *, tenant_id: int, insurance_type: str
    ) -> set[int]:
        rows = self.conn.execute(
            """
            SELECT nursing_service_id
            FROM accounting.insurance_nursing_exclusions
            WHERE tenant_id=%s AND insurance_type=%s
            """,
            (tenant_id, insurance_type),
        ).fetchall()
        return {int(row["nursing_service_id"]) for row in rows}

    def create_injection(
        self,
        *,
        tenant_id: int,
        patient_id: int,
        invoice_id: int,
        service_id: int,
        service_name: str,
        unit_price: int,
        patient_amount: int,
        insurance_amount: int,
        covered_by_insurance: bool,
        work_date,
        shift: str,
        reception_user: str,
        notes: Optional[str],
        doctor_id: Optional[int],
        nurse_id: Optional[int],
    ) -> int:
        row = self.conn.execute(
            """
            INSERT INTO accounting.injections
                (tenant_id, patient_id, injection_type, service_id,
                 shift, work_date, count, unit_price, total_price,
                 patient_amount, insurance_amount, covered_by_insurance,
                 reception_user, notes, invoice_id, doctor_id, nurse_id)
            VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                patient_id,
                service_name,
                service_id,
                shift,
                work_date,
                unit_price,
                unit_price,
                patient_amount,
                insurance_amount,
                covered_by_insurance,
                reception_user,
                notes,
                invoice_id,
                doctor_id,
                nurse_id,
            ),
        ).fetchone()
        return int(row["id"])

    def create_consumable(
        self,
        *,
        tenant_id: int,
        patient_id: int,
        invoice_id: int,
        item_name: str,
        category: str,
        quantity: Decimal,
        unit_price: int,
        total_cost: int,
        patient_provided: bool,
        is_exception: bool,
        work_date,
        shift: str,
        reception_user: str,
        notes: Optional[str],
        doctor_id: Optional[int],
        nurse_id: Optional[int],
    ) -> int:
        row = self.conn.execute(
            """
            INSERT INTO accounting.consumables_ledger
                (tenant_id, patient_id, item_name, category, quantity,
                 unit_price, total_cost, patient_provided, is_exception,
                 shift, work_date, reception_user, notes, invoice_id,
                 doctor_id, nurse_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                patient_id,
                item_name,
                category,
                quantity,
                unit_price,
                total_cost,
                patient_provided,
                is_exception,
                shift,
                work_date,
                reception_user,
                notes,
                invoice_id,
                doctor_id,
                nurse_id,
            ),
        ).fetchone()
        return int(row["id"])

    def update_invoice_total_and_version(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        total_amount: int,
        pricing_version: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE accounting.invoices
               SET total_amount=%s, pricing_version=%s
             WHERE tenant_id=%s AND id=%s AND status='open'
            """,
            (total_amount, pricing_version, tenant_id, invoice_id),
        )
