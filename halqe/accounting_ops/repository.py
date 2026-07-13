"""PostgreSQL adapter for the accounting write-side.

Only this module contains accounting write SQL. The application service owns
validation and orchestration; this repository owns persistence and projections.
Every query is explicitly tenant-scoped even though accounting RLS is deferred
until the second-clinic (T1) gate.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from psycopg import Connection


_PATIENT_COLUMNS = """
    id, uuid, name, family_name, full_name, national_id,
    phone_number, birthdate, gender, insurance_type,
    insurance_expiry, address, is_foreign
"""


class AccountingRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    # ------------------------------------------------------------------ patient
    def find_patient_by_national_id_for_update(
        self, *, tenant_id: int, national_id: str
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            f"""
            SELECT {_PATIENT_COLUMNS}
            FROM accounting.patients
            WHERE tenant_id = %s AND national_id = %s
            FOR UPDATE
            """,
            (tenant_id, national_id),
        ).fetchone()

    def find_patient_by_name_phone_for_update(
        self,
        *,
        tenant_id: int,
        name: str,
        family_name: str,
        phone_number: str,
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            f"""
            SELECT {_PATIENT_COLUMNS}
            FROM accounting.patients
            WHERE tenant_id = %s
              AND name = %s
              AND family_name = %s
              AND phone_number = %s
            ORDER BY id
            LIMIT 1
            FOR UPDATE
            """,
            (tenant_id, name, family_name, phone_number),
        ).fetchone()

    def update_patient(
        self,
        *,
        tenant_id: int,
        patient_id: int,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.conn.execute(
            f"""
            UPDATE accounting.patients
               SET name = %s,
                   family_name = %s,
                   phone_number = %s,
                   birthdate = COALESCE(%s, birthdate),
                   gender = COALESCE(%s, gender),
                   insurance_type = COALESCE(%s, insurance_type),
                   insurance_expiry = COALESCE(%s, insurance_expiry),
                   address = COALESCE(%s, address),
                   is_foreign = %s,
                   updated_at = now()
             WHERE tenant_id = %s AND id = %s
            RETURNING {_PATIENT_COLUMNS}
            """,
            (
                data["name"],
                data["family_name"],
                data["phone_number"],
                data["birthdate"],
                data["gender"],
                data["insurance_type"],
                data["insurance_expiry"],
                data["address"],
                data["is_foreign"],
                tenant_id,
                patient_id,
            ),
        ).fetchone()

    def create_patient(
        self,
        *,
        tenant_id: int,
        data: Mapping[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        return self.conn.execute(
            f"""
            INSERT INTO accounting.patients
                (tenant_id, name, family_name, national_id, phone_number,
                 birthdate, gender, insurance_type, insurance_expiry,
                 address, is_foreign, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_PATIENT_COLUMNS}
            """,
            (
                tenant_id,
                data["name"],
                data["family_name"],
                data["national_id"],
                data["phone_number"],
                data["birthdate"],
                data["gender"],
                data["insurance_type"],
                data["insurance_expiry"],
                data["address"],
                data["is_foreign"],
                created_by,
            ),
        ).fetchone()

    def search_patients(
        self, *, tenant_id: int, query: str, limit: int
    ) -> list[dict[str, Any]]:
        if query:
            like = f"%{query}%"
            return self.conn.execute(
                f"""
                SELECT {_PATIENT_COLUMNS}
                FROM accounting.patients
                WHERE tenant_id = %s
                  AND (
                    full_name ILIKE %s
                    OR COALESCE(national_id, '') ILIKE %s
                    OR COALESCE(phone_number, '') ILIKE %s
                  )
                ORDER BY id DESC
                LIMIT %s
                """,
                (tenant_id, like, like, like, limit),
            ).fetchall()
        return self.conn.execute(
            f"""
            SELECT {_PATIENT_COLUMNS}
            FROM accounting.patients
            WHERE tenant_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (tenant_id, limit),
        ).fetchall()

    # ------------------------------------------------------------------ tariffs
    def get_visit_tariff(
        self,
        *,
        tenant_id: int,
        insurance_type: str,
        is_supplementary: bool,
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, insurance_type, tariff_price
            FROM accounting.visit_tariffs
            WHERE tenant_id = %s
              AND insurance_type = %s
              AND is_active = TRUE
              AND is_supplementary = %s
            LIMIT 1
            """,
            (tenant_id, insurance_type, is_supplementary),
        ).fetchone()

    def list_visit_tariffs(self, *, tenant_id: int) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, insurance_type, tariff_price, is_supplementary,
                   is_base_tariff, nursing_covers, nursing_tariff
            FROM accounting.visit_tariffs
            WHERE tenant_id = %s AND is_active = TRUE
            ORDER BY is_supplementary, insurance_type
            """,
            (tenant_id,),
        ).fetchall()

    # -------------------------------------------------------------------- staff
    def get_active_doctor(
        self, *, tenant_id: int, doctor_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, full_name
            FROM accounting.medical_staff
            WHERE tenant_id = %s
              AND id = %s
              AND staff_type = 'doctor'
              AND is_active = TRUE
            """,
            (tenant_id, doctor_id),
        ).fetchone()

    # ------------------------------------------------------------------ invoice
    def create_invoice(
        self,
        *,
        tenant_id: int,
        patient_id: int,
        doctor_id: Optional[int],
        insurance_type: str,
        supplementary_insurance: Optional[str],
        total_amount: int,
        work_date,
        shift: str,
        opened_by: str,
        opened_by_name: str,
        pricing_version: str,
    ) -> int:
        row = self.conn.execute(
            """
            INSERT INTO accounting.invoices
                (tenant_id, patient_id, doctor_id, status, insurance_type,
                 supplementary_insurance, total_amount, work_date, shift,
                 opened_by, opened_by_name, pricing_version)
            VALUES (%s, %s, %s, 'open', %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                patient_id,
                doctor_id,
                insurance_type,
                supplementary_insurance,
                total_amount,
                work_date,
                shift,
                opened_by,
                opened_by_name,
                pricing_version,
            ),
        ).fetchone()
        return int(row["id"])

    def create_visit(
        self,
        *,
        tenant_id: int,
        patient_id: int,
        doctor_id: Optional[int],
        doctor_name: Optional[str],
        invoice_id: int,
        insurance_type: str,
        supplementary_insurance: Optional[str],
        price: int,
        work_date,
        shift: str,
        reception_user: str,
        notes: Optional[str],
    ) -> int:
        row = self.conn.execute(
            """
            INSERT INTO accounting.visits
                (tenant_id, patient_id, doctor_name, shift, work_date,
                 insurance_type, supplementary_insurance, status, price,
                 payment_status, reception_user, notes, invoice_id, doctor_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s,
                    'unpaid', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                patient_id,
                doctor_name,
                shift,
                work_date,
                insurance_type,
                supplementary_insurance,
                price,
                reception_user,
                notes,
                invoice_id,
                doctor_id,
            ),
        ).fetchone()
        return int(row["id"])

    def lock_invoice(
        self, *, tenant_id: int, invoice_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, patient_id, status, pricing_version
            FROM accounting.invoices
            WHERE tenant_id = %s AND id = %s
            FOR UPDATE
            """,
            (tenant_id, invoice_id),
        ).fetchone()

    def unsupported_item_counts(
        self, *, tenant_id: int, invoice_id: int
    ) -> dict[str, int]:
        row = self.conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM accounting.injections i
                WHERE i.tenant_id=%s AND i.invoice_id=%s) AS injections,
              (SELECT COUNT(*) FROM accounting.procedures p
                WHERE p.tenant_id=%s AND p.invoice_id=%s) AS procedures,
              (SELECT COUNT(*) FROM accounting.consumables_ledger c
                WHERE c.tenant_id=%s AND c.invoice_id=%s) AS consumables
            """,
            (
                tenant_id,
                invoice_id,
                tenant_id,
                invoice_id,
                tenant_id,
                invoice_id,
            ),
        ).fetchone()
        return {
            key: int(row[key])
            for key in ("injections", "procedures", "consumables")
        }

    def visit_patient_total(self, *, tenant_id: int, invoice_id: int) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(price), 0) AS total
            FROM accounting.visits
            WHERE tenant_id = %s AND invoice_id = %s
            """,
            (tenant_id, invoice_id),
        ).fetchone()
        return int(row["total"] or 0)

    def mark_invoice_closed(
        self,
        *,
        tenant_id: int,
        invoice_id: int,
        total_amount: int,
        closed_by: str,
        closed_by_name: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE accounting.invoices
               SET total_amount = %s,
                   status = 'closed',
                   closed_at = now(),
                   closed_by = %s,
                   closed_by_name = %s
             WHERE tenant_id = %s AND id = %s
            """,
            (total_amount, closed_by, closed_by_name, tenant_id, invoice_id),
        )

    def count_open_invoices(self, *, tenant_id: int) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM accounting.invoices
            WHERE tenant_id = %s AND status = 'open'
            """,
            (tenant_id,),
        ).fetchone()
        return int(row["c"])

    def list_open_invoices(
        self, *, tenant_id: int, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT i.id, i.tenant_id, i.patient_id, i.status, i.pricing_version,
                   i.insurance_type, i.supplementary_insurance,
                   i.total_amount, i.work_date, i.shift,
                   i.opened_at, i.closed_at, i.opened_by, i.opened_by_name,
                   i.closed_by, i.closed_by_name,
                   p.uuid AS patient_uuid, p.full_name AS patient_full_name,
                   p.national_id, p.phone_number,
                   (
                       SELECT v.id
                       FROM accounting.visits v
                       WHERE v.tenant_id = i.tenant_id AND v.invoice_id = i.id
                       ORDER BY v.id LIMIT 1
                   ) AS visit_id,
                   (
                       SELECT v.price
                       FROM accounting.visits v
                       WHERE v.tenant_id = i.tenant_id AND v.invoice_id = i.id
                       ORDER BY v.id LIMIT 1
                   ) AS visit_price
            FROM accounting.invoices i
            JOIN accounting.patients p
              ON p.tenant_id = i.tenant_id AND p.id = i.patient_id
            WHERE i.tenant_id = %s AND i.status = 'open'
            ORDER BY i.opened_at DESC, i.id DESC
            LIMIT %s OFFSET %s
            """,
            (tenant_id, limit, offset),
        ).fetchall()

    def invoice_projection(
        self, *, tenant_id: int, invoice_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT i.id, i.tenant_id, i.patient_id, i.status, i.pricing_version,
                   i.insurance_type, i.supplementary_insurance,
                   i.total_amount, i.work_date, i.shift,
                   i.opened_at, i.closed_at, i.opened_by, i.opened_by_name,
                   i.closed_by, i.closed_by_name,
                   p.uuid AS patient_uuid, p.full_name AS patient_full_name,
                   p.national_id, p.phone_number,
                   (
                       SELECT v.id
                       FROM accounting.visits v
                       WHERE v.tenant_id = i.tenant_id AND v.invoice_id = i.id
                       ORDER BY v.id LIMIT 1
                   ) AS visit_id,
                   (
                       SELECT v.price
                       FROM accounting.visits v
                       WHERE v.tenant_id = i.tenant_id AND v.invoice_id = i.id
                       ORDER BY v.id LIMIT 1
                   ) AS visit_price
            FROM accounting.invoices i
            JOIN accounting.patients p
              ON p.tenant_id = i.tenant_id AND p.id = i.patient_id
            WHERE i.tenant_id = %s AND i.id = %s
            """,
            (tenant_id, invoice_id),
        ).fetchone()

    def patient_for_invoice(
        self, *, tenant_id: int, invoice_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT p.id, p.full_name
            FROM accounting.patients p
            JOIN accounting.invoices i
              ON i.tenant_id = p.tenant_id AND i.patient_id = p.id
            WHERE i.tenant_id = %s AND i.id = %s
            """,
            (tenant_id, invoice_id),
        ).fetchone()

    # --------------------------------------------------------------------- audit
    def log_activity(
        self,
        *,
        tenant_id: int,
        user_id: Optional[int],
        username: str,
        action_type: str,
        description: str,
        invoice_id: Optional[int],
        patient_id: Optional[int],
        patient_name: Optional[str],
        amount: int,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO accounting.activity_logs
                (tenant_id, user_id, username, action_type, action_category,
                 description, target_type, target_id, invoice_id, patient_id,
                 patient_name, amount, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, 'invoice', %s, 'invoice', %s,
                    %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                user_id,
                username,
                action_type,
                description,
                invoice_id,
                invoice_id,
                patient_id,
                patient_name,
                amount,
                ip_address,
                user_agent,
            ),
        )
