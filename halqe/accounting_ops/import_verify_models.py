from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class VerificationCheck:
    code: str
    status: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationReport:
    source_id: str
    source_path: str
    tenant_id: int
    decision: str = "FAILED"
    source_file_sha256: str = ""
    source_manifest_sha256: str = ""
    source_rows: int = 0
    ledger_rows: int = 0
    target_rows: int = 0
    source_money: dict[str, int] = field(default_factory=dict)
    target_money: dict[str, int] = field(default_factory=dict)
    checks: list[VerificationCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def check(
        self,
        code: str,
        ok: bool,
        message: str,
        **evidence: Any,
    ) -> None:
        self.checks.append(
            VerificationCheck(
                code=code,
                status="PASS" if ok else "FAIL",
                message=message,
                evidence=evidence,
            )
        )
        if not ok:
            self.errors.append(code)

    def finalize(self) -> "VerificationReport":
        self.decision = "VERIFIED" if not self.errors else "FAILED"
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
