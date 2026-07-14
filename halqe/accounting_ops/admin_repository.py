"""Persistence adapter for manager-owned accounting configuration.

All queries run through the dedicated accounting writer connection and require
an explicit tenant id. Catalog rows are never hard-deleted; deactivation keeps
historical invoice snapshots interpretable. Only exclusion rows are deleted,
because they are pure current-policy mappings rather than billed facts.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from psycopg import Connection, sql


_CATALOGS = {
    "nursing": {
        "table": "nursing_services",
        "name": "service_name",
        "price": "unit_price",
    },
    "procedure": {
        "table": "procedure_tariffs",
        "name": "name",
        "price": "unit_price",
    },
    "consumable": {
        "table": "consumable_tariffs",
        "name": "name",
        "price": "default_price",
    },
}


class AccountingAdminRepository:
    def __init__(self, conn: Connection):
        self.conn = conn

    # ------------------------------------------------------------------ reads
    def configuration(self, *, tenant_id: int) -> dict[str, Any]:
        staff = self.conn.execute(
            """
            SELECT id, full_name, staff_type, is_active, created_at
            FROM accounting.medical_staff
            WHERE tenant_id=%s
            ORDER BY is_active DESC, staff_type, full_name, id
            """,
            (tenant_id,),
        ).fetchall()
        schemes = self.conn.execute(
            """
            SELECT id, code, name, is_supplementary, is_base, is_active, created_at
            FROM accounting.insurance_schemes
            WHERE tenant_id=%s
            ORDER BY is_active DESC, is_base DESC, is_supplementary, name, id
            """,
            (tenant_id,),
        ).fetchall()
        tariffs = self.conn.execute(
            """
            SELECT id, insurance_type, insurance_scheme_id, tariff_price,
                   nursing_tariff, nursing_covers, is_active,
                   is_supplementary, is_base_tariff, created_at, updated_at
            FROM accounting.visit_tariffs
            WHERE tenant_id=%s
            ORDER BY is_active DESC, is_base_tariff DESC,
                     is_supplementary, insurance_type, id
            """,
            (tenant_id,),
        ).fetchall()
        nursing = self.conn.execute(
            """
            SELECT id, service_name AS name, unit_price AS price,
                   is_active, created_at
            FROM accounting.nursing_services
            WHERE tenant_id=%s
            ORDER BY is_active DESC, service_name, id
            """,
            (tenant_id,),
        ).fetchall()
        procedures = self.conn.execute(
            """
            SELECT id, name, unit_price AS price, is_active, created_at
            FROM accounting.procedure_tariffs
            WHERE tenant_id=%s
            ORDER BY is_active DESC, name, id
            """,
            (tenant_id,),
        ).fetchall()
        consumables = self.conn.execute(
            """
            SELECT id, name, default_price AS price, category,
                   is_active, created_at
            FROM accounting.consumable_tariffs
            WHERE tenant_id=%s
            ORDER BY is_active DESC, category, name, id
            """,
            (tenant_id,),
        ).fetchall()
        exclusions = self.conn.execute(
            """
            SELECT e.id, e.insurance_type, e.nursing_service_id,
                   n.service_name, e.note, e.created_at
            FROM accounting.insurance_nursing_exclusions e
            JOIN accounting.nursing_services n
              ON n.tenant_id=e.tenant_id AND n.id=e.nursing_service_id
            WHERE e.tenant_id=%s
            ORDER BY e.insurance_type, n.service_name, e.id
            """,
            (tenant_id,),
        ).fetchall()
        payroll = self.conn.execute(
            """
            SELECT p.id, p.staff_id, s.full_name AS staff_name,
                   s.staff_type, p.base_morning, p.base_evening, p.base_night,
                   p.visit_fee, p.injection_percent, p.procedure_percent,
                   p.tax_percent, p.nursing_percent,
                   p.nurse_procedure_percent, p.updated_at
            FROM accounting.payroll_settings p
            JOIN accounting.medical_staff s
              ON s.tenant_id=p.tenant_id AND s.id=p.staff_id
            WHERE p.tenant_id=%s
            ORDER BY s.staff_type, s.full_name, p.id
            """,
            (tenant_id,),
        ).fetchall()
        return {
            "staff": staff,
            "insurance_schemes": schemes,
            "visit_tariffs": tariffs,
            "catalogs": {
                "nursing": nursing,
                "procedure": procedures,
                "consumable": consumables,
            },
            "exclusions": exclusions,
            "payroll_settings": payroll,
        }

    def active_staff(
        self, *, tenant_id: int, staff_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, full_name, staff_type, is_active
            FROM accounting.medical_staff
            WHERE tenant_id=%s AND id=%s
            """,
            (tenant_id, staff_id),
        ).fetchone()

    def nursing_service(
        self, *, tenant_id: int, service_id: int
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, service_name, is_active
            FROM accounting.nursing_services
            WHERE tenant_id=%s AND id=%s
            """,
            (tenant_id, service_id),
        ).fetchone()

    def visit_tariff_by_name(
        self, *, tenant_id: int, insurance_type: str
    ) -> Optional[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, insurance_type, is_active
            FROM accounting.visit_tariffs
            WHERE tenant_id=%s AND insurance_type=%s
            """,
            (tenant_id, insurance_type),
        ).fetchone()

    # ---------------------------------------------------------------- writes
    def upsert_staff(
        self,
        *,
        tenant_id: int,
        staff_id: Optional[int],
        full_name: str,
        staff_type: str,
        is_active: bool,
    ) -> dict[str, Any]:
        if staff_id is None:
            return self.conn.execute(
                """
                INSERT INTO accounting.medical_staff
                    (tenant_id, full_name, staff_type, is_active)
                VALUES (%s, %s, %s, %s)
                RETURNING id, full_name, staff_type, is_active, created_at
                """,
                (tenant_id, full_name, staff_type, is_active),
            ).fetchone()
        return self.conn.execute(
            """
            UPDATE accounting.medical_staff
               SET full_name=%s, staff_type=%s, is_active=%s
             WHERE tenant_id=%s AND id=%s
            RETURNING id, full_name, staff_type, is_active, created_at
            """,
            (full_name, staff_type, is_active, tenant_id, staff_id),
        ).fetchone()

    def upsert_insurance_scheme(
        self,
        *,
        tenant_id: int,
        scheme_id: Optional[int],
        code: str,
        name: str,
        is_supplementary: bool,
        is_base: bool,
        is_active: bool,
    ) -> dict[str, Any]:
        if scheme_id is None:
            return self.conn.execute(
                """
                INSERT INTO accounting.insurance_schemes AS s
                    (tenant_id, code, name, is_supplementary, is_base, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO UPDATE SET
                    name=EXCLUDED.name,
                    is_supplementary=EXCLUDED.is_supplementary,
                    is_base=EXCLUDED.is_base,
                    is_active=EXCLUDED.is_active
                RETURNING id, code, name, is_supplementary, is_base,
                          is_active, created_at
                """,
                (
                    tenant_id,
                    code,
                    name,
                    is_supplementary,
                    is_base,
                    is_active,
                ),
            ).fetchone()
        return self.conn.execute(
            """
            UPDATE accounting.insurance_schemes
               SET code=%s, name=%s, is_supplementary=%s,
                   is_base=%s, is_active=%s
             WHERE tenant_id=%s AND id=%s
            RETURNING id, code, name, is_supplementary, is_base,
                      is_active, created_at
            """,
            (
                code,
                name,
                is_supplementary,
                is_base,
                is_active,
                tenant_id,
                scheme_id,
            ),
        ).fetchone()

    def upsert_visit_tariff(
        self,
        *,
        tenant_id: int,
        tariff_id: Optional[int],
        insurance_type: str,
        insurance_scheme_id: Optional[int],
        tariff_price: int,
        nursing_tariff: int,
        nursing_covers: bool,
        is_active: bool,
        is_supplementary: bool,
        is_base_tariff: bool,
    ) -> dict[str, Any]:
        if tariff_id is None:
            return self.conn.execute(
                """
                INSERT INTO accounting.visit_tariffs AS t
                    (tenant_id, insurance_type, insurance_scheme_id,
                     tariff_price, nursing_tariff, nursing_covers,
                     is_active, is_supplementary, is_base_tariff)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, insurance_type) DO UPDATE SET
                    insurance_scheme_id=EXCLUDED.insurance_scheme_id,
                    tariff_price=EXCLUDED.tariff_price,
                    nursing_tariff=EXCLUDED.nursing_tariff,
                    nursing_covers=EXCLUDED.nursing_covers,
                    is_active=EXCLUDED.is_active,
                    is_supplementary=EXCLUDED.is_supplementary,
                    is_base_tariff=EXCLUDED.is_base_tariff,
                    updated_at=now()
                RETURNING id, insurance_type, insurance_scheme_id,
                          tariff_price, nursing_tariff, nursing_covers,
                          is_active, is_supplementary, is_base_tariff,
                          created_at, updated_at
                """,
                (
                    tenant_id,
                    insurance_type,
                    insurance_scheme_id,
                    tariff_price,
                    nursing_tariff,
                    nursing_covers,
                    is_active,
                    is_supplementary,
                    is_base_tariff,
                ),
            ).fetchone()
        return self.conn.execute(
            """
            UPDATE accounting.visit_tariffs
               SET insurance_type=%s, insurance_scheme_id=%s,
                   tariff_price=%s, nursing_tariff=%s,
                   nursing_covers=%s, is_active=%s,
                   is_supplementary=%s, is_base_tariff=%s,
                   updated_at=now()
             WHERE tenant_id=%s AND id=%s
            RETURNING id, insurance_type, insurance_scheme_id,
                      tariff_price, nursing_tariff, nursing_covers,
                      is_active, is_supplementary, is_base_tariff,
                      created_at, updated_at
            """,
            (
                insurance_type,
                insurance_scheme_id,
                tariff_price,
                nursing_tariff,
                nursing_covers,
                is_active,
                is_supplementary,
                is_base_tariff,
                tenant_id,
                tariff_id,
            ),
        ).fetchone()

    def upsert_catalog_item(
        self,
        *,
        tenant_id: int,
        catalog_type: str,
        item_id: Optional[int],
        name: str,
        price: int,
        is_active: bool,
        category: Optional[str] = None,
    ) -> dict[str, Any]:
        config = _CATALOGS[catalog_type]
        table = sql.Identifier("accounting", config["table"])
        name_col = sql.Identifier(config["name"])
        price_col = sql.Identifier(config["price"])
        if catalog_type == "consumable":
            if item_id is None:
                query = sql.SQL(
                    """
                    INSERT INTO {table} AS c
                        (tenant_id, {name_col}, {price_col}, category, is_active)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, name) DO UPDATE SET
                        default_price=EXCLUDED.default_price,
                        category=EXCLUDED.category,
                        is_active=EXCLUDED.is_active
                    RETURNING id, name, default_price AS price,
                              category, is_active, created_at
                    """
                ).format(table=table, name_col=name_col, price_col=price_col)
                return self.conn.execute(
                    query,
                    (tenant_id, name, price, category, is_active),
                ).fetchone()
            query = sql.SQL(
                """
                UPDATE {table}
                   SET {name_col}=%s, {price_col}=%s, category=%s, is_active=%s
                 WHERE tenant_id=%s AND id=%s
                RETURNING id, name, default_price AS price,
                          category, is_active, created_at
                """
            ).format(table=table, name_col=name_col, price_col=price_col)
            return self.conn.execute(
                query,
                (name, price, category, is_active, tenant_id, item_id),
            ).fetchone()

        if item_id is None:
            query = sql.SQL(
                """
                INSERT INTO {table} AS c
                    (tenant_id, {name_col}, {price_col}, is_active)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, {name_col}) DO UPDATE SET
                    {price_col}=EXCLUDED.{price_col},
                    is_active=EXCLUDED.is_active
                RETURNING id, {name_col} AS name, {price_col} AS price,
                          is_active, created_at
                """
            ).format(table=table, name_col=name_col, price_col=price_col)
            return self.conn.execute(
                query,
                (tenant_id, name, price, is_active),
            ).fetchone()
        query = sql.SQL(
            """
            UPDATE {table}
               SET {name_col}=%s, {price_col}=%s, is_active=%s
             WHERE tenant_id=%s AND id=%s
            RETURNING id, {name_col} AS name, {price_col} AS price,
                      is_active, created_at
            """
        ).format(table=table, name_col=name_col, price_col=price_col)
        return self.conn.execute(
            query,
            (name, price, is_active, tenant_id, item_id),
        ).fetchone()

    def upsert_exclusion(
        self,
        *,
        tenant_id: int,
        exclusion_id: Optional[int],
        insurance_type: str,
        nursing_service_id: int,
        note: Optional[str],
    ) -> dict[str, Any]:
        if exclusion_id is None:
            return self.conn.execute(
                """
                INSERT INTO accounting.insurance_nursing_exclusions AS e
                    (tenant_id, insurance_type, nursing_service_id, note)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, insurance_type, nursing_service_id)
                DO UPDATE SET note=EXCLUDED.note
                RETURNING id, insurance_type, nursing_service_id, note, created_at
                """,
                (tenant_id, insurance_type, nursing_service_id, note),
            ).fetchone()
        return self.conn.execute(
            """
            UPDATE accounting.insurance_nursing_exclusions
               SET insurance_type=%s, nursing_service_id=%s, note=%s
             WHERE tenant_id=%s AND id=%s
            RETURNING id, insurance_type, nursing_service_id, note, created_at
            """,
            (
                insurance_type,
                nursing_service_id,
                note,
                tenant_id,
                exclusion_id,
            ),
        ).fetchone()

    def delete_exclusion(self, *, tenant_id: int, exclusion_id: int) -> bool:
        result = self.conn.execute(
            """
            DELETE FROM accounting.insurance_nursing_exclusions
            WHERE tenant_id=%s AND id=%s
            """,
            (tenant_id, exclusion_id),
        )
        return result.rowcount == 1

    def upsert_payroll(
        self,
        *,
        tenant_id: int,
        staff_id: int,
        base_morning: int,
        base_evening: int,
        base_night: int,
        visit_fee: int,
        injection_percent: Decimal,
        procedure_percent: Decimal,
        tax_percent: Decimal,
        nursing_percent: Decimal,
        nurse_procedure_percent: Decimal,
    ) -> dict[str, Any]:
        return self.conn.execute(
            """
            INSERT INTO accounting.payroll_settings AS p
                (tenant_id, staff_id, base_morning, base_evening,
                 base_night, visit_fee, injection_percent,
                 procedure_percent, tax_percent, nursing_percent,
                 nurse_procedure_percent)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, staff_id) DO UPDATE SET
                base_morning=EXCLUDED.base_morning,
                base_evening=EXCLUDED.base_evening,
                base_night=EXCLUDED.base_night,
                visit_fee=EXCLUDED.visit_fee,
                injection_percent=EXCLUDED.injection_percent,
                procedure_percent=EXCLUDED.procedure_percent,
                tax_percent=EXCLUDED.tax_percent,
                nursing_percent=EXCLUDED.nursing_percent,
                nurse_procedure_percent=EXCLUDED.nurse_procedure_percent,
                updated_at=now()
            RETURNING id, staff_id, base_morning, base_evening,
                      base_night, visit_fee, injection_percent,
                      procedure_percent, tax_percent, nursing_percent,
                      nurse_procedure_percent, updated_at
            """,
            (
                tenant_id,
                staff_id,
                base_morning,
                base_evening,
                base_night,
                visit_fee,
                injection_percent,
                procedure_percent,
                tax_percent,
                nursing_percent,
                nurse_procedure_percent,
            ),
        ).fetchone()

    def log_configuration_change(
        self,
        *,
        tenant_id: int,
        user_id: Optional[int],
        username: str,
        action_type: str,
        target_type: str,
        target_id: Optional[int],
        target_name: Optional[str],
        description: str,
        old_value: Optional[str],
        new_value: Optional[str],
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO accounting.activity_logs
                (tenant_id, user_id, username, action_type, action_category,
                 description, target_type, target_id, target_name,
                 old_value, new_value, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, 'configuration', %s, %s, %s, %s,
                    %s, %s, %s, %s)
            """,
            (
                tenant_id,
                user_id,
                username,
                action_type,
                description,
                target_type,
                target_id,
                target_name,
                old_value,
                new_value,
                ip_address,
                user_agent,
            ),
        )
