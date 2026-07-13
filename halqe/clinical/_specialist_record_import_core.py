"""Historical specialist-clinic SQLite -> Halqe PostgreSQL record importer.

The import is deliberately conservative.  It resolves patients through the
accounting identity boundary, never creates or mutates accounting demographics,
never infers SMS consent, and refuses to silently discard financial wallet data.
Every imported source row receives an append-only ledger entry containing a
canonical payload digest.  An exact replay is idempotent; a changed source row is
an explicit conflict instead of a silent overwrite.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from psycopg import sql
from psycopg.types.json import Jsonb

from platform_core.tenant_context import set_tenant_guc


TEHRAN = ZoneInfo("Asia/Tehran")
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class SpecialistRecordImportError(Exception):
    """Base fail-closed import error."""


class SourceDatabaseError(SpecialistRecordImportError):
    pass


class SourceRowChangedError(SpecialistRecordImportError):
    pass


class ImportConflictError(SpecialistRecordImportError):
    pass


class UnresolvedPatientError(SpecialistRecordImportError):
    pass


class FinancialDataOutOfScopeError(SpecialistRecordImportError):
    pass


@dataclass
class TableStats:
    source_rows: int = 0
    inserted: int = 0
    reused: int = 0
    replayed: int = 0
    planned_insert: int = 0
    planned_reuse: int = 0
    skipped_unresolved: int = 0

    @property
    def accounted_rows(self) -> int:
        return (
            self.inserted
            + self.reused
            + self.replayed
            + self.planned_insert
            + self.planned_reuse
            + self.skipped_unresolved
        )


@dataclass
class ImportReport:
    source_id: str
    source_path: str
    tenant_id: int
    mode: str
    source_file_sha256: Optional[str] = None
    source_manifest_sha256: Optional[str] = None
    ledger_rows_after: Optional[int] = None
    tables: dict[str, TableStats] = field(default_factory=dict)
    missing_optional_tables: list[str] = field(default_factory=list)
    unresolved_patients: list[dict[str, Any]] = field(default_factory=list)
    financial_data_out_of_scope: dict[str, Any] = field(default_factory=dict)
    out_of_scope_table_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def stat(self, table: str) -> TableStats:
        if table not in self.tables:
            self.tables[table] = TableStats()
        return self.tables[table]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tables"] = {
            key: {
                **asdict(value),
                "accounted_rows": value.accounted_rows,
            }
            for key, value in sorted(self.tables.items())
        }
        return payload


class SQLiteSnapshot:
    """Read-only, transactionally consistent view of the source database."""

    def __init__(self, path: Path, *, allow_live_source: bool = False):
        self.path = path
        self.allow_live_source = allow_live_source
        self.conn: Optional[sqlite3.Connection] = None
        self.tables: set[str] = set()
        self._columns: dict[str, set[str]] = {}

    def __enter__(self) -> "SQLiteSnapshot":
        if not self.path.exists() or not self.path.is_file():
            raise SourceDatabaseError(f"SQLite source does not exist: {self.path}")
        wal = Path(str(self.path) + "-wal")
        if (
            not self.allow_live_source
            and wal.exists()
            and wal.is_file()
            and wal.stat().st_size > 0
        ):
            raise SourceDatabaseError(
                "The SQLite source has a non-empty WAL file. Copy/quiesce the "
                "database first, or explicitly pass --allow-live-source."
            )
        uri = f"file:{self.path.as_posix()}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only=ON")
        self.conn.execute("PRAGMA foreign_keys=ON")
        quick = self.conn.execute("PRAGMA quick_check").fetchone()
        if not quick or quick[0] != "ok":
            raise SourceDatabaseError(
                f"SQLite quick_check failed: {quick[0] if quick else 'no result'}"
            )
        self.conn.execute("BEGIN")
        self.tables = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.conn is not None:
            try:
                self.conn.rollback()
            finally:
                self.conn.close()
        self.conn = None

    def has_table(self, table: str) -> bool:
        return table in self.tables

    def columns(self, table: str) -> set[str]:
        if table not in self._columns:
            if not self.has_table(table):
                self._columns[table] = set()
            else:
                assert self.conn is not None
                self._columns[table] = {
                    row[1]
                    for row in self.conn.execute(
                        f'PRAGMA table_info("{table}")'
                    ).fetchall()
                }
        return self._columns[table]

    def rows(self, table: str) -> list[dict[str, Any]]:
        if not self.has_table(table):
            return []
        assert self.conn is not None
        order = "id" if "id" in self.columns(table) else "rowid"
        return [
            dict(row)
            for row in self.conn.execute(
                f'SELECT * FROM "{table}" ORDER BY {order}'
            ).fetchall()
        ]

    def count(self, table: str) -> int:
        if not self.has_table(table):
            return 0
        assert self.conn is not None
        return int(
            self.conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        )


class SpecialistRecordImporter:
    """One-shot, idempotent importer for one tenant and one SQLite source."""

    REQUIRED_TABLES = ("patient_links",)
    OPTIONAL_TABLES = (
        "conditions",
        "flag_catalog",
        "drug_classes",
        "drug_catalog",
        "lab_test_catalog",
        "condition_lab_tests",
        "patient_conditions",
        "patient_medications",
        "medication_events",
        "allergies",
        "vital_readings",
        "lab_results",
        "patient_flags",
        "appointments",
        "followup_tasks",
        "suggestion_log",
        "surgery_history",
        "medical_history",
        "clinical_notes",
        "prescriptions",
    )
    OUT_OF_SCOPE_TABLES = (
        "wallet_transactions",
        "sms_campaigns",
        "sms_messages",
        "campaign_audience",
        "engagement_dispatch",
        "engagement_approvals",
        "patient_card_tokens",
        "processed_invoices",
        "doctor_visit_log",
        "activity_logs",
        "clinical_rules",
        "clinical_indicators",
        "care_protocols",
    )
    VALID_APPOINTMENT_STATUSES = frozenset(
        {"scheduled", "done", "no_show", "cancelled"}
    )
    VALID_FOLLOWUP_STATUSES = frozenset({"open", "done", "dismissed"})
    VALID_MEDICATION_EVENTS = frozenset({"start", "stop", "dose_change"})
    VALID_NOTE_KINDS = frozenset({"symptom", "exam", "lifestyle", "general"})
    VALID_SUGGESTION_STATUSES = frozenset({"pending", "accepted", "dismissed"})
    DEFAULT_ON_NULL_COLUMNS = frozenset({
        "created_at",
        "diagnosed_at",
        "enrolled_at",
        "issued_at",
        "measured_at",
        "recorded_at",
        "taken_at",
        "updated_at",
    })

    def __init__(
        self,
        *,
        sqlite_path: str | Path,
        source_id: str,
        tenant_id: int,
        apply: bool = False,
        skip_unresolved: bool = False,
        acknowledge_financial_data_out_of_scope: bool = False,
        allow_live_source: bool = False,
        imported_by: str = "specialist-record-etl",
    ):
        self.path = Path(sqlite_path).expanduser().resolve()
        self.source_id = source_id.strip()
        self.tenant_id = int(tenant_id)
        self.apply = bool(apply)
        self.skip_unresolved = bool(skip_unresolved)
        self.ack_financial = bool(acknowledge_financial_data_out_of_scope)
        self.allow_live_source = bool(allow_live_source)
        self.imported_by = imported_by.strip() or "specialist-record-etl"
        self.report = ImportReport(
            source_id=self.source_id,
            source_path=str(self.path),
            tenant_id=self.tenant_id,
            mode="apply" if self.apply else "dry-run",
        )
        self.source: Optional[SQLiteSnapshot] = None
        self.pg = None
        self.maps: dict[str, dict[int, int]] = defaultdict(dict)
        self.unresolved_source_patients: set[int] = set()
        self._target_columns: dict[tuple[str, str], set[str]] = {}
        self._pseudo_id = -1
        self._manifest: list[tuple[str, int, str]] = []
        self._pending_appointment_parents: list[tuple[int, int, int]] = []
        self._source_users: dict[int, str] = {}
        self._platform_users: dict[str, int] = {}

    # ------------------------------------------------------------------ run
    def run(self) -> ImportReport:
        self._validate_arguments()
        before_hash = self._file_sha256(self.path)
        self.report.source_file_sha256 = before_hash

        with SQLiteSnapshot(
            self.path,
            allow_live_source=self.allow_live_source,
        ) as source:
            self.source = source
            self._validate_source_schema()
            self._load_source_users()
            self._collect_out_of_scope_counts()
            self._guard_financial_data()

            with transaction.atomic():
                set_tenant_guc(self.tenant_id)
                with connection.cursor() as cursor:
                    self.pg = cursor
                    self._load_platform_users()
                    self._import_conditions()
                    self._import_flag_catalog()
                    self._import_drug_classes()
                    self._import_drug_catalog()
                    self._import_lab_catalog()
                    self._import_condition_lab_tests()
                    self._import_patient_links()
                    self._import_patient_conditions()
                    self._import_patient_medications()
                    self._import_medication_events()
                    self._import_allergies()
                    self._import_vitals()
                    self._import_labs()
                    self._import_patient_flags()
                    self._import_appointments()
                    self._resolve_appointment_parents()
                    self._import_followups()
                    self._import_suggestion_log()
                    self._import_surgeries()
                    self._import_medical_history()
                    self._import_clinical_notes()
                    self._import_prescriptions()
                    self._reconcile()
                    if self.apply:
                        self.pg.execute(
                            """
                            SELECT COUNT(*)
                            FROM clinical.record_import_ledger
                            WHERE tenant_id=%s AND source_id=%s
                            """,
                            [self.tenant_id, self.source_id],
                        )
                        self.report.ledger_rows_after = int(self.pg.fetchone()[0])

                after_hash = self._file_sha256(self.path)
                if after_hash != before_hash:
                    raise SourceDatabaseError(
                        "SQLite source changed while it was being imported; "
                        "the PostgreSQL transaction was rolled back."
                    )

        self.report.source_manifest_sha256 = self._manifest_sha256()
        self.source = None
        self.pg = None
        return self.report

    # -------------------------------------------------------------- validation
    def _validate_arguments(self) -> None:
        if self.tenant_id <= 0:
            raise SourceDatabaseError("tenant_id must be a positive integer")
        if not SOURCE_ID_RE.fullmatch(self.source_id):
            raise SourceDatabaseError(
                "source_id must be 1-200 characters using letters, digits, . _ : / -"
            )

    def _validate_source_schema(self) -> None:
        assert self.source is not None
        missing = [table for table in self.REQUIRED_TABLES if not self.source.has_table(table)]
        if missing:
            raise SourceDatabaseError(
                "Required SQLite tables are missing: " + ", ".join(missing)
            )
        self.report.missing_optional_tables = [
            table for table in self.OPTIONAL_TABLES if not self.source.has_table(table)
        ]

    def _load_source_users(self) -> None:
        assert self.source is not None
        if not self.source.has_table("users"):
            return
        for row in self.source.rows("users"):
            row_id = self._integer(row.get("id"), "users.id")
            username = self._clean(row.get("username"))
            if username:
                self._source_users[row_id] = username

    def _load_platform_users(self) -> None:
        assert self.pg is not None
        self.pg.execute(
            "SELECT id, username FROM platform.users WHERE tenant_id=%s",
            [self.tenant_id],
        )
        self._platform_users = {
            str(username): int(user_id) for user_id, username in self.pg.fetchall()
        }

    def _collect_out_of_scope_counts(self) -> None:
        assert self.source is not None
        self.report.out_of_scope_table_counts = {
            table: self.source.count(table)
            for table in self.OUT_OF_SCOPE_TABLES
            if self.source.has_table(table) and self.source.count(table) > 0
        }

    def _guard_financial_data(self) -> None:
        assert self.source is not None
        nonzero_wallets = []
        for row in self.source.rows("patient_links"):
            balance = int(row.get("wallet_balance") or 0)
            if balance:
                nonzero_wallets.append(
                    {
                        "source_patient_link_id": int(row["id"]),
                        "national_id": self._clean(row.get("national_id")),
                        "wallet_balance": balance,
                    }
                )
        wallet_transactions = self.source.count("wallet_transactions")
        self.report.financial_data_out_of_scope = {
            "nonzero_patient_wallets": nonzero_wallets,
            "wallet_transaction_count": wallet_transactions,
            "acknowledged": self.ack_financial,
        }
        if (nonzero_wallets or wallet_transactions) and self.apply and not self.ack_financial:
            raise FinancialDataOutOfScopeError(
                "The specialist database contains wallet/financial data. The patient-record "
                "import never migrates money. Reconcile it in the accounting migration first, "
                "then rerun with --acknowledge-financial-data-out-of-scope."
            )
        if nonzero_wallets or wallet_transactions:
            self.report.warnings.append(
                "Wallet balances and wallet_transactions were intentionally not imported."
            )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _clean(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _integer(value: Any, label: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise SourceDatabaseError(f"{label} is not an integer: {value!r}") from exc

    @staticmethod
    def _bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _date(self, value: Any, label: str) -> Optional[date]:
        text = self._clean(value)
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError as exc:
            raise SourceDatabaseError(f"Invalid date in {label}: {text!r}") from exc

    def _datetime(self, value: Any, label: str) -> Optional[datetime]:
        text = self._clean(value)
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise SourceDatabaseError(f"Invalid timestamp in {label}: {text!r}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TEHRAN)
        return parsed

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, Jsonb):
            return SpecialistRecordImporter._jsonable(value.obj)
        if isinstance(value, Mapping):
            return {
                str(key): SpecialistRecordImporter._jsonable(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [SpecialistRecordImporter._jsonable(item) for item in value]
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return value

    def _digest(self, payload: Mapping[str, Any]) -> str:
        rendered = json.dumps(
            self._jsonable(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(rendered).hexdigest()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _manifest_sha256(self) -> str:
        digest = hashlib.sha256()
        for table, row_id, payload_hash in sorted(self._manifest):
            digest.update(f"{table}\0{row_id}\0{payload_hash}\n".encode("utf-8"))
        return digest.hexdigest()

    def _source_row_id(self, table: str, row: Mapping[str, Any]) -> int:
        if row.get("id") is not None:
            return self._integer(row["id"], f"{table}.id")
        natural = {
            "lab_test_catalog": [row.get("test_key")],
            "condition_lab_tests": [row.get("condition_code"), row.get("lab_test_key")],
        }.get(table)
        if not natural or any(self._clean(item) is None for item in natural):
            raise SourceDatabaseError(
                f"Cannot derive a stable source row id for {table}: {row!r}"
            )
        raw = json.dumps(natural, ensure_ascii=False, separators=(",", ":"))
        # Fifteen hex digits stay comfortably inside signed BIGINT.
        return int(hashlib.sha256(f"{table}:{raw}".encode("utf-8")).hexdigest()[:15], 16)

    def _pseudo(self) -> int:
        value = self._pseudo_id
        self._pseudo_id -= 1
        return value

    def _columns(self, schema: str, table: str) -> set[str]:
        key = (schema, table)
        if key not in self._target_columns:
            assert self.pg is not None
            self.pg.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s
                """,
                [schema, table],
            )
            self._target_columns[key] = {str(row[0]) for row in self.pg.fetchall()}
        return self._target_columns[key]

    def _filtered_payload(
        self, schema: str, table: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        allowed = self._columns(schema, table)
        return {
            key: value
            for key, value in payload.items()
            if key in allowed
            and not (value is None and key in self.DEFAULT_ON_NULL_COLUMNS)
        }

    def _insert(self, schema: str, table: str, payload: Mapping[str, Any]) -> int:
        if not self.apply:
            return self._pseudo()
        assert self.pg is not None
        values = self._filtered_payload(schema, table, payload)
        columns = list(values)
        query = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({}) RETURNING id").format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        self.pg.execute(query, [values[column] for column in columns])
        return int(self.pg.fetchone()[0])

    def _exact_id(
        self,
        schema: str,
        table: str,
        payload: Mapping[str, Any],
        *,
        ignore: Iterable[str] = (),
    ) -> Optional[int]:
        assert self.pg is not None
        ignored = set(ignore) | {"id"}
        values = self._filtered_payload(schema, table, payload)
        values = {key: value for key, value in values.items() if key not in ignored}
        if not values:
            return None
        clauses = [
            sql.SQL("{} IS NOT DISTINCT FROM {}").format(
                sql.Identifier(column), sql.Placeholder()
            )
            for column in values
        ]
        query = sql.SQL("SELECT id FROM {}.{} WHERE {} ORDER BY id LIMIT 2").format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(" AND ").join(clauses),
        )
        self.pg.execute(query, list(values.values()))
        rows = self.pg.fetchall()
        if len(rows) > 1:
            self.report.warnings.append(
                f"Multiple exact target rows found for {schema}.{table}; reused id {rows[0][0]}."
            )
        return int(rows[0][0]) if rows else None

    def _target_id_exists(self, target_table: str, target_id: int) -> bool:
        assert self.pg is not None
        schema, table = target_table.split(".", 1)
        query = sql.SQL("SELECT 1 FROM {}.{} WHERE tenant_id=%s AND id=%s").format(
            sql.Identifier(schema), sql.Identifier(table)
        )
        self.pg.execute(query, [self.tenant_id, target_id])
        return self.pg.fetchone() is not None

    def _ledger_get(self, table: str, row_id: int) -> Optional[dict[str, Any]]:
        assert self.pg is not None
        self.pg.execute(
            """
            SELECT target_table, target_row_id, target_key, payload_sha256
            FROM clinical.record_import_ledger
            WHERE tenant_id=%s AND source_id=%s
              AND source_table=%s AND source_row_id=%s
            """,
            [self.tenant_id, self.source_id, table, row_id],
        )
        row = self.pg.fetchone()
        if not row:
            return None
        return {
            "target_table": str(row[0]),
            "target_row_id": int(row[1]) if row[1] is not None else None,
            "target_key": str(row[2]),
            "payload_sha256": str(row[3]),
        }

    def _ledger_add(
        self,
        *,
        source_table: str,
        source_row_id: int,
        target_table: str,
        target_row_id: Optional[int],
        target_key: str,
        payload_sha256: str,
    ) -> None:
        if not self.apply:
            return
        assert self.pg is not None
        self.pg.execute(
            """
            INSERT INTO clinical.record_import_ledger
                (tenant_id, source_id, source_table, source_row_id,
                 target_table, target_row_id, target_key, payload_sha256,
                 imported_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            [
                self.tenant_id,
                self.source_id,
                source_table,
                source_row_id,
                target_table,
                target_row_id,
                target_key,
                payload_sha256,
                self.imported_by,
            ],
        )

    def _begin(
        self,
        *,
        source_table: str,
        row: Mapping[str, Any],
        payload: Mapping[str, Any],
        expected_target_table: str,
    ) -> tuple[int, str, Optional[dict[str, Any]]]:
        row_id = self._source_row_id(source_table, row)
        digest = self._digest(payload)
        self._manifest.append((source_table, row_id, digest))
        stat = self.report.stat(source_table)
        stat.source_rows += 1
        ledger = self._ledger_get(source_table, row_id)
        if ledger:
            if ledger["payload_sha256"] != digest:
                raise SourceRowChangedError(
                    f"Source row changed after import: {source_table}#{row_id}. "
                    "Do not overwrite history silently; reconcile this row explicitly."
                )
            if ledger["target_table"] != expected_target_table:
                raise ImportConflictError(
                    f"Ledger target drift for {source_table}#{row_id}: "
                    f"{ledger['target_table']} != {expected_target_table}"
                )
            target_id = ledger["target_row_id"]
            if target_id is not None and not self._target_id_exists(
                expected_target_table, target_id
            ):
                raise ImportConflictError(
                    f"Ledger points to a missing target row: {expected_target_table}#{target_id}"
                )
            stat.replayed += 1
        return row_id, digest, ledger

    def _finish(
        self,
        *,
        source_table: str,
        source_row_id: int,
        target_table: str,
        target_row_id: Optional[int],
        target_key: str,
        digest: str,
        reused: bool,
    ) -> None:
        stat = self.report.stat(source_table)
        if self.apply:
            if reused:
                stat.reused += 1
            else:
                stat.inserted += 1
            self._ledger_add(
                source_table=source_table,
                source_row_id=source_row_id,
                target_table=target_table,
                target_row_id=target_row_id,
                target_key=target_key,
                payload_sha256=digest,
            )
        elif reused:
            stat.planned_reuse += 1
        else:
            stat.planned_insert += 1

    def _skip_unresolved(self, table: str, source_patient_id: int) -> bool:
        if source_patient_id not in self.unresolved_source_patients:
            return False
        self.report.stat(table).source_rows += 1
        self.report.stat(table).skipped_unresolved += 1
        return True

    # --------------------------------------------------------------- catalogs
    def _import_conditions(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("conditions"):
            payload = {
                "tenant_id": self.tenant_id,
                "name": self._clean(row.get("name")),
                "code": self._clean(row.get("code")),
                "is_active": self._bool(row.get("is_active", 1)),
                "is_chronic": self._bool(row.get("is_chronic", 1)),
                "display_order": int(row.get("display_order") or 100),
                "description": self._clean(row.get("description")),
                "icon": self._clean(row.get("icon")),
                "color": self._clean(row.get("color")),
            }
            if not payload["name"]:
                raise SourceDatabaseError("conditions.name cannot be blank")
            source_row_id, digest, ledger = self._begin(
                source_table="conditions",
                row=row,
                payload=payload,
                expected_target_table="clinical.conditions",
            )
            if ledger:
                self.maps["conditions"][source_row_id] = int(ledger["target_row_id"])
                continue
            matches: set[int] = set()
            if payload["code"]:
                self.pg.execute(
                    "SELECT id FROM clinical.conditions WHERE tenant_id=%s AND code=%s",
                    [self.tenant_id, payload["code"]],
                )
                matches.update(int(item[0]) for item in self.pg.fetchall())
            self.pg.execute(
                "SELECT id FROM clinical.conditions WHERE tenant_id=%s AND name=%s",
                [self.tenant_id, payload["name"]],
            )
            matches.update(int(item[0]) for item in self.pg.fetchall())
            if len(matches) > 1:
                raise ImportConflictError(
                    f"Condition natural keys resolve to different target rows: {row!r}"
                )
            reused = bool(matches)
            target_id = next(iter(matches)) if matches else self._insert("clinical", "conditions", payload)
            self.maps["conditions"][source_row_id] = target_id
            self._finish(
                source_table="conditions",
                source_row_id=source_row_id,
                target_table="clinical.conditions",
                target_row_id=target_id if target_id > 0 else None,
                target_key=f"id:{target_id}" if target_id > 0 else f"planned:{source_row_id}",
                digest=digest,
                reused=reused,
            )

    @staticmethod
    def _flag_section(flag_key: str, category: Optional[str], stored: Optional[str]) -> str:
        if stored:
            return stored
        if flag_key == "metabolic_surgery":
            return "disease"
        return {
            "cardiac": "disease",
            "renal": "disease",
            "hepatic": "disease",
            "risk": "disease",
            "repro": "disease",
            "lifestyle": "lifestyle",
            "exam": "exam",
        }.get(category or "", "general")

    def _import_flag_catalog(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("flag_catalog"):
            key = self._clean(row.get("flag_key"))
            category = self._clean(row.get("category")) or "other"
            payload = {
                "tenant_id": self.tenant_id,
                "flag_key": key,
                "label": self._clean(row.get("label")),
                "flag_type": self._clean(row.get("flag_type")) or "bool",
                "options": self._clean(row.get("options")),
                "category": category,
                "record_section": self._flag_section(
                    key or "",
                    category,
                    self._clean(row.get("record_section")),
                ),
                "display_order": int(row.get("display_order") or 100),
                "is_active": self._bool(row.get("is_active", 1)),
                "notes": self._clean(row.get("notes")),
            }
            if not key or not payload["label"]:
                raise SourceDatabaseError("flag_catalog key/label cannot be blank")
            source_row_id, digest, ledger = self._begin(
                source_table="flag_catalog",
                row=row,
                payload=payload,
                expected_target_table="clinical.flag_catalog",
            )
            if ledger:
                continue
            self.pg.execute(
                "SELECT id FROM clinical.flag_catalog WHERE tenant_id=%s AND flag_key=%s",
                [self.tenant_id, key],
            )
            found = self.pg.fetchone()
            reused = found is not None
            target_id = int(found[0]) if found else self._insert("clinical", "flag_catalog", payload)
            self._finish(
                source_table="flag_catalog",
                source_row_id=source_row_id,
                target_table="clinical.flag_catalog",
                target_row_id=target_id if target_id > 0 else None,
                target_key=f"flag_key:{key}",
                digest=digest,
                reused=reused,
            )

    def _import_drug_classes(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("drug_classes"):
            key = self._clean(row.get("class_key"))
            payload = {
                "tenant_id": self.tenant_id,
                "class_key": key,
                "label": self._clean(row.get("label")),
                "glucose_lowering": self._bool(row.get("glucose_lowering", 0)),
                "display_order": int(row.get("display_order") or 100),
                "is_active": self._bool(row.get("is_active", 1)),
            }
            if not key or not payload["label"]:
                raise SourceDatabaseError("drug_classes key/label cannot be blank")
            source_row_id, digest, ledger = self._begin(
                source_table="drug_classes",
                row=row,
                payload=payload,
                expected_target_table="clinical.drug_classes",
            )
            if ledger:
                continue
            self.pg.execute(
                "SELECT id FROM clinical.drug_classes WHERE tenant_id=%s AND class_key=%s",
                [self.tenant_id, key],
            )
            found = self.pg.fetchone()
            reused = found is not None
            target_id = int(found[0]) if found else self._insert("clinical", "drug_classes", payload)
            self._finish(
                source_table="drug_classes",
                source_row_id=source_row_id,
                target_table="clinical.drug_classes",
                target_row_id=target_id if target_id > 0 else None,
                target_key=f"class_key:{key}",
                digest=digest,
                reused=reused,
            )

    def _import_drug_catalog(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("drug_catalog"):
            name = self._clean(row.get("generic_fa"))
            class_key = self._clean(row.get("drug_class_key"))
            payload = {
                "tenant_id": self.tenant_id,
                "generic_fa": name,
                "drug_class_key": class_key,
                "standard_doses": self._clean(row.get("standard_doses")),
                "is_active": self._bool(row.get("is_active", 1)),
            }
            if not name:
                raise SourceDatabaseError("drug_catalog.generic_fa cannot be blank")
            source_row_id, digest, ledger = self._begin(
                source_table="drug_catalog",
                row=row,
                payload=payload,
                expected_target_table="clinical.drug_catalog",
            )
            if ledger:
                continue
            self.pg.execute(
                """
                SELECT id FROM clinical.drug_catalog
                WHERE tenant_id=%s AND generic_fa=%s
                  AND drug_class_key IS NOT DISTINCT FROM %s
                ORDER BY id LIMIT 2
                """,
                [self.tenant_id, name, class_key],
            )
            matches = self.pg.fetchall()
            if len(matches) > 1:
                self.report.warnings.append(
                    f"Duplicate target drug catalog rows for {name!r}; reused lowest id."
                )
            reused = bool(matches)
            target_id = int(matches[0][0]) if matches else self._insert("clinical", "drug_catalog", payload)
            self._finish(
                source_table="drug_catalog",
                source_row_id=source_row_id,
                target_table="clinical.drug_catalog",
                target_row_id=target_id if target_id > 0 else None,
                target_key=f"drug:{name}|{class_key or ''}",
                digest=digest,
                reused=reused,
            )

    def _import_lab_catalog(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("lab_test_catalog"):
            key = self._clean(row.get("test_key"))
            payload = {
                "tenant_id": self.tenant_id,
                "test_key": key,
                "name_fa": self._clean(row.get("name_fa")),
                "unit": self._clean(row.get("unit")),
                "ref_low": row.get("ref_low"),
                "ref_high": row.get("ref_high"),
                "category": self._clean(row.get("category")),
                "display_order": int(row.get("display_order") or 100),
                "is_active": self._bool(row.get("is_active", 1)),
            }
            if not key or not payload["name_fa"]:
                raise SourceDatabaseError("lab_test_catalog key/name cannot be blank")
            source_row_id, digest, ledger = self._begin(
                source_table="lab_test_catalog",
                row=row,
                payload=payload,
                expected_target_table="clinical.lab_test_catalog",
            )
            if ledger:
                continue
            self.pg.execute(
                "SELECT id FROM clinical.lab_test_catalog WHERE tenant_id=%s AND test_key=%s",
                [self.tenant_id, key],
            )
            found = self.pg.fetchone()
            reused = found is not None
            target_id = int(found[0]) if found else self._insert("clinical", "lab_test_catalog", payload)
            self._finish(
                source_table="lab_test_catalog",
                source_row_id=source_row_id,
                target_table="clinical.lab_test_catalog",
                target_row_id=target_id if target_id > 0 else None,
                target_key=f"test_key:{key}",
                digest=digest,
                reused=reused,
            )

    def _import_condition_lab_tests(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("condition_lab_tests"):
            condition_code = self._clean(row.get("condition_code"))
            test_key = self._clean(row.get("lab_test_key"))
            payload = {
                "tenant_id": self.tenant_id,
                "condition_code": condition_code,
                "lab_test_key": test_key,
                "display_order": int(row.get("display_order") or 100),
            }
            if not condition_code or not test_key:
                raise SourceDatabaseError("condition_lab_tests natural key is blank")
            source_row_id, digest, ledger = self._begin(
                source_table="condition_lab_tests",
                row=row,
                payload=payload,
                expected_target_table="clinical.condition_lab_tests",
            )
            if ledger:
                self.pg.execute(
                    """
                    SELECT 1 FROM clinical.condition_lab_tests
                    WHERE tenant_id=%s AND condition_code=%s AND lab_test_key=%s
                    """,
                    [self.tenant_id, condition_code, test_key],
                )
                if not self.pg.fetchone():
                    raise ImportConflictError(
                        f"Ledger mapping is missing for condition_lab_tests {condition_code}/{test_key}"
                    )
                continue
            self.pg.execute(
                """
                SELECT 1 FROM clinical.condition_lab_tests
                WHERE tenant_id=%s AND condition_code=%s AND lab_test_key=%s
                """,
                [self.tenant_id, condition_code, test_key],
            )
            reused = self.pg.fetchone() is not None
            if self.apply and not reused:
                self.pg.execute(
                    """
                    INSERT INTO clinical.condition_lab_tests
                        (tenant_id, condition_code, lab_test_key, display_order)
                    VALUES (%s,%s,%s,%s)
                    """,
                    [self.tenant_id, condition_code, test_key, payload["display_order"]],
                )
            self._finish(
                source_table="condition_lab_tests",
                source_row_id=source_row_id,
                target_table="clinical.condition_lab_tests",
                target_row_id=None,
                target_key=f"{condition_code}|{test_key}",
                digest=digest,
                reused=reused,
            )

    # ------------------------------------------------------------- identities
    def _resolve_accounting_patient(self, row: Mapping[str, Any]) -> Optional[int]:
        assert self.pg is not None
        national_id = self._clean(row.get("national_id"))
        source_accounting_id = row.get("accounting_patient_id")
        by_national: Optional[int] = None
        by_id: Optional[int] = None
        if national_id:
            self.pg.execute(
                """
                SELECT id FROM accounting.patients
                WHERE tenant_id=%s AND national_id=%s
                ORDER BY id LIMIT 2
                """,
                [self.tenant_id, national_id],
            )
            matches = self.pg.fetchall()
            if len(matches) > 1:
                raise ImportConflictError(
                    f"Multiple accounting patients share national_id {national_id!r}"
                )
            if matches:
                by_national = int(matches[0][0])
        if source_accounting_id is not None:
            try:
                numeric_id = int(source_accounting_id)
            except (TypeError, ValueError):
                numeric_id = 0
            if numeric_id > 0:
                self.pg.execute(
                    "SELECT id FROM accounting.patients WHERE tenant_id=%s AND id=%s",
                    [self.tenant_id, numeric_id],
                )
                found = self.pg.fetchone()
                if found:
                    by_id = int(found[0])
        if by_national and by_id and by_national != by_id:
            raise ImportConflictError(
                "Source patient identity conflict: accounting_patient_id and national_id "
                f"resolve to different target patients ({by_id} vs {by_national})."
            )
        return by_national or by_id

    def _import_patient_links(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("patient_links"):
            source_row_id = self._source_row_id("patient_links", row)
            payload_for_digest = {
                "accounting_patient_id": row.get("accounting_patient_id"),
                "national_id": self._clean(row.get("national_id")),
                "full_name": self._clean(row.get("full_name")),
                "phone_number": self._clean(row.get("phone_number")),
                "gender": self._clean(row.get("gender")),
                "birthdate": self._clean(row.get("birthdate")),
                "address": self._clean(row.get("address")),
                "notes": self._clean(row.get("notes")),
                "sms_opt_out": self._bool(row.get("sms_opt_out", 0)),
                "is_active": self._bool(row.get("is_active", 1)),
                "enrolled_by": self._clean(row.get("enrolled_by")),
                "enrolled_at": self._datetime(
                    row.get("enrolled_at"), f"patient_links#{source_row_id}.enrolled_at"
                ),
            }
            source_row_id, digest, ledger = self._begin(
                source_table="patient_links",
                row=row,
                payload=payload_for_digest,
                expected_target_table="clinical.patient_links",
            )
            if ledger:
                self.maps["patient_links"][source_row_id] = int(ledger["target_row_id"])
                continue

            accounting_patient_id = self._resolve_accounting_patient(row)
            if accounting_patient_id is None:
                detail = {
                    "source_patient_link_id": source_row_id,
                    "national_id": self._clean(row.get("national_id")),
                    "accounting_patient_id": row.get("accounting_patient_id"),
                    "full_name": self._clean(row.get("full_name")),
                }
                self.report.unresolved_patients.append(detail)
                self.unresolved_source_patients.add(source_row_id)
                if self.skip_unresolved:
                    stat = self.report.stat("patient_links")
                    stat.skipped_unresolved += 1
                    continue
                raise UnresolvedPatientError(
                    "Cannot resolve specialist patient to accounting.patients: "
                    + json.dumps(detail, ensure_ascii=False, sort_keys=True)
                )

            self.pg.execute(
                """
                SELECT id, is_active, sms_opt_out
                FROM clinical.patient_links
                WHERE tenant_id=%s AND patient_id=%s
                ORDER BY id LIMIT 2
                """,
                [self.tenant_id, accounting_patient_id],
            )
            matches = self.pg.fetchall()
            if len(matches) > 1:
                raise ImportConflictError(
                    f"Multiple clinical patient_links for accounting patient {accounting_patient_id}"
                )
            reused = bool(matches)
            if reused:
                target_id = int(matches[0][0])
                target_active = bool(matches[0][1])
                target_opt_out = bool(matches[0][2])
                if payload_for_digest["sms_opt_out"] and not target_opt_out and self.apply:
                    self.pg.execute(
                        """
                        UPDATE clinical.patient_links
                        SET sms_opt_out=TRUE,
                            sms_opt_out_at=COALESCE(sms_opt_out_at,%s)
                        WHERE tenant_id=%s AND id=%s
                        """,
                        [
                            self._datetime(
                                row.get("updated_at"),
                                f"patient_links#{source_row_id}.updated_at",
                            )
                            or datetime.now(tz=TEHRAN),
                            self.tenant_id,
                            target_id,
                        ],
                    )
                if payload_for_digest["is_active"] and not target_active:
                    self.report.warnings.append(
                        f"Source patient_link {source_row_id} is active but target link {target_id} is inactive; target was not reactivated."
                    )
            else:
                target_payload = {
                    "tenant_id": self.tenant_id,
                    "patient_id": accounting_patient_id,
                    # Never infer consent. The safe default remains FALSE.
                    "sms_consent": False,
                    "sms_opt_out": payload_for_digest["sms_opt_out"],
                    "sms_opt_out_at": (
                        self._datetime(
                            row.get("updated_at"),
                            f"patient_links#{source_row_id}.updated_at",
                        )
                        if payload_for_digest["sms_opt_out"]
                        else None
                    ),
                    "is_active": payload_for_digest["is_active"],
                    "enrolled_by": payload_for_digest["enrolled_by"],
                    "enrolled_at": payload_for_digest["enrolled_at"],
                    "notes": payload_for_digest["notes"],
                }
                target_id = self._insert("clinical", "patient_links", target_payload)
            self.maps["patient_links"][source_row_id] = target_id
            self._finish(
                source_table="patient_links",
                source_row_id=source_row_id,
                target_table="clinical.patient_links",
                target_row_id=target_id if target_id > 0 else None,
                target_key=f"patient_id:{accounting_patient_id}",
                digest=digest,
                reused=reused,
            )

    def _patient_target(self, table: str, row: Mapping[str, Any]) -> Optional[int]:
        source_patient_id = self._integer(
            row.get("patient_link_id"), f"{table}.patient_link_id"
        )
        if self._skip_unresolved(table, source_patient_id):
            return None
        if source_patient_id not in self.maps["patient_links"]:
            raise SourceDatabaseError(
                f"{table} references unknown source patient_link_id {source_patient_id}"
            )
        return self.maps["patient_links"][source_patient_id]

    # --------------------------------------------------------------- children
    def _import_patient_conditions(self) -> None:
        assert self.source is not None
        for row in self.source.rows("patient_conditions"):
            target_patient = self._patient_target("patient_conditions", row)
            if target_patient is None:
                continue
            source_condition_id = self._integer(
                row.get("condition_id"), "patient_conditions.condition_id"
            )
            if source_condition_id not in self.maps["conditions"]:
                raise SourceDatabaseError(
                    f"patient_conditions references unknown condition {source_condition_id}"
                )
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "condition_id": self.maps["conditions"][source_condition_id],
                "stage": self._clean(row.get("stage")),
                "onset_date": self._date(row.get("onset_date"), "patient_conditions.onset_date"),
                "notes": self._clean(row.get("notes")),
                "is_active": self._bool(row.get("is_active", 1)),
                "diagnosed_at": self._datetime(
                    row.get("diagnosed_at"), "patient_conditions.diagnosed_at"
                ),
            }
            self._import_exact_child("patient_conditions", row, payload)

    def _import_patient_medications(self) -> None:
        assert self.source is not None
        for row in self.source.rows("patient_medications"):
            target_patient = self._patient_target("patient_medications", row)
            if target_patient is None:
                continue
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "drug_name": self._clean(row.get("drug_name")),
                "dose": self._clean(row.get("dose")),
                "schedule": self._clean(row.get("schedule")),
                "start_date": self._date(row.get("start_date"), "patient_medications.start_date"),
                "refill_due_date": self._date(
                    row.get("refill_due_date"), "patient_medications.refill_due_date"
                ),
                "end_date": self._date(row.get("end_date"), "patient_medications.end_date"),
                "drug_class": self._clean(row.get("drug_class")),
                "is_active": self._bool(row.get("is_active", 1)),
                "notes": self._clean(row.get("notes")),
                "created_at": self._datetime(
                    row.get("created_at"), "patient_medications.created_at"
                ),
            }
            if not payload["drug_name"]:
                raise SourceDatabaseError("patient_medications.drug_name cannot be blank")
            target_id = self._import_exact_child(
                "patient_medications", row, payload
            )
            self.maps["patient_medications"][self._source_row_id("patient_medications", row)] = target_id

    def _import_medication_events(self) -> None:
        assert self.source is not None
        for row in self.source.rows("medication_events"):
            target_patient = self._patient_target("medication_events", row)
            if target_patient is None:
                continue
            event_type = self._clean(row.get("event_type"))
            if event_type not in self.VALID_MEDICATION_EVENTS:
                raise SourceDatabaseError(f"Invalid medication event type: {event_type!r}")
            source_medication_id = row.get("medication_id")
            target_medication_id = None
            if source_medication_id is not None:
                numeric = self._integer(source_medication_id, "medication_events.medication_id")
                target_medication_id = self.maps["patient_medications"].get(numeric)
                if target_medication_id is None:
                    self.report.warnings.append(
                        f"Medication event {row.get('id')} references missing medication {numeric}; imported as orphan event."
                    )
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "medication_id": target_medication_id,
                "drug_name": self._clean(row.get("drug_name")),
                "event_type": event_type,
                "dose": self._clean(row.get("dose")),
                "event_date": self._date(row.get("event_date"), "medication_events.event_date"),
                "note": self._clean(row.get("note")),
                "created_by": self._clean(row.get("created_by")),
                "created_at": self._datetime(
                    row.get("created_at"), "medication_events.created_at"
                ),
            }
            if not payload["drug_name"]:
                raise SourceDatabaseError("medication_events.drug_name cannot be blank")
            self._import_exact_child("medication_events", row, payload)

    def _import_allergies(self) -> None:
        assert self.source is not None
        for row in self.source.rows("allergies"):
            target_patient = self._patient_target("allergies", row)
            if target_patient is None:
                continue
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "substance": self._clean(row.get("substance")),
                "reaction": self._clean(row.get("reaction")),
                "severity": self._clean(row.get("severity")),
                "created_at": self._datetime(row.get("created_at"), "allergies.created_at"),
            }
            if not payload["substance"]:
                raise SourceDatabaseError("allergies.substance cannot be blank")
            self._import_exact_child("allergies", row, payload)

    def _import_vitals(self) -> None:
        assert self.source is not None
        for row in self.source.rows("vital_readings"):
            target_patient = self._patient_target("vital_readings", row)
            if target_patient is None:
                continue
            source_name = (self._clean(row.get("source")) or "clinic").lower()
            self_report = source_name in {"self", "patient_self"}
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "type": self._clean(row.get("type")),
                "value": row.get("value"),
                "unit": self._clean(row.get("unit")),
                "measured_at": self._datetime(
                    row.get("measured_at"), "vital_readings.measured_at"
                ),
                "source": "patient_self" if self_report else "clinic",
                "notes": self._clean(row.get("notes")),
                "recorded_by": self._clean(row.get("recorded_by")),
                "encounter_id": None,
                "verified": not self_report,
                "verified_by": None,
                "verified_at": None,
                "rejected_by": None,
                "rejected_at": None,
            }
            if not payload["type"] or payload["value"] is None:
                raise SourceDatabaseError("vital_readings type/value cannot be blank")
            self._import_exact_child("vital_readings", row, payload)

    def _import_labs(self) -> None:
        assert self.source is not None
        for row in self.source.rows("lab_results"):
            target_patient = self._patient_target("lab_results", row)
            if target_patient is None:
                continue
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "test_name": self._clean(row.get("test_name")),
                "test_key": self._clean(row.get("test_key")),
                "value": row.get("value"),
                "unit": self._clean(row.get("unit")),
                "ref_low": row.get("ref_low"),
                "ref_high": row.get("ref_high"),
                "taken_at": self._datetime(row.get("taken_at"), "lab_results.taken_at"),
                "notes": self._clean(row.get("notes")),
                "recorded_by": self._clean(row.get("recorded_by")),
                "encounter_id": None,
            }
            if not payload["test_name"]:
                raise SourceDatabaseError("lab_results.test_name cannot be blank")
            self._import_exact_child("lab_results", row, payload)

    def _import_patient_flags(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("patient_flags"):
            target_patient = self._patient_target("patient_flags", row)
            if target_patient is None:
                continue
            key = self._clean(row.get("flag_key"))
            if not key:
                raise SourceDatabaseError("patient_flags.flag_key cannot be blank")
            self.pg.execute(
                "SELECT 1 FROM clinical.flag_catalog WHERE tenant_id=%s AND flag_key=%s",
                [self.tenant_id, key],
            )
            if not self.pg.fetchone():
                raise SourceDatabaseError(
                    f"patient_flags references missing target flag_catalog key {key!r}"
                )
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "flag_key": key,
                "value": self._clean(row.get("value")) or "",
                "recorded_by": self._clean(row.get("recorded_by")),
                "updated_at": self._datetime(row.get("updated_at"), "patient_flags.updated_at"),
            }
            source_row_id, digest, ledger = self._begin(
                source_table="patient_flags",
                row=row,
                payload=payload,
                expected_target_table="clinical.patient_flags",
            )
            if ledger:
                continue
            self.pg.execute(
                """
                SELECT id, value FROM clinical.patient_flags
                WHERE tenant_id=%s AND patient_link_id=%s AND flag_key=%s
                """,
                [self.tenant_id, target_patient, key],
            )
            found = self.pg.fetchone()
            reused = False
            if found:
                if str(found[1] or "") != str(payload["value"] or ""):
                    raise ImportConflictError(
                        f"Target patient flag {key!r} already has a different value."
                    )
                target_id = int(found[0])
                reused = True
            else:
                target_id = self._insert("clinical", "patient_flags", payload)
            self._finish(
                source_table="patient_flags",
                source_row_id=source_row_id,
                target_table="clinical.patient_flags",
                target_row_id=target_id if target_id > 0 else None,
                target_key=f"patient:{target_patient}|flag:{key}",
                digest=digest,
                reused=reused,
            )

    def _import_appointments(self) -> None:
        assert self.source is not None
        for row in self.source.rows("appointments"):
            target_patient = self._patient_target("appointments", row)
            if target_patient is None:
                continue
            status = self._clean(row.get("status")) or "scheduled"
            if status not in self.VALID_APPOINTMENT_STATUSES:
                raise SourceDatabaseError(f"Invalid appointment status: {status!r}")
            source_user = row.get("doctor_id")
            target_doctor_id = self._map_platform_user_id(source_user)
            parent_source_raw = row.get("parent_appointment_id")
            parent_source_id = (
                self._integer(parent_source_raw, "appointments.parent_appointment_id")
                if parent_source_raw is not None
                else None
            )
            payload = {
                "_source_parent_appointment_id": parent_source_id,
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "scheduled_at": self._datetime(
                    row.get("scheduled_at"), "appointments.scheduled_at"
                ),
                "appt_type": self._clean(row.get("appt_type")),
                "status": status,
                "recurrence_months": row.get("recurrence_months"),
                "parent_appointment_id": None,
                "reminder_sent": self._bool(row.get("reminder_sent", 0)),
                "notes": self._clean(row.get("notes")),
                "created_by": self._clean(row.get("created_by")),
                "created_at": self._datetime(row.get("created_at"), "appointments.created_at"),
                "doctor_id": target_doctor_id,
                "chief_complaint": self._clean(row.get("chief_complaint")),
            }
            if payload["scheduled_at"] is None:
                raise SourceDatabaseError("appointments.scheduled_at cannot be blank")
            target_id = self._import_exact_child(
                "appointments",
                row,
                payload,
                exact_ignore={"parent_appointment_id"},
            )
            source_id = self._source_row_id("appointments", row)
            self.maps["appointments"][source_id] = target_id
            if parent_source_id is not None:
                self._pending_appointment_parents.append(
                    (source_id, target_id, parent_source_id)
                )

    def _resolve_appointment_parents(self) -> None:
        if not self._pending_appointment_parents:
            return
        assert self.pg is not None
        for source_id, target_id, parent_source_id in self._pending_appointment_parents:
            parent_target = self.maps["appointments"].get(parent_source_id)
            if parent_target is None:
                raise SourceDatabaseError(
                    f"Appointment {source_id} references missing parent {parent_source_id}"
                )
            if self.apply:
                self.pg.execute(
                    """
                    UPDATE clinical.appointments
                    SET parent_appointment_id=%s
                    WHERE tenant_id=%s AND id=%s
                      AND parent_appointment_id IS DISTINCT FROM %s
                    """,
                    [parent_target, self.tenant_id, target_id, parent_target],
                )

    def _import_followups(self) -> None:
        assert self.source is not None
        for row in self.source.rows("followup_tasks"):
            target_patient = self._patient_target("followup_tasks", row)
            if target_patient is None:
                continue
            status = self._clean(row.get("status")) or "open"
            if status not in self.VALID_FOLLOWUP_STATUSES:
                raise SourceDatabaseError(f"Invalid followup status: {status!r}")
            source_appointment = row.get("appointment_id")
            target_appointment = None
            if source_appointment is not None:
                target_appointment = self.maps["appointments"].get(
                    self._integer(source_appointment, "followup_tasks.appointment_id")
                )
                if target_appointment is None:
                    self.report.warnings.append(
                        f"Followup {row.get('id')} references missing appointment {source_appointment}; link omitted."
                    )
            fulfillment = self._clean(row.get("fulfillment")) or "in_person"
            if fulfillment not in {"in_person", "remote"}:
                fulfillment = "in_person"
                self.report.warnings.append(
                    f"Followup {row.get('id')} had invalid fulfillment; defaulted to in_person."
                )
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "due_date": self._date(row.get("due_date"), "followup_tasks.due_date"),
                "reason": self._clean(row.get("reason")),
                "detail": self._clean(row.get("detail")),
                "status": status,
                "assigned_to": self._clean(row.get("assigned_to")),
                "call_log": self._clean(row.get("call_log")),
                "source_rule": self._clean(row.get("source_rule")),
                "source_event": self._clean(row.get("source_event")),
                "appointment_id": target_appointment,
                "fulfillment": fulfillment,
                "created_at": self._datetime(row.get("created_at"), "followup_tasks.created_at"),
                "resolved_at": self._datetime(row.get("resolved_at"), "followup_tasks.resolved_at"),
            }
            target_id = self._import_exact_child("followup_tasks", row, payload)
            self.maps["followup_tasks"][self._source_row_id("followup_tasks", row)] = target_id

    def _import_suggestion_log(self) -> None:
        assert self.source is not None and self.pg is not None
        for row in self.source.rows("suggestion_log"):
            target_patient = self._patient_target("suggestion_log", row)
            if target_patient is None:
                continue
            status = self._clean(row.get("status")) or "pending"
            if status not in self.VALID_SUGGESTION_STATUSES:
                raise SourceDatabaseError(f"Invalid suggestion status: {status!r}")
            rule_code = self._clean(row.get("rule_code"))
            if not rule_code:
                raise SourceDatabaseError("suggestion_log.rule_code cannot be blank")
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "rule_code": rule_code,
                "suggestion_text": self._clean(row.get("suggestion_text")),
                "evidence_level": self._clean(row.get("evidence_level")),
                "status": status,
                "acted_by": self._clean(row.get("acted_by")),
                "acted_at": self._datetime(row.get("acted_at"), "suggestion_log.acted_at"),
                "note": self._clean(row.get("note")),
                "created_at": self._datetime(row.get("created_at"), "suggestion_log.created_at"),
            }
            source_row_id, digest, ledger = self._begin(
                source_table="suggestion_log",
                row=row,
                payload=payload,
                expected_target_table="clinical.suggestion_log",
            )
            if ledger:
                continue
            self.pg.execute(
                """
                SELECT id, status, acted_by, acted_at, note
                FROM clinical.suggestion_log
                WHERE tenant_id=%s AND patient_link_id=%s AND rule_code=%s
                """,
                [self.tenant_id, target_patient, rule_code],
            )
            found = self.pg.fetchone()
            reused = False
            if found:
                existing = {
                    "status": found[1],
                    "acted_by": found[2],
                    "acted_at": found[3],
                    "note": found[4],
                }
                expected = {
                    "status": payload["status"],
                    "acted_by": payload["acted_by"],
                    "acted_at": payload["acted_at"],
                    "note": payload["note"],
                }
                if self._jsonable(existing) != self._jsonable(expected):
                    raise ImportConflictError(
                        f"Target suggestion_log for {rule_code!r} already differs."
                    )
                target_id = int(found[0])
                reused = True
            else:
                target_id = self._insert("clinical", "suggestion_log", payload)
            self._finish(
                source_table="suggestion_log",
                source_row_id=source_row_id,
                target_table="clinical.suggestion_log",
                target_row_id=target_id if target_id > 0 else None,
                target_key=f"patient:{target_patient}|rule:{rule_code}",
                digest=digest,
                reused=reused,
            )

    def _import_surgeries(self) -> None:
        assert self.source is not None
        for row in self.source.rows("surgery_history"):
            target_patient = self._patient_target("surgery_history", row)
            if target_patient is None:
                continue
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "title": self._clean(row.get("title")),
                "performed_on": self._date(row.get("performed_on"), "surgery_history.performed_on"),
                "note": self._clean(row.get("note")),
                "created_at": self._datetime(row.get("created_at"), "surgery_history.created_at"),
            }
            if not payload["title"]:
                raise SourceDatabaseError("surgery_history.title cannot be blank")
            self._import_exact_child("surgery_history", row, payload)

    def _import_medical_history(self) -> None:
        assert self.source is not None
        for row in self.source.rows("medical_history"):
            target_patient = self._patient_target("medical_history", row)
            if target_patient is None:
                continue
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "title": self._clean(row.get("title")),
                "note": self._clean(row.get("note")),
                "since": self._date(row.get("since"), "medical_history.since"),
                "created_at": self._datetime(row.get("created_at"), "medical_history.created_at"),
            }
            if not payload["title"]:
                raise SourceDatabaseError("medical_history.title cannot be blank")
            self._import_exact_child("medical_history", row, payload)

    def _import_clinical_notes(self) -> None:
        assert self.source is not None
        for row in self.source.rows("clinical_notes"):
            target_patient = self._patient_target("clinical_notes", row)
            if target_patient is None:
                continue
            kind = self._clean(row.get("kind"))
            if kind not in self.VALID_NOTE_KINDS:
                raise SourceDatabaseError(f"Invalid clinical note kind: {kind!r}")
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "kind": kind,
                "body": self._clean(row.get("body")),
                "recorded_at": self._datetime(row.get("recorded_at"), "clinical_notes.recorded_at"),
                "recorded_by": self._clean(row.get("recorded_by")),
            }
            self._import_exact_child("clinical_notes", row, payload)

    def _parse_prescription_items(self, value: Any, source_row_id: int) -> Any:
        text = self._clean(value)
        if not text:
            return None
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            self.report.warnings.append(
                f"Prescription {source_row_id} had invalid JSON; preserved under legacy_raw."
            )
            return {"legacy_raw": text}

    def _map_platform_user_id(self, source_user_id: Any) -> Optional[int]:
        if source_user_id is None:
            return None
        try:
            source_id = int(source_user_id)
        except (TypeError, ValueError):
            return None
        username = self._source_users.get(source_id)
        if not username:
            return None
        target = self._platform_users.get(username)
        if target is None:
            self.report.warnings.append(
                f"Source user {username!r} has no platform.users match; foreign key omitted."
            )
        return target

    def _import_prescriptions(self) -> None:
        assert self.source is not None
        for row in self.source.rows("prescriptions"):
            target_patient = self._patient_target("prescriptions", row)
            if target_patient is None:
                continue
            source_row_id = self._source_row_id("prescriptions", row)
            source_followup = row.get("followup_task_id")
            target_followup = None
            if source_followup is not None:
                target_followup = self.maps["followup_tasks"].get(
                    self._integer(source_followup, "prescriptions.followup_task_id")
                )
                if target_followup is None:
                    self.report.warnings.append(
                        f"Prescription {source_row_id} references missing followup {source_followup}; link omitted."
                    )
            parsed_items = self._parse_prescription_items(row.get("items"), source_row_id)
            payload = {
                "tenant_id": self.tenant_id,
                "patient_link_id": target_patient,
                "kind": self._clean(row.get("kind")),
                "items": Jsonb(parsed_items) if parsed_items is not None else None,
                "mode": self._clean(row.get("mode")) or "free",
                "insurer": self._clean(row.get("insurer")),
                "portal_rx_id": self._clean(row.get("portal_rx_id")),
                "prescriber_user_id": self._map_platform_user_id(row.get("prescriber_user_id")),
                "followup_task_id": target_followup,
                "encounter_id": None,
                "issued_at": self._datetime(row.get("issued_at"), "prescriptions.issued_at"),
            }
            if not payload["kind"]:
                raise SourceDatabaseError("prescriptions.kind cannot be blank")
            self._import_exact_child("prescriptions", row, payload)

    def _import_exact_child(
        self,
        source_table: str,
        row: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        exact_ignore: Iterable[str] = (),
    ) -> int:
        target_table = f"clinical.{source_table}"
        source_row_id, digest, ledger = self._begin(
            source_table=source_table,
            row=row,
            payload=payload,
            expected_target_table=target_table,
        )
        if ledger:
            target_id = ledger["target_row_id"]
            if target_id is None:
                raise ImportConflictError(
                    f"Ledger row lacks target id for {source_table}#{source_row_id}"
                )
            return int(target_id)
        target_id = self._exact_id(
            "clinical", source_table, payload, ignore=exact_ignore
        )
        reused = target_id is not None
        if target_id is None:
            target_id = self._insert("clinical", source_table, payload)
        self._finish(
            source_table=source_table,
            source_row_id=source_row_id,
            target_table=target_table,
            target_row_id=target_id if target_id > 0 else None,
            target_key=f"id:{target_id}" if target_id > 0 else f"planned:{source_row_id}",
            digest=digest,
            reused=reused,
        )
        return target_id

    # ------------------------------------------------------------ reconciliation
    def _reconcile(self) -> None:
        assert self.source is not None
        for table, stat in self.report.tables.items():
            if stat.accounted_rows != stat.source_rows:
                raise ImportConflictError(
                    f"Reconciliation mismatch for {table}: source={stat.source_rows}, "
                    f"accounted={stat.accounted_rows}"
                )
        if self.report.unresolved_patients and not self.skip_unresolved:
            raise UnresolvedPatientError("Unresolved patients remain after import")
