from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TableStats:
    source_rows: int = 0
    planned_insert: int = 0
    planned_reuse: int = 0
    inserted: int = 0
    reused: int = 0
    replayed: int = 0


@dataclass
class ImportReport:
    source_id: str
    source_path: str
    tenant_id: int
    mode: str
    transaction_status: str = "not_started"
    source_file_sha256: str = ""
    source_manifest_sha256: str = ""
    tables: dict[str, TableStats] = field(default_factory=dict)
    source_money: dict[str, Any] = field(default_factory=dict)
    target_money: dict[str, Any] = field(default_factory=dict)
    ledger_rows_before: int = 0
    ledger_rows_after: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def table(self, name: str) -> TableStats:
        return self.tables.setdefault(name, TableStats())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tables"] = {
            name: asdict(stats) for name, stats in sorted(self.tables.items())
        }
        return payload
