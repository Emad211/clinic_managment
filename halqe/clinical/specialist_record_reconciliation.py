"""Read-only reconciliation verifier for specialist-clinic record imports.

The importer proves that a source can be transformed safely.  This module proves
that a committed rehearsal is still internally consistent: the secured SQLite
snapshot reproduces the same file/manifest hashes, the apply and replay reports
agree, every ledger pointer resolves, and domain invariants such as unverified
patient self-reports remain intact.

No clinical or accounting row is written by this verifier.  Its only optional
write is an owner-only JSON artifact performed by the management command.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any, Iterable, Mapping, Optional

from django.db import connection
from psycopg import sql

from clinical.specialist_record_import import (
    SpecialistRecordImportError,
    SpecialistRecordImporter,
)
from platform_core.tenant_context import set_tenant_guc


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_ALLOWED_SCHEMAS = frozenset({"clinical", "accounting", "platform"})
_COUNTER_FIELDS = (
    "inserted",
    "reused",
    "replayed",
    "planned_insert",
    "planned_reuse",
    "skipped_unresolved",
)


class SpecialistRecordReconciliationError(Exception):
    """Raised for unusable inputs rather than an ordinary NO_GO finding."""


@dataclass
class ReconciliationCheck:
    name: str
    status: str
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpecialistRecordReconciliationReport:
    source_id: str
    tenant_id: int
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    decision: str = "NO_GO"
    strict_warnings: bool = False
    source_file_sha256: Optional[str] = None
    source_manifest_sha256: Optional[str] = None
    apply_report_sha256: Optional[str] = None
    replay_report_sha256: Optional[str] = None
    checks: list[ReconciliationCheck] = field(default_factory=list)

    def add(
        self,
        name: str,
        status: str,
        detail: str,
        **metrics: Any,
    ) -> None:
        if status not in {"pass", "warn", "fail"}:
            raise ValueError(f"invalid reconciliation status: {status}")
        self.checks.append(
            ReconciliationCheck(
                name=name,
                status=status,
                detail=detail,
                metrics=metrics,
            )
        )

    def finalize(self) -> None:
        has_failures = any(item.status == "fail" for item in self.checks)
        has_warnings = any(item.status == "warn" for item in self.checks)
        self.decision = (
            "NO_GO"
            if has_failures or (self.strict_warnings and has_warnings)
            else "GO"
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = {
            "passed": sum(item.status == "pass" for item in self.checks),
            "warnings": sum(item.status == "warn" for item in self.checks),
            "failed": sum(item.status == "fail" for item in self.checks),
        }
        return payload


class SpecialistRecordReconciler:
    """Verify apply/replay reports, source snapshot and durable target state."""

    def __init__(
        self,
        *,
        sqlite_path: str | Path,
        apply_report_path: str | Path,
        replay_report_path: str | Path | None,
        source_id: str | None = None,
        tenant_id: int | None = None,
        allow_skipped_unresolved: bool = False,
        allow_live_source: bool = False,
        strict_warnings: bool = False,
        require_replay: bool = True,
    ):
        self.sqlite_path = Path(sqlite_path).expanduser().resolve()
        self.apply_report_path = Path(apply_report_path).expanduser().absolute()
        self.replay_report_path = (
            Path(replay_report_path).expanduser().absolute()
            if replay_report_path
            else None
        )
        self.expected_source_id = source_id.strip() if source_id else None
        self.expected_tenant_id = int(tenant_id) if tenant_id is not None else None
        self.allow_skipped_unresolved = bool(allow_skipped_unresolved)
        self.allow_live_source = bool(allow_live_source)
        self.strict_warnings = bool(strict_warnings)
        self.require_replay = bool(require_replay)
        self.apply_report: dict[str, Any] = {}
        self.replay_report: dict[str, Any] | None = None
        self.report: SpecialistRecordReconciliationReport | None = None

    # ------------------------------------------------------------------ public
    def run(self) -> SpecialistRecordReconciliationReport:
        apply_payload, apply_digest, apply_mode = self._load_json_report(
            self.apply_report_path,
            label="apply report",
        )
        source_id = self._required_string(apply_payload, "source_id")
        tenant_id = self._positive_int(apply_payload.get("tenant_id"), "tenant_id")
        if self.expected_source_id and source_id != self.expected_source_id:
            raise SpecialistRecordReconciliationError(
                "apply report source_id does not match --source-id"
            )
        if self.expected_tenant_id and tenant_id != self.expected_tenant_id:
            raise SpecialistRecordReconciliationError(
                "apply report tenant_id does not match --tenant-id"
            )

        self.apply_report = apply_payload
        self.report = SpecialistRecordReconciliationReport(
            source_id=source_id,
            tenant_id=tenant_id,
            strict_warnings=self.strict_warnings,
            apply_report_sha256=apply_digest,
        )
        self._check_private_mode("apply_report_permissions", apply_mode)

        if self.replay_report_path:
            replay_payload, replay_digest, replay_mode = self._load_json_report(
                self.replay_report_path,
                label="replay report",
            )
            self.replay_report = replay_payload
            self.report.replay_report_sha256 = replay_digest
            self._check_private_mode("replay_report_permissions", replay_mode)
        elif self.require_replay:
            self.report.add(
                "replay_report_present",
                "fail",
                "A second idempotent --apply report is required for release reconciliation.",
            )
        else:
            self.report.add(
                "replay_report_present",
                "warn",
                "No replay report was supplied; idempotent apply was not independently certified.",
            )

        self._check_apply_report()
        if self.replay_report is not None:
            self._check_replay_report()
        self._rerun_relational_dry_run()
        self._check_durable_ledger()
        self._check_domain_invariants()
        self.report.finalize()
        return self.report

    # -------------------------------------------------------------- input files
    @staticmethod
    def _load_json_report(
        path: Path,
        *,
        label: str,
    ) -> tuple[dict[str, Any], str, int]:
        if path.is_symlink():
            raise SpecialistRecordReconciliationError(
                f"Refusing to read {label} through a symlink: {path}"
            )
        if not path.exists() or not path.is_file():
            raise SpecialistRecordReconciliationError(
                f"{label} does not exist or is not a regular file: {path}"
            )
        if path.stat().st_size > 20 * 1024 * 1024:
            raise SpecialistRecordReconciliationError(
                f"{label} exceeds the 20 MiB safety limit: {path}"
            )
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpecialistRecordReconciliationError(
                f"{label} is not valid UTF-8 JSON: {path}"
            ) from exc
        if not isinstance(payload, dict):
            raise SpecialistRecordReconciliationError(
                f"{label} root must be a JSON object"
            )
        return (
            payload,
            hashlib.sha256(raw).hexdigest(),
            stat.S_IMODE(path.stat().st_mode),
        )

    @staticmethod
    def _required_string(payload: Mapping[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SpecialistRecordReconciliationError(
                f"report field {key!r} must be a non-empty string"
            )
        return value.strip()

    @staticmethod
    def _positive_int(value: Any, label: str) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise SpecialistRecordReconciliationError(
                f"{label} must be an integer"
            ) from exc
        if number <= 0:
            raise SpecialistRecordReconciliationError(
                f"{label} must be positive"
            )
        return number

    def _check_private_mode(self, name: str, mode: int) -> None:
        assert self.report is not None
        if mode & 0o077:
            self.report.add(
                name,
                "warn",
                "Report is readable or writable by group/other users.",
                mode=oct(mode),
                expected="0o600",
            )
        else:
            self.report.add(
                name,
                "pass",
                "Report permissions are owner-only.",
                mode=oct(mode),
            )

    # -------------------------------------------------------------- report rules
    @staticmethod
    def _table_counters(row: Mapping[str, Any]) -> dict[str, int]:
        counters: dict[str, int] = {}
        for key in ("source_rows", *_COUNTER_FIELDS):
            try:
                value = int(row.get(key, 0))
            except (TypeError, ValueError) as exc:
                raise SpecialistRecordReconciliationError(
                    f"table statistic {key!r} is not an integer"
                ) from exc
            if value < 0:
                raise SpecialistRecordReconciliationError(
                    f"table statistic {key!r} cannot be negative"
                )
            counters[key] = value
        counters["accounted_rows"] = sum(
            counters[key] for key in _COUNTER_FIELDS
        )
        return counters

    def _table_stats(self, payload: Mapping[str, Any]) -> dict[str, dict[str, int]]:
        raw = payload.get("tables")
        if not isinstance(raw, dict):
            raise SpecialistRecordReconciliationError(
                "report field 'tables' must be an object"
            )
        output: dict[str, dict[str, int]] = {}
        for table, row in raw.items():
            if not isinstance(table, str) or not table:
                raise SpecialistRecordReconciliationError(
                    "report table names must be non-empty strings"
                )
            if not isinstance(row, dict):
                raise SpecialistRecordReconciliationError(
                    f"report statistics for {table!r} must be an object"
                )
            output[table] = self._table_counters(row)
        return output

    @staticmethod
    def _valid_hash(value: Any) -> bool:
        return isinstance(value, str) and bool(_HASH_RE.fullmatch(value))

    def _check_apply_report(self) -> None:
        assert self.report is not None
        payload = self.apply_report
        failures: list[str] = []
        if payload.get("mode") != "apply":
            failures.append("mode is not apply")
        if payload.get("transaction_status") != "committed":
            failures.append("transaction_status is not committed")
        if payload.get("error") not in (None, ""):
            failures.append("error is not empty")
        if payload.get("source_id") != self.report.source_id:
            failures.append("source_id drift")
        if int(payload.get("tenant_id", 0) or 0) != self.report.tenant_id:
            failures.append("tenant_id drift")
        if not self._valid_hash(payload.get("source_file_sha256")):
            failures.append("source_file_sha256 is missing or invalid")
        if not self._valid_hash(payload.get("source_manifest_sha256")):
            failures.append("source_manifest_sha256 is missing or invalid")

        if failures:
            self.report.add(
                "apply_report_contract",
                "fail",
                "; ".join(failures),
            )
        else:
            self.report.source_file_sha256 = payload["source_file_sha256"]
            self.report.source_manifest_sha256 = payload["source_manifest_sha256"]
            self.report.add(
                "apply_report_contract",
                "pass",
                "Apply report is committed, error-free and hash-complete.",
            )

        stats = self._table_stats(payload)
        mismatches = {
            table: {
                "source_rows": row["source_rows"],
                "accounted_rows": row["accounted_rows"],
            }
            for table, row in stats.items()
            if row["source_rows"] != row["accounted_rows"]
        }
        planned = {
            table: row["planned_insert"] + row["planned_reuse"]
            for table, row in stats.items()
            if row["planned_insert"] or row["planned_reuse"]
        }
        if mismatches or planned:
            self.report.add(
                "apply_table_accounting",
                "fail",
                "Apply report contains unaccounted rows or dry-run counters.",
                mismatches=mismatches,
                planned=planned,
            )
        else:
            self.report.add(
                "apply_table_accounting",
                "pass",
                "Every source row is accounted for and no planned counters remain.",
                tables=len(stats),
                source_rows=sum(row["source_rows"] for row in stats.values()),
            )

        skipped = sum(row["skipped_unresolved"] for row in stats.values())
        unresolved = payload.get("unresolved_patients") or []
        if skipped or unresolved:
            status = "warn" if self.allow_skipped_unresolved else "fail"
            self.report.add(
                "unresolved_patient_policy",
                status,
                "One or more source patients or child rows were skipped as unresolved.",
                skipped_rows=skipped,
                unresolved_patients=len(unresolved) if isinstance(unresolved, list) else None,
            )
        else:
            self.report.add(
                "unresolved_patient_policy",
                "pass",
                "No source patient or child row was skipped as unresolved.",
            )

        expected_ledger = sum(
            row["source_rows"] - row["skipped_unresolved"]
            for row in stats.values()
        )
        actual_ledger = payload.get("ledger_rows_after")
        if actual_ledger != expected_ledger:
            self.report.add(
                "apply_report_ledger_count",
                "fail",
                "Apply report ledger count does not equal imported/reused source rows.",
                expected=expected_ledger,
                reported=actual_ledger,
            )
        else:
            self.report.add(
                "apply_report_ledger_count",
                "pass",
                "Apply report ledger count matches all non-skipped source rows.",
                ledger_rows=expected_ledger,
            )

        financial = payload.get("financial_data_out_of_scope") or {}
        wallet_rows = financial.get("nonzero_patient_wallets") or [] if isinstance(financial, dict) else []
        wallet_transactions = int(financial.get("wallet_transaction_count", 0) or 0) if isinstance(financial, dict) else 0
        acknowledged = bool(financial.get("acknowledged")) if isinstance(financial, dict) else False
        if wallet_rows or wallet_transactions:
            self.report.add(
                "financial_data_out_of_scope",
                "warn" if acknowledged else "fail",
                "Source contains financial data that this record importer intentionally excludes.",
                nonzero_wallets=len(wallet_rows),
                wallet_transactions=wallet_transactions,
                acknowledged=acknowledged,
            )
        else:
            self.report.add(
                "financial_data_out_of_scope",
                "pass",
                "No wallet balance or wallet transaction was reported by the source.",
            )

        warnings = payload.get("warnings") or []
        missing = payload.get("missing_optional_tables") or []
        out_of_scope = payload.get("out_of_scope_table_counts") or {}
        if warnings or missing or out_of_scope:
            self.report.add(
                "apply_report_warnings",
                "warn",
                "Apply report contains warnings, missing optional tables or other out-of-scope rows.",
                warnings=len(warnings) if isinstance(warnings, list) else None,
                missing_optional_tables=len(missing) if isinstance(missing, list) else None,
                out_of_scope_tables=len(out_of_scope) if isinstance(out_of_scope, dict) else None,
            )
        else:
            self.report.add(
                "apply_report_warnings",
                "pass",
                "Apply report contains no warnings or unreviewed optional gaps.",
            )

    def _check_replay_report(self) -> None:
        assert self.report is not None and self.replay_report is not None
        payload = self.replay_report
        failures: list[str] = []
        for key in ("source_id", "tenant_id", "source_file_sha256", "source_manifest_sha256"):
            if payload.get(key) != self.apply_report.get(key):
                failures.append(f"{key} differs from apply report")
        if payload.get("mode") != "apply":
            failures.append("mode is not apply")
        if payload.get("transaction_status") != "committed":
            failures.append("transaction_status is not committed")
        if payload.get("error") not in (None, ""):
            failures.append("error is not empty")
        if payload.get("ledger_rows_after") != self.apply_report.get("ledger_rows_after"):
            failures.append("ledger_rows_after differs from apply report")

        apply_stats = self._table_stats(self.apply_report)
        replay_stats = self._table_stats(payload)
        if set(apply_stats) != set(replay_stats):
            failures.append("table set differs from apply report")
        else:
            for table, row in replay_stats.items():
                if row["source_rows"] != apply_stats[table]["source_rows"]:
                    failures.append(f"source row count changed for {table}")
                if any(
                    row[key] != 0
                    for key in ("inserted", "reused", "planned_insert", "planned_reuse")
                ):
                    failures.append(f"replay performed non-replay work for {table}")
                if row["replayed"] + row["skipped_unresolved"] != row["source_rows"]:
                    failures.append(f"replay did not account for every row in {table}")

        if failures:
            self.report.add(
                "idempotent_replay_report",
                "fail",
                "; ".join(failures[:20]),
                failure_count=len(failures),
            )
        else:
            self.report.add(
                "idempotent_replay_report",
                "pass",
                "Second apply is a pure replay with unchanged hashes and ledger count.",
                tables=len(replay_stats),
            )

    # ---------------------------------------------------------- source rehearsal
    def _rerun_relational_dry_run(self) -> None:
        assert self.report is not None
        apply_stats = self._table_stats(self.apply_report)
        has_skips = any(row["skipped_unresolved"] for row in apply_stats.values())
        try:
            rehearsal = SpecialistRecordImporter(
                sqlite_path=self.sqlite_path,
                source_id=self.report.source_id,
                tenant_id=self.report.tenant_id,
                apply=False,
                skip_unresolved=has_skips,
                acknowledge_financial_data_out_of_scope=False,
                allow_live_source=self.allow_live_source,
                imported_by="specialist-record-reconciliation",
            ).run()
        except SpecialistRecordImportError as exc:
            self.report.add(
                "relational_dry_run_reproduction",
                "fail",
                f"Current source cannot reproduce a safe dry-run: {exc}",
            )
            return

        dry = rehearsal.to_dict()
        failures: list[str] = []
        if dry.get("transaction_status") != "validated_no_commit":
            failures.append("dry-run did not end as validated_no_commit")
        for key in ("source_file_sha256", "source_manifest_sha256"):
            if dry.get(key) != self.apply_report.get(key):
                failures.append(f"{key} differs from apply report")
        dry_stats = self._table_stats(dry)
        if set(dry_stats) != set(apply_stats):
            failures.append("source table set differs from apply report")
        else:
            for table in dry_stats:
                for key in ("source_rows", "skipped_unresolved"):
                    if dry_stats[table][key] != apply_stats[table][key]:
                        failures.append(f"{key} differs for {table}")
        if dry.get("missing_optional_tables") != self.apply_report.get("missing_optional_tables"):
            failures.append("missing optional table set changed")
        if dry.get("out_of_scope_table_counts") != self.apply_report.get("out_of_scope_table_counts"):
            failures.append("out-of-scope source counts changed")

        if failures:
            self.report.add(
                "relational_dry_run_reproduction",
                "fail",
                "; ".join(failures[:20]),
                failure_count=len(failures),
            )
        else:
            self.report.add(
                "relational_dry_run_reproduction",
                "pass",
                "Current SQLite snapshot reproduces the committed file hash, manifest and source counts with no writes.",
            )

    # --------------------------------------------------------------- PostgreSQL
    def _ledger_rows(self) -> list[dict[str, Any]]:
        assert self.report is not None
        set_tenant_guc(self.report.tenant_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_table, source_row_id, target_table,
                       target_row_id, target_key, payload_sha256
                FROM clinical.record_import_ledger
                WHERE tenant_id=%s AND source_id=%s
                ORDER BY source_table, source_row_id
                """,
                [self.report.tenant_id, self.report.source_id],
            )
            return [
                {
                    "source_table": str(row[0]),
                    "source_row_id": int(row[1]),
                    "target_table": str(row[2]),
                    "target_row_id": int(row[3]) if row[3] is not None else None,
                    "target_key": str(row[4]),
                    "payload_sha256": str(row[5]),
                }
                for row in cursor.fetchall()
            ]

    def _check_durable_ledger(self) -> None:
        assert self.report is not None
        rows = self._ledger_rows()
        apply_stats = self._table_stats(self.apply_report)
        expected = sum(
            row["source_rows"] - row["skipped_unresolved"]
            for row in apply_stats.values()
        )
        if len(rows) != expected:
            self.report.add(
                "durable_ledger_count",
                "fail",
                "Durable ledger row count differs from the apply report.",
                expected=expected,
                actual=len(rows),
            )
        else:
            self.report.add(
                "durable_ledger_count",
                "pass",
                "Durable ledger contains one row for every non-skipped source row.",
                rows=len(rows),
            )

        actual_by_table = Counter(row["source_table"] for row in rows)
        expected_by_table = {
            table: stats["source_rows"] - stats["skipped_unresolved"]
            for table, stats in apply_stats.items()
            if stats["source_rows"] - stats["skipped_unresolved"] > 0
        }
        count_drift = {
            table: {
                "expected": expected_by_table.get(table, 0),
                "actual": actual_by_table.get(table, 0),
            }
            for table in sorted(set(expected_by_table) | set(actual_by_table))
            if expected_by_table.get(table, 0) != actual_by_table.get(table, 0)
        }
        if count_drift:
            self.report.add(
                "ledger_source_table_counts",
                "fail",
                "Ledger source-table counts differ from the apply report.",
                drift=count_drift,
            )
        else:
            self.report.add(
                "ledger_source_table_counts",
                "pass",
                "Ledger source-table counts match the apply report.",
                tables=len(actual_by_table),
            )

        malformed = [
            f"{row['source_table']}#{row['source_row_id']}"
            for row in rows
            if not row["target_key"].strip()
            or not _HASH_RE.fullmatch(row["payload_sha256"])
            or (
                row["target_row_id"] is not None
                and row["target_row_id"] <= 0
            )
        ]
        if malformed:
            self.report.add(
                "ledger_row_shape",
                "fail",
                "Ledger contains blank keys, invalid digests or non-positive target IDs.",
                count=len(malformed),
                sample=malformed[:10],
            )
        else:
            self.report.add(
                "ledger_row_shape",
                "pass",
                "Every ledger row has a valid digest, target key and positive target ID when applicable.",
            )

        skipped = sum(row["skipped_unresolved"] for row in apply_stats.values())
        if not skipped:
            digest = hashlib.sha256()
            for row in rows:
                digest.update(
                    f"{row['source_table']}\0{row['source_row_id']}\0{row['payload_sha256']}\n".encode(
                        "utf-8"
                    )
                )
            ledger_manifest = digest.hexdigest()
            expected_manifest = self.apply_report.get("source_manifest_sha256")
            if ledger_manifest != expected_manifest:
                self.report.add(
                    "ledger_manifest",
                    "fail",
                    "Digest manifest reconstructed from the ledger differs from the source manifest.",
                    ledger_manifest=ledger_manifest,
                    source_manifest=expected_manifest,
                )
            else:
                self.report.add(
                    "ledger_manifest",
                    "pass",
                    "Ledger digests reproduce the committed source manifest.",
                    manifest=ledger_manifest,
                )
        else:
            self.report.add(
                "ledger_manifest",
                "warn",
                "Manifest equality is not asserted because unresolved source rows were skipped.",
                skipped_rows=skipped,
            )

        self._check_target_existence(rows)

    @staticmethod
    def _chunks(values: list[int], size: int = 5000) -> Iterable[list[int]]:
        for index in range(0, len(values), size):
            yield values[index : index + size]

    def _check_target_existence(self, rows: list[dict[str, Any]]) -> None:
        assert self.report is not None
        grouped: dict[str, set[int]] = defaultdict(set)
        natural: list[dict[str, Any]] = []
        invalid_tables: list[str] = []
        null_id_unexpected: list[str] = []

        for row in rows:
            target_table = row["target_table"]
            parts = target_table.split(".")
            if (
                len(parts) != 2
                or parts[0] not in _ALLOWED_SCHEMAS
                or not all(_IDENTIFIER_RE.fullmatch(part) for part in parts)
            ):
                invalid_tables.append(target_table)
                continue
            if row["target_row_id"] is None:
                if target_table == "clinical.condition_lab_tests":
                    natural.append(row)
                else:
                    null_id_unexpected.append(
                        f"{row['source_table']}#{row['source_row_id']}->{target_table}"
                    )
            else:
                grouped[target_table].add(row["target_row_id"])

        missing: list[str] = []
        set_tenant_guc(self.report.tenant_id)
        with connection.cursor() as cursor:
            for target_table, ids in grouped.items():
                schema_name, table_name = target_table.split(".", 1)
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema=%s AND table_name=%s
                      AND column_name IN ('tenant_id','id')
                    """,
                    [schema_name, table_name],
                )
                if {str(row[0]) for row in cursor.fetchall()} != {"tenant_id", "id"}:
                    invalid_tables.append(target_table)
                    continue
                found: set[int] = set()
                for chunk in self._chunks(sorted(ids)):
                    query = sql.SQL(
                        "SELECT id FROM {}.{} WHERE tenant_id=%s AND id=ANY(%s)"
                    ).format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                    )
                    cursor.execute(query, [self.report.tenant_id, chunk])
                    found.update(int(row[0]) for row in cursor.fetchall())
                missing.extend(
                    f"{target_table}#{target_id}"
                    for target_id in sorted(ids - found)
                )

            if natural:
                cursor.execute(
                    """
                    SELECT condition_code, lab_test_key
                    FROM clinical.condition_lab_tests
                    WHERE tenant_id=%s
                    """,
                    [self.report.tenant_id],
                )
                existing_natural = {
                    f"{row[0]}|{row[1]}" for row in cursor.fetchall()
                }
                for item in natural:
                    if item["target_key"] not in existing_natural:
                        missing.append(
                            "clinical.condition_lab_tests:"
                            + item["target_key"]
                        )

        if invalid_tables or null_id_unexpected or missing:
            self.report.add(
                "ledger_target_existence",
                "fail",
                "One or more ledger targets are invalid or missing.",
                invalid_tables=sorted(set(invalid_tables))[:20],
                unexpected_null_ids=null_id_unexpected[:20],
                missing_count=len(missing),
                missing_sample=missing[:20],
            )
        else:
            self.report.add(
                "ledger_target_existence",
                "pass",
                "Every ledger target resolves in the expected tenant, including natural-key mappings.",
                id_targets=sum(len(ids) for ids in grouped.values()),
                natural_targets=len(natural),
            )

    # ------------------------------------------------------------ domain checks
    def _scalar(self, query: str, params: list[Any]) -> int:
        assert self.report is not None
        set_tenant_guc(self.report.tenant_id)
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return int(cursor.fetchone()[0])

    def _check_domain_invariants(self) -> None:
        assert self.report is not None
        base = [self.report.tenant_id, self.report.source_id]
        checks = [
            (
                "medication_event_orphans",
                "Imported medication events must reference an existing medication for the same patient.",
                """
                SELECT COUNT(*)
                FROM clinical.record_import_ledger l
                JOIN clinical.medication_events e
                  ON e.tenant_id=l.tenant_id AND e.id=l.target_row_id
                LEFT JOIN clinical.patient_medications m
                  ON m.tenant_id=e.tenant_id AND m.id=e.medication_id
                WHERE l.tenant_id=%s AND l.source_id=%s
                  AND l.source_table='medication_events'
                  AND e.medication_id IS NOT NULL
                  AND (
                      m.id IS NULL
                      OR m.patient_link_id IS DISTINCT FROM e.patient_link_id
                  )
                """,
            ),
            (
                "verified_patient_self_reports",
                "Imported patient self-reports must remain unverified until clinical review.",
                """
                SELECT COUNT(*)
                FROM clinical.record_import_ledger l
                JOIN clinical.vital_readings v
                  ON v.tenant_id=l.tenant_id AND v.id=l.target_row_id
                WHERE l.tenant_id=%s AND l.source_id=%s
                  AND l.source_table='vital_readings'
                  AND v.source IN ('patient_self','self')
                  AND v.verified=TRUE
                """,
            ),
            (
                "lab_observation_visibility",
                "Every imported lab result must be visible in the canonical Observation stream.",
                """
                SELECT COUNT(*)
                FROM clinical.record_import_ledger l
                JOIN clinical.lab_results r
                  ON r.tenant_id=l.tenant_id AND r.id=l.target_row_id
                LEFT JOIN clinical.observations o
                  ON o.tenant_id=r.tenant_id
                 AND o.patient_link_id=r.patient_link_id
                 AND o.source_table='lab'
                 AND o.source_id=r.id
                WHERE l.tenant_id=%s AND l.source_id=%s
                  AND l.source_table='lab_results'
                  AND o.source_id IS NULL
                """,
            ),
            (
                "appointment_parent_orphans",
                "Imported recurring appointments must not point to a missing parent.",
                """
                SELECT COUNT(*)
                FROM clinical.record_import_ledger l
                JOIN clinical.appointments a
                  ON a.tenant_id=l.tenant_id AND a.id=l.target_row_id
                LEFT JOIN clinical.appointments p
                  ON p.tenant_id=a.tenant_id AND p.id=a.parent_appointment_id
                WHERE l.tenant_id=%s AND l.source_id=%s
                  AND l.source_table='appointments'
                  AND a.parent_appointment_id IS NOT NULL
                  AND p.id IS NULL
                """,
            ),
            (
                "followup_appointment_orphans",
                "Imported follow-ups must not point to a missing appointment.",
                """
                SELECT COUNT(*)
                FROM clinical.record_import_ledger l
                JOIN clinical.followup_tasks f
                  ON f.tenant_id=l.tenant_id AND f.id=l.target_row_id
                LEFT JOIN clinical.appointments a
                  ON a.tenant_id=f.tenant_id AND a.id=f.appointment_id
                WHERE l.tenant_id=%s AND l.source_id=%s
                  AND l.source_table='followup_tasks'
                  AND f.appointment_id IS NOT NULL
                  AND a.id IS NULL
                """,
            ),
            (
                "prescription_followup_orphans",
                "Imported prescriptions must not point to a missing follow-up.",
                """
                SELECT COUNT(*)
                FROM clinical.record_import_ledger l
                JOIN clinical.prescriptions p
                  ON p.tenant_id=l.tenant_id AND p.id=l.target_row_id
                LEFT JOIN clinical.followup_tasks f
                  ON f.tenant_id=p.tenant_id AND f.id=p.followup_task_id
                WHERE l.tenant_id=%s AND l.source_id=%s
                  AND l.source_table='prescriptions'
                  AND p.followup_task_id IS NOT NULL
                  AND f.id IS NULL
                """,
            ),
        ]

        for name, detail, query in checks:
            count = self._scalar(query, base)
            if count:
                self.report.add(
                    name,
                    "fail",
                    detail,
                    violations=count,
                )
            else:
                self.report.add(
                    name,
                    "pass",
                    detail,
                    violations=0,
                )
