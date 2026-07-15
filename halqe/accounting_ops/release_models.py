from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ReleaseCheck:
    code: str
    status: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountingReleaseManifest:
    decision: str
    release_id: str
    source_id: str
    tenant_id: int
    generated_at: str
    git_commit: str
    image_digest: str
    latest_dual_run_date: str | None
    artifact_sha256: dict[str, Any]
    fresh_import_report_sha256: str | None
    fresh_dual_run_sha256: dict[str, str]
    checks: list[ReleaseCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, code: str, ok: bool, message: str, **evidence: Any) -> None:
        self.checks.append(
            ReleaseCheck(
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
