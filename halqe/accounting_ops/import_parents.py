from __future__ import annotations

from typing import Any, Mapping, Sequence

from accounting_ops.import_common import (
    TargetConflictError,
    boolean,
    clean_text,
    integer_money,
    mapped_service_type,
    normalize,
)
from accounting_ops.import_context import ImportContext


def _assert_equal(actual: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    comparable = {key: actual.get(key) for key in expected}
    if normalize(comparable) != normalize(expected):
        raise TargetConflictError(f"Existing canonical target differs for {label}")


def _insert_id(
    ctx: ImportContext,
    *,
    table: str,
    columns: Sequence[str],
    values: Sequence[Any],
) -> int:
    rendered = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(values))
    if ctx.apply:
        row = ctx.conn.execute(
            f"INSERT INTO {table} ({rendered}) VALUES ({placeholders}) RETURNING id",
            tuple(values),
        ).fetchone()
        return int(row["id"])
    target_id = ctx.temp_id()
    ctx.conn.execute(
        f"INSERT INTO {table} (id, {rendered}) VALUES (%s, {placeholders})",
        (target_id, *values),
    )
    return target_id


def _finish_simple(
    ctx: ImportContext,
    *,
    source_table: str,
    start,
    target_table: str,
    target_id: int,
    reused: bool,
) -> None:
    payload = ctx.read_target(target_table, str(target_id))
    if payload is None:
        raise TargetConflictError(f"Inserted target disappeared: {target_table}#{target_id}")
    ctx.finish(
        source_table=source_table,
        start=start,
        target_table=target_table,
        target_key=str(target_id),
        target_payload=payload,
        reused=reused,
    )


class ParentImporter:
    def __init__(self, ctx: ImportContext, *, service_type_map: Mapping[str, str]):
        self.ctx = ctx
        self.service_type_map = service_type_map

    def run(self, rows: Mapping[str, list[dict[str, Any]]]) -> None:
        self._medical_staff(rows["medical_staff"])
        self._patients(rows["patients"])
        self._visit_tariffs(rows["visit_tariffs"])
        self._services(rows["services"])
        self._nursing_services(rows["nursing_services"])
        self._injection_types(rows["injection_types"])
        self._procedure_tariffs(rows["procedure_tariffs"])
        self._consumable_tariffs(rows["consumable_tariffs"])
        self._exclusions(rows["insurance_nursing_exclusions"])
        self._payroll(rows["payroll_settings"])

    def _medical_staff(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            start = self.ctx.start("medical_staff", row, "accounting.medical_staff")
            if start.replayed:
                continue
            expected = {
                "full_name": clean_text(row.get("full_name")) or "",
                "staff_type": clean_text(row.get("staff_type")) or "",
                "is_active": boolean(row.get("is_active", 1)),
            }
            matches = self.ctx.conn.execute(
                """
                SELECT id, full_name, staff_type, is_active
                FROM accounting.medical_staff
                WHERE tenant_id=%s AND full_name=%s AND staff_type=%s
                ORDER BY id LIMIT 2
                """,
                (self.ctx.tenant_id, expected["full_name"], expected["staff_type"]),
            ).fetchall()
            if len(matches) > 1:
                raise TargetConflictError("Multiple medical staff rows match one legacy identity")
            if matches:
                _assert_equal(matches[0], expected, "medical_staff")
                target_id, reused = int(matches[0]["id"]), True
            else:
                target_id = _insert_id(
                    self.ctx,
                    table="accounting.medical_staff",
                    columns=("tenant_id", "full_name", "staff_type", "is_active"),
                    values=(self.ctx.tenant_id, *expected.values()),
                )
                reused = False
            _finish_simple(
                self.ctx, source_table="medical_staff", start=start,
                target_table="accounting.medical_staff", target_id=target_id, reused=reused,
            )

    def _patients(self, rows: list[dict[str, Any]]) -> None:
        fields = (
            "name", "family_name", "national_id", "phone_number", "birthdate", "gender",
            "insurance_type", "insurance_expiry", "address", "is_foreign", "created_by",
        )
        for row in rows:
            start = self.ctx.start("patients", row, "accounting.patients")
            if start.replayed:
                continue
            expected = {
                "name": clean_text(row.get("name")) or "",
                "family_name": clean_text(row.get("family_name")) or "",
                "national_id": clean_text(row.get("national_id")),
                "phone_number": clean_text(row.get("phone_number")),
                "birthdate": clean_text(row.get("birthdate")),
                "gender": clean_text(row.get("gender")),
                "insurance_type": clean_text(row.get("insurance_type")),
                "insurance_expiry": clean_text(row.get("insurance_expiry")),
                "address": clean_text(row.get("address")),
                "is_foreign": boolean(row.get("is_foreign", 0)),
                "created_by": clean_text(row.get("created_by")),
            }
            existing = None
            if expected["national_id"]:
                existing = self.ctx.conn.execute(
                    """
                    SELECT id, name, family_name, national_id, phone_number, birthdate,
                           gender, insurance_type, insurance_expiry, address, is_foreign, created_by
                    FROM accounting.patients
                    WHERE tenant_id=%s AND national_id=%s
                    """,
                    (self.ctx.tenant_id, expected["national_id"]),
                ).fetchone()
            if existing:
                _assert_equal(existing, expected, "patient national identity")
                target_id, reused = int(existing["id"]), True
            else:
                target_id = _insert_id(
                    self.ctx,
                    table="accounting.patients",
                    columns=("tenant_id", *fields),
                    values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
                )
                reused = False
            _finish_simple(
                self.ctx, source_table="patients", start=start,
                target_table="accounting.patients", target_id=target_id, reused=reused,
            )

    def _visit_tariffs(self, rows: list[dict[str, Any]]) -> None:
        fields = (
            "insurance_type", "insurance_scheme_id", "tariff_price", "nursing_tariff",
            "nursing_covers", "is_active", "is_supplementary", "is_base_tariff",
        )
        for row in rows:
            start = self.ctx.start("visit_tariffs", row, "accounting.visit_tariffs")
            if start.replayed:
                continue
            expected = {
                "insurance_type": clean_text(row.get("insurance_type")) or "",
                "insurance_scheme_id": None,
                "tariff_price": integer_money(row.get("tariff_price"), field="tariff_price"),
                "nursing_tariff": integer_money(row.get("nursing_tariff"), field="nursing_tariff"),
                "nursing_covers": boolean(row.get("nursing_covers", 0)),
                "is_active": boolean(row.get("is_active", 1)),
                "is_supplementary": boolean(row.get("is_supplementary", 0)),
                "is_base_tariff": boolean(row.get("is_base_tariff", 0)),
            }
            existing = self.ctx.conn.execute(
                f"SELECT id, {', '.join(fields)} FROM accounting.visit_tariffs "
                "WHERE tenant_id=%s AND insurance_type=%s",
                (self.ctx.tenant_id, expected["insurance_type"]),
            ).fetchone()
            if existing:
                _assert_equal(existing, expected, "visit tariff")
                target_id, reused = int(existing["id"]), True
            else:
                target_id = _insert_id(
                    self.ctx,
                    table="accounting.visit_tariffs",
                    columns=("tenant_id", *fields),
                    values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
                )
                reused = False
            _finish_simple(
                self.ctx, source_table="visit_tariffs", start=start,
                target_table="accounting.visit_tariffs", target_id=target_id, reused=reused,
            )

    def _services(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            start = self.ctx.start("services", row, "accounting.services")
            if start.replayed:
                continue
            service_type, legacy_type = mapped_service_type(
                row.get("service_type"), self.service_type_map
            )
            target_id = _insert_id(
                self.ctx,
                table="accounting.services",
                columns=("tenant_id", "name", "base_price", "service_type", "legacy_service_type"),
                values=(
                    self.ctx.tenant_id,
                    clean_text(row.get("name")) or "",
                    integer_money(row.get("base_price"), field="service base_price"),
                    service_type,
                    legacy_type,
                ),
            )
            _finish_simple(
                self.ctx, source_table="services", start=start,
                target_table="accounting.services", target_id=target_id, reused=False,
            )

    def _natural_catalog(
        self,
        *,
        source_table: str,
        target_table: str,
        rows: list[dict[str, Any]],
        natural_column: str,
        price_source: str,
        price_target: str,
        category: bool = False,
    ) -> None:
        for row in rows:
            start = self.ctx.start(source_table, row, target_table)
            if start.replayed:
                continue
            expected = {
                natural_column: clean_text(row.get(natural_column)) or "",
                price_target: integer_money(row.get(price_source), field=f"{source_table}.{price_source}"),
                "is_active": boolean(row.get("is_active", 1)),
            }
            if category:
                expected["category"] = clean_text(row.get("category")) or "supply"
            selected = ["id", *expected]
            existing = self.ctx.conn.execute(
                f"SELECT {', '.join(selected)} FROM {target_table} "
                f"WHERE tenant_id=%s AND {natural_column}=%s",
                (self.ctx.tenant_id, expected[natural_column]),
            ).fetchone()
            if existing:
                _assert_equal(existing, expected, source_table)
                target_id, reused = int(existing["id"]), True
            else:
                fields = tuple(expected)
                target_id = _insert_id(
                    self.ctx,
                    table=target_table,
                    columns=("tenant_id", *fields),
                    values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
                )
                reused = False
            _finish_simple(
                self.ctx, source_table=source_table, start=start,
                target_table=target_table, target_id=target_id, reused=reused,
            )

    def _nursing_services(self, rows):
        self._natural_catalog(
            source_table="nursing_services", target_table="accounting.nursing_services",
            rows=rows, natural_column="service_name", price_source="unit_price",
            price_target="unit_price",
        )

    def _injection_types(self, rows):
        self._natural_catalog(
            source_table="injection_types", target_table="accounting.injection_types",
            rows=rows, natural_column="type_name", price_source="base_price",
            price_target="base_price",
        )

    def _procedure_tariffs(self, rows):
        self._natural_catalog(
            source_table="procedure_tariffs", target_table="accounting.procedure_tariffs",
            rows=rows, natural_column="name", price_source="unit_price",
            price_target="unit_price",
        )

    def _consumable_tariffs(self, rows):
        self._natural_catalog(
            source_table="consumable_tariffs", target_table="accounting.consumable_tariffs",
            rows=rows, natural_column="name", price_source="default_price",
            price_target="default_price", category=True,
        )

    def _exclusions(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            start = self.ctx.start(
                "insurance_nursing_exclusions", row,
                "accounting.insurance_nursing_exclusions",
            )
            if start.replayed:
                continue
            expected = {
                "insurance_type": clean_text(row.get("insurance_type")) or "",
                "nursing_service_id": self.ctx.mapped_id(
                    "nursing_services", row.get("nursing_service_id")
                ),
                "note": clean_text(row.get("note")),
            }
            existing = self.ctx.conn.execute(
                """
                SELECT id, insurance_type, nursing_service_id, note
                FROM accounting.insurance_nursing_exclusions
                WHERE tenant_id=%s AND insurance_type=%s AND nursing_service_id=%s
                """,
                (
                    self.ctx.tenant_id, expected["insurance_type"],
                    expected["nursing_service_id"],
                ),
            ).fetchone()
            if existing:
                _assert_equal(existing, expected, "insurance nursing exclusion")
                target_id, reused = int(existing["id"]), True
            else:
                fields = tuple(expected)
                target_id = _insert_id(
                    self.ctx,
                    table="accounting.insurance_nursing_exclusions",
                    columns=("tenant_id", *fields),
                    values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
                )
                reused = False
            _finish_simple(
                self.ctx, source_table="insurance_nursing_exclusions", start=start,
                target_table="accounting.insurance_nursing_exclusions",
                target_id=target_id, reused=reused,
            )

    def _payroll(self, rows: list[dict[str, Any]]) -> None:
        money_fields = ("base_morning", "base_evening", "base_night", "visit_fee")
        percent_fields = (
            "injection_percent", "procedure_percent", "tax_percent",
            "nursing_percent", "nurse_procedure_percent",
        )
        for row in rows:
            start = self.ctx.start("payroll_settings", row, "accounting.payroll_settings")
            if start.replayed:
                continue
            expected: dict[str, Any] = {
                "staff_id": self.ctx.mapped_id("medical_staff", row.get("staff_id")),
            }
            for field in money_fields:
                expected[field] = integer_money(row.get(field), field=f"payroll.{field}")
            for field in percent_fields:
                value = float(row.get(field) or 0)
                if value < 0 or value > 100:
                    raise TargetConflictError(f"Payroll percentage out of range: {field}")
                expected[field] = value
            existing = self.ctx.conn.execute(
                f"SELECT id, {', '.join(expected)} FROM accounting.payroll_settings "
                "WHERE tenant_id=%s AND staff_id=%s",
                (self.ctx.tenant_id, expected["staff_id"]),
            ).fetchone()
            if existing:
                _assert_equal(existing, expected, "payroll settings")
                target_id, reused = int(existing["id"]), True
            else:
                fields = tuple(expected)
                target_id = _insert_id(
                    self.ctx,
                    table="accounting.payroll_settings",
                    columns=("tenant_id", *fields),
                    values=(self.ctx.tenant_id, *(expected[field] for field in fields)),
                )
                reused = False
            _finish_simple(
                self.ctx, source_table="payroll_settings", start=start,
                target_table="accounting.payroll_settings", target_id=target_id, reused=reused,
            )
