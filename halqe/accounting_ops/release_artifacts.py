from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from accounting_ops.cutover_signoff import (
    AccountingCutoverSignoffError,
    _dual_key,
    _private_json,
    verify_accounting_cutover_signoff,
)
from platform_core.backup_canonical import file_sha256
from platform_core.backup_manifest import (
    load_backup_manifest,
    validate_backup_artifact,
)


@dataclass(frozen=True)
class ReleaseArtifacts:
    packet: dict[str, Any]
    saved_signoff: dict[str, Any]
    import_verification: dict[str, Any]
    restore_verification: dict[str, Any]
    dual_reports: dict[str, dict[str, Any]]
    hashes: dict[str, Any]
    latest_date: date


def load_release_artifacts(
    *,
    packet_path: str | Path,
    signoff_report_path: str | Path,
    import_verification_path: str | Path,
    restore_verification_path: str | Path,
    dual_run_report_paths: Iterable[str | Path],
    backup_manifest_path: str | Path,
    backup_file_path: str | Path,
    source_id: str,
    tenant_id: int,
) -> ReleaseArtifacts:
    packet, packet_sha = _private_json(packet_path, label="signoff_packet")
    saved_signoff, signoff_sha = _private_json(
        signoff_report_path, label="signoff_report"
    )
    import_report, import_sha = _private_json(
        import_verification_path, label="import_verification"
    )
    restore_report, restore_sha = _private_json(
        restore_verification_path, label="restore_verification"
    )
    paths = [Path(item).expanduser().absolute() for item in dual_run_report_paths]
    recomputed = verify_accounting_cutover_signoff(
        packet_path=packet_path,
        import_verification_path=import_verification_path,
        restore_verification_path=restore_verification_path,
        dual_run_report_paths=paths,
        source_id=source_id,
        tenant_id=tenant_id,
    )
    if recomputed.decision != "GO":
        raise AccountingCutoverSignoffError(
            "Recomputed accounting sign-off is not GO: " + ", ".join(recomputed.errors)
        )
    if saved_signoff.get("decision") != "GO":
        raise AccountingCutoverSignoffError("Saved accounting sign-off report is not GO")
    if saved_signoff.get("source_id") != source_id:
        raise AccountingCutoverSignoffError("Saved sign-off source-id mismatch")
    if int(saved_signoff.get("tenant_id") or 0) != int(tenant_id):
        raise AccountingCutoverSignoffError("Saved sign-off tenant mismatch")
    if saved_signoff.get("artifact_sha256") != recomputed.artifact_sha256:
        raise AccountingCutoverSignoffError(
            "Saved sign-off artifact hashes do not match recomputed evidence"
        )

    dual_reports: dict[str, dict[str, Any]] = {}
    dual_hashes: dict[str, str] = {}
    for path in paths:
        payload, digest = _private_json(path, label="dual_run_report")
        key = _dual_key(payload)
        if key in dual_reports:
            raise AccountingCutoverSignoffError(f"Duplicate release dual-run scope: {key}")
        dual_reports[key] = payload
        dual_hashes[key] = digest
    observed = sorted({date.fromisoformat(key.split(":", 1)[0]) for key in dual_reports})
    if not observed:
        raise AccountingCutoverSignoffError("Release requires dual-run reports")

    manifest = load_backup_manifest(backup_manifest_path)
    backup = validate_backup_artifact(backup_file_path)
    expected_backup = manifest.get("backup", {})
    if (
        expected_backup.get("sha256") != backup.sha256
        or int(expected_backup.get("size_bytes") or -1) != backup.size_bytes
        or expected_backup.get("format") != backup.format
    ):
        raise AccountingCutoverSignoffError(
            "Backup bytes do not match the captured backup manifest"
        )
    if restore_report.get("backup_sha256") not in (None, backup.sha256):
        raise AccountingCutoverSignoffError(
            "Restore verification refers to a different backup artifact"
        )

    hashes = {
        "signoff_packet": packet_sha,
        "signoff_report": signoff_sha,
        "import_verification": import_sha,
        "restore_verification": restore_sha,
        "dual_run_reports": dict(sorted(dual_hashes.items())),
        "backup_manifest": file_sha256(Path(backup_manifest_path)),
        "backup_file": backup.sha256,
    }
    return ReleaseArtifacts(
        packet=packet,
        saved_signoff=saved_signoff,
        import_verification=import_report,
        restore_verification=restore_report,
        dual_reports=dual_reports,
        hashes=hashes,
        latest_date=observed[-1],
    )
