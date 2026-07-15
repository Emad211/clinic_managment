from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from psycopg import Connection

from accounting_ops.import_common import (
    ReplayConflictError,
    payload_sha256,
    source_key,
)
from accounting_ops.import_report import ImportReport


@dataclass(frozen=True)
class LedgerEntry:
    source_table: str
    source_key: str
    target_table: str
    target_key: str
    source_sha256: str
    target_sha256: str | None


@dataclass(frozen=True)
class RowStart:
    source_key: str
    source_sha256: str
    replay_target_key: str | None = None

    @property
    def replayed(self) -> bool:
        return self.replay_target_key is not None


_TARGET_COLUMNS: dict[str, tuple[str, ...]] = {
    "accounting.medical_staff": ("id", "tenant_id", "full_name", "staff_type", "is_active"),
    "accounting.patients": (
        "id", "tenant_id", "name", "family_name", "national_id", "phone_number",
        "birthdate", "gender", "insurance_type", "insurance_expiry", "address",
        "is_foreign", "created_by",
    ),
    "accounting.visit_tariffs": (
        "id", "tenant_id", "insurance_type", "insurance_scheme_id", "tariff_price",
        "nursing_tariff", "nursing_covers", "is_active", "is_supplementary",
        "is_base_tariff",
    ),
    "accounting.services": (
        "id", "tenant_id", "name", "base_price", "service_type", "legacy_service_type",
    ),
    "accounting.visit_items": (
        "id", "tenant_id", "visit_id", "service_id", "quantity", "price_at_time",
    ),
    "accounting.nursing_services": (
        "id", "tenant_id", "service_name", "unit_price", "is_active",
    ),
    "accounting.injection_types": (
        "id", "tenant_id", "type_name", "base_price", "is_active",
    ),
    "accounting.procedure_tariffs": (
        "id", "tenant_id", "name", "unit_price", "is_active",
    ),
    "accounting.consumable_tariffs": (
        "id", "tenant_id", "name", "default_price", "category", "is_active",
    ),
    "accounting.insurance_nursing_exclusions": (
        "id", "tenant_id", "insurance_type", "nursing_service_id", "note",
    ),
    "accounting.payroll_settings": (
        "id", "tenant_id", "staff_id", "base_morning", "base_evening", "base_night",
        "visit_fee", "injection_percent", "procedure_percent", "tax_percent",
        "nursing_percent", "nurse_procedure_percent",
    ),
    "accounting.invoices": (
        "id", "tenant_id", "patient_id", "doctor_id", "nurse_id", "status",
        "insurance_type", "supplementary_insurance", "total_amount", "work_date",
        "shift", "opened_at", "closed_at", "opened_by", "opened_by_name",
        "closed_by", "closed_by_name", "pricing_version",
    ),
    "accounting.visits": (
        "id", "tenant_id", "patient_id", "doctor_name", "visit_date", "shift",
        "work_date", "insurance_type", "supplementary_insurance", "status", "price",
        "payment_status", "reception_user", "notes", "invoice_id", "doctor_id", "nurse_id",
    ),
    "accounting.injections": (
        "id", "tenant_id", "patient_id", "injection_type", "service_id",
        "injection_date", "shift", "work_date", "count", "unit_price", "total_price",
        "patient_amount", "insurance_amount", "covered_by_insurance", "reception_user",
        "notes", "invoice_id", "doctor_id", "nurse_id",
    ),
    "accounting.procedures": (
        "id", "tenant_id", "patient_id", "procedure_type", "procedure_date", "shift",
        "work_date", "price", "patient_amount", "insurance_amount", "covered_by_insurance",
        "reception_user", "notes", "invoice_id", "performer_type", "performer_id",
        "doctor_id", "nurse_id",
    ),
    "accounting.consumables_ledger": (
        "id", "tenant_id", "patient_id", "item_name", "category", "quantity",
        "unit_price", "total_cost", "patient_provided", "is_exception", "usage_date",
        "shift", "work_date", "reception_user", "notes", "invoice_id", "doctor_id", "nurse_id",
    ),
    "accounting.invoice_item_payments": (
        "tenant_id", "invoice_id", "item_type", "item_id", "payment_type", "is_paid",
    ),
}


class ImportContext:
    def __init__(
        self,
        *,
        conn: Connection,
        tenant_id: int,
        source_id: str,
        imported_by: str,
        apply: bool,
        report: ImportReport,
    ):
        self.conn = conn
        self.tenant_id = tenant_id
        self.source_id = source_id
        self.imported_by = imported_by
        self.apply = apply
        self.report = report
        self.id_map: dict[tuple[str, str], int] = {}
        self._next_temp_id = -1_000_000_000
        self.ledger = self._load_ledger()

    def _load_ledger(self) -> dict[tuple[str, str], LedgerEntry]:
        rows = self.conn.execute(
            """
            SELECT source_table, source_key, target_table, target_key,
                   source_sha256, target_sha256
            FROM accounting.accounting_import_ledger
            WHERE tenant_id=%s AND source_id=%s
            """,
            (self.tenant_id, self.source_id),
        ).fetchall()
        return {
            (row["source_table"], row["source_key"]): LedgerEntry(**row)
            for row in rows
        }

    def ledger_count(self) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM accounting.accounting_import_ledger
            WHERE tenant_id=%s AND source_id=%s
            """,
            (self.tenant_id, self.source_id),
        ).fetchone()
        return int(row["count"])

    def temp_id(self) -> int:
        value = self._next_temp_id
        self._next_temp_id -= 1
        return value

    def start(self, table: str, row: Mapping[str, Any], target_table: str) -> RowStart:
        key = source_key(table, row)
        digest = payload_sha256(dict(row))
        entry = self.ledger.get((table, key))
        if entry is None:
            return RowStart(key, digest)
        if entry.target_table != target_table or entry.source_sha256 != digest:
            raise ReplayConflictError(
                f"Source row changed or target table drifted for {table}#{key}"
            )
        actual = self.read_target(entry.target_table, entry.target_key)
        if actual is None or payload_sha256(actual) != entry.target_sha256:
            raise ReplayConflictError(
                f"Target fingerprint changed for replayed {table}#{key}"
            )
        self.report.table(table).replayed += 1
        if entry.target_table != "accounting.invoice_item_payments":
            self.id_map[(table, key)] = int(entry.target_key)
        return RowStart(key, digest, entry.target_key)

    def read_target(self, table: str, key: str) -> dict[str, Any] | None:
        columns = _TARGET_COLUMNS.get(table)
        if columns is None:
            raise ReplayConflictError(f"Unsupported target table in ledger: {table}")
        select_columns = ", ".join(columns)
        if table == "accounting.invoice_item_payments":
            invoice_id, item_type, item_id = key.split(":", 2)
            row = self.conn.execute(
                f"SELECT {select_columns} FROM {table} "
                "WHERE tenant_id=%s AND invoice_id=%s AND item_type=%s AND item_id=%s",
                (self.tenant_id, int(invoice_id), item_type, int(item_id)),
            ).fetchone()
        else:
            row = self.conn.execute(
                f"SELECT {select_columns} FROM {table} WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, int(key)),
            ).fetchone()
        return dict(row) if row else None

    def finish(
        self,
        *,
        source_table: str,
        start: RowStart,
        target_table: str,
        target_key: str,
        target_payload: Mapping[str, Any],
        reused: bool,
    ) -> None:
        target_digest = payload_sha256(target_payload)
        if self.apply:
            self.conn.execute(
                """
                INSERT INTO accounting.accounting_import_ledger(
                    tenant_id, source_id, source_table, source_key, target_table,
                    target_key, source_sha256, target_sha256, imported_by
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    self.tenant_id, self.source_id, source_table, start.source_key,
                    target_table, target_key, start.source_sha256, target_digest,
                    self.imported_by,
                ),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO accounting.accounting_import_ledger(
                    id, tenant_id, source_id, source_table, source_key, target_table,
                    target_key, source_sha256, target_sha256, imported_by
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    self.temp_id(), self.tenant_id, self.source_id, source_table,
                    start.source_key, target_table, target_key, start.source_sha256,
                    target_digest, self.imported_by,
                ),
            )
        stats = self.report.table(source_table)
        if self.apply:
            stats.reused += int(reused)
            stats.inserted += int(not reused)
        else:
            stats.planned_reuse += int(reused)
            stats.planned_insert += int(not reused)
        self.ledger[(source_table, start.source_key)] = LedgerEntry(
            source_table=source_table,
            source_key=start.source_key,
            target_table=target_table,
            target_key=target_key,
            source_sha256=start.source_sha256,
            target_sha256=target_digest,
        )
        if target_table != "accounting.invoice_item_payments":
            self.id_map[(source_table, start.source_key)] = int(target_key)

    def mapped_id(self, table: str, source_id: Any, *, nullable: bool = False) -> int | None:
        if source_id is None and nullable:
            return None
        key = str(int(source_id))
        value = self.id_map.get((table, key))
        if value is None:
            raise ReplayConflictError(f"Missing mapped parent {table}#{key}")
        return value
