from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SignoffCheck:
    code: str
    status: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountingCutoverSignoffReport:
    decision: str
    source_id: str
    tenant_id: int
    reviewed_by: str | None
    reviewed_at: str | None
    required_consecutive_days: int
    observed_dates: list[str]
    artifact_sha256: dict[str, Any]
    checks: list[SignoffCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(
        self,
        code: str,
        ok: bool,
        message: str,
        **evidence: Any,
    ) -> None:
        self.checks.append(
            SignoffCheck(
                code=code,
                status="PASS" if ok else "FAIL",
                message=message,
                evidence=evidence,
            )
        )
        if not ok:
            self.errors.append(code)
            self.decision = "NO_GO"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
