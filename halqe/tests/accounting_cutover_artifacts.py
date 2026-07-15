from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
from typing import Any

from platform_core.backup_canonical import file_sha256


SOURCE_ID = "cutover-signoff-source"
TENANT_ID = 73
_SCOPES = ("all", "morning", "evening", "night")


def write_private_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return path


def build_cutover_artifacts(
    root: Path,
    *,
    days: int = 2,
    omit: str | None = None,
    restore_decision: str = "VERIFIED",
    import_decision: str = "VERIFIED",
    discrepancy_status: str | None = None,
    include_sensitive_key: bool = False,
) -> dict[str, Any]:
    import_report = write_private_json(
        root / "import-verification.json",
        {
            "decision": import_decision,
            "source_id": SOURCE_ID,
            "tenant_id": TENANT_ID,
            "errors": [] if import_decision == "VERIFIED" else ["ledger_coverage"],
            "checks": [{
                "code": "ledger_coverage",
                "status": "PASS" if import_decision == "VERIFIED" else "FAIL",
            }],
        },
    )
    restore_report = write_private_json(
        root / "restore-verification.json",
        {
            "decision": restore_decision,
            "errors": [] if restore_decision == "VERIFIED" else ["database_digest"],
            "checks": [{
                "code": "database_digest",
                "status": "PASS" if restore_decision == "VERIFIED" else "FAIL",
            }],
        },
    )

    dual_paths: list[Path] = []
    dual_hashes: dict[str, str] = {}
    start = date(2026, 7, 1)
    for offset in range(days):
        day = start + timedelta(days=offset)
        daily_file_hash = f"{offset + 1:064x}"[-64:]
        daily_manifest_hash = f"{offset + 101:064x}"[-64:]
        for scope in _SCOPES:
            key = f"{day.isoformat()}:{scope}"
            if omit == key:
                continue
            financial = {
                "totals": {
                    "invoice_count": offset + 1,
                    "invoice_amount": 100000 * (offset + 1),
                    "payment_paid_count": offset + 1,
                },
                "by_shift": {scope: {"invoice_count": offset + 1}},
            }
            payroll = {
                "summary": {
                    "staff_count": 1,
                    "gross_salary": 25000.0,
                    "tax_amount": 2500.0,
                    "net_salary": 22500.0,
                },
                "rows": {
                    "1": {
                        "staff_type": "doctor",
                        "gross_salary": 25000.0,
                        "tax_amount": 2500.0,
                        "net_salary": 22500.0,
                    }
                },
            }
            path = write_private_json(
                root / f"dual-{day.isoformat()}-{scope}.json",
                {
                    "decision": "GO",
                    "source_id": SOURCE_ID,
                    "tenant_id": TENANT_ID,
                    "date_from": day.isoformat(),
                    "date_to": day.isoformat(),
                    "shift": None if scope == "all" else scope,
                    "source_file_sha256": daily_file_hash,
                    "source_manifest_sha256": daily_manifest_hash,
                    "financial_source": financial,
                    "financial_target": financial,
                    "payroll_source": payroll,
                    "payroll_target": payroll,
                    "differences": [],
                    "errors": [],
                },
            )
            dual_paths.append(path)
            dual_hashes[key] = file_sha256(path)

    reviewed_at = "2026-07-03T10:00:00+03:30"
    human_checks = {
        "cash": {"status": "approved", "reviewer": "cash-reviewer", "reviewed_at": reviewed_at},
        "insurance": {"status": "approved", "reviewer": "insurance-reviewer", "reviewed_at": reviewed_at},
        "payroll": {"status": "approved", "reviewer": "payroll-reviewer", "reviewed_at": reviewed_at},
        "invoice_samples": {
            "status": "approved",
            "reviewer": "invoice-reviewer",
            "reviewed_at": reviewed_at,
            "sample_count": 12,
        },
    }
    discrepancies = []
    if discrepancy_status:
        discrepancies = [{
            "code": "sample-discrepancy",
            "status": discrepancy_status,
            "owner": "finance-owner",
            "resolution": "reconciled" if discrepancy_status == "fixed" else "pending",
        }]
    packet_payload: dict[str, Any] = {
        "version": 1,
        "source_id": SOURCE_ID,
        "tenant_id": TENANT_ID,
        "reviewed_by": "finance-lead",
        "reviewed_at": reviewed_at,
        "decision": "approved",
        "required_consecutive_days": days,
        "artifact_sha256": {
            "import_verification": file_sha256(import_report),
            "restore_verification": file_sha256(restore_report),
            "dual_run_reports": dual_hashes,
        },
        "human_checks": human_checks,
        "discrepancies": discrepancies,
    }
    if include_sensitive_key:
        packet_payload["phone_number"] = "redacted-placeholder"
    packet = write_private_json(root / "signoff-packet.json", packet_payload)
    return {
        "packet": packet,
        "import_report": import_report,
        "restore_report": restore_report,
        "dual_reports": dual_paths,
    }
