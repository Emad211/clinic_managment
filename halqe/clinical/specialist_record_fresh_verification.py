"""Run and validate a fresh database reconciliation for final release.

The clinician packet is intentionally bound to the earlier verifier report used
for sampling.  Immediately before cutover we run the same verifier again against
the current database and source snapshot.  The fresh report is retained as a
private artifact and a normalized fingerprint is included in the final release
manifest, preventing stale database verification from being reused.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Optional

from django.core.management import call_command
from django.core.management.base import CommandError


_MAX_REPORT_BYTES = 20 * 1024 * 1024
_PASS_STATUSES = frozenset({"pass", "passed", "ok", "warning", "warn"})


@dataclass
class FreshImportVerificationResult:
    passed: bool
    report_path: Path
    report_sha256: Optional[str]
    semantic_fingerprint: Optional[str]
    detail: str
    payload: Optional[dict[str, Any]] = None



def run_fresh_import_verification(
    *,
    sqlite_path: str | Path,
    apply_report_path: str | Path,
    replay_report_path: str | Path,
    saved_verification_report: Mapping[str, Any],
    source_id: str,
    tenant_id: int,
    report_path: str | Path,
) -> FreshImportVerificationResult:
    """Execute ``verify_specialist_record_import`` and validate its fresh report."""
    target = Path(report_path).expanduser().absolute()
    stdout = StringIO()
    command_error: Optional[str] = None
    try:
        call_command(
            "verify_specialist_record_import",
            sqlite=str(Path(sqlite_path).expanduser().absolute()),
            apply_report=str(Path(apply_report_path).expanduser().absolute()),
            replay_report=str(Path(replay_report_path).expanduser().absolute()),
            source_id=source_id,
            tenant_id=int(tenant_id),
            report=str(target),
            stdout=stdout,
            verbosity=0,
        )
    except CommandError as exc:
        command_error = str(exc)

    if target.is_symlink() or not target.exists() or not target.is_file():
        return FreshImportVerificationResult(
            passed=False,
            report_path=target,
            report_sha256=None,
            semantic_fingerprint=None,
            detail=(
                "Fresh verifier did not produce a safe regular report"
                + (f": {command_error}" if command_error else ".")
            ),
        )
    mode = stat.S_IMODE(target.stat().st_mode)
    size = target.stat().st_size
    if mode & 0o077 or size <= 0 or size > _MAX_REPORT_BYTES:
        return FreshImportVerificationResult(
            passed=False,
            report_path=target,
            report_sha256=None,
            semantic_fingerprint=None,
            detail=(
                "Fresh verifier report is not owner-only or exceeds the size bound."
            ),
        )

    raw = target.read_bytes()
    report_hash = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return FreshImportVerificationResult(
            passed=False,
            report_path=target,
            report_sha256=report_hash,
            semantic_fingerprint=None,
            detail="Fresh verifier report is not valid UTF-8 JSON.",
        )
    if not isinstance(payload, dict):
        return FreshImportVerificationResult(
            passed=False,
            report_path=target,
            report_sha256=report_hash,
            semantic_fingerprint=None,
            detail="Fresh verifier report root is not a JSON object.",
        )

    fresh_checks = _status_map(payload.get("checks"))
    saved_checks = _status_map(saved_verification_report.get("checks"))
    summary = payload.get("summary")
    clean_go = (
        payload.get("decision") == "GO"
        and payload.get("source_id") == source_id
        and _integer_or_none(payload.get("tenant_id")) == int(tenant_id)
        and isinstance(summary, Mapping)
        and _integer_or_none(summary.get("failed")) == 0
        and bool(fresh_checks)
        and all(status in _PASS_STATUSES for status in fresh_checks.values())
    )
    same_source = (
        payload.get("source_file_sha256")
        == saved_verification_report.get("source_file_sha256")
        and payload.get("source_manifest_sha256")
        == saved_verification_report.get("source_manifest_sha256")
    )
    same_check_contract = bool(saved_checks) and fresh_checks == saved_checks
    semantic = {
        "decision": payload.get("decision"),
        "source_id": payload.get("source_id"),
        "tenant_id": payload.get("tenant_id"),
        "source_file_sha256": payload.get("source_file_sha256"),
        "source_manifest_sha256": payload.get("source_manifest_sha256"),
        "summary": payload.get("summary"),
        "checks": fresh_checks,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            semantic,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    failures = []
    if command_error:
        failures.append("verifier-command-returned-NO_GO")
    if not clean_go:
        failures.append("fresh-verifier-not-clean-GO")
    if not same_source:
        failures.append("fresh-source-hash-differs")
    if not same_check_contract:
        failures.append("fresh-check-status-map-differs")

    return FreshImportVerificationResult(
        passed=not failures,
        report_path=target,
        report_sha256=report_hash,
        semantic_fingerprint=fingerprint,
        detail=(
            "Fresh database reconciliation is GO and matches the saved verifier "
            "check contract."
            if not failures
            else "Fresh database reconciliation failed: " + ", ".join(failures)
        ),
        payload=payload,
    )



def _status_map(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for item in value:
        if not isinstance(item, Mapping):
            return {}
        key = str(item.get("key") or item.get("name") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        if not key or not status or key in result:
            return {}
        result[key] = status
    return result



def _integer_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
