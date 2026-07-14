"""Data contracts for legacy SQLite accounting-import preflight."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TablePreflight:
    source_rows: int = 0
    manifest_sha256: str = ""
    missing_columns: list[str] = field(default_factory=list)


@dataclass
class AccountingImportPreflightReport:
    source_id: str
    source_path: str
    source_file_sha256: str = ""
    source_manifest_sha256: str = ""
    quick_check: str = "not_run"
    decision: str = "NO_GO"
    tables: dict[str, TablePreflight] = field(default_factory=dict)
    money: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    ignored_tables: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def check(self, code: str, passed: bool, detail: str, **evidence: Any) -> None:
        self.checks.append(
            {
                "code": code,
                "status": "PASS" if passed else "FAIL",
                "detail": detail,
                "evidence": evidence,
            }
        )
        if not passed:
            self.errors.append(f"{code}: {detail}")

    def finalize(self) -> "AccountingImportPreflightReport":
        self.decision = "GO" if not self.errors else "NO_GO"
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tables"] = {
            name: asdict(value) for name, value in self.tables.items()
        }
        return payload
