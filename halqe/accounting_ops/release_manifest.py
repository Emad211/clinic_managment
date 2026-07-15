from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from accounting_ops.dual_run_service import compare_accounting_dual_run
from accounting_ops.import_verifier import AccountingImportVerifier
from accounting_ops.release_artifacts import load_release_artifacts
from accounting_ops.release_models import AccountingReleaseManifest
from clinical.secure_report_io import (
    SecureReportIOError,
    ensure_distinct_artifact_paths,
    write_private_text,
)
from platform_core.backup_canonical import file_sha256


class AccountingReleaseManifestError(RuntimeError):
    pass


_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPES = ("all", "morning", "evening", "night")


def _render(payload: dict) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        default=str,
    ) + "\n"


def build_accounting_release_manifest(
    *,
    import_sqlite_path: str | Path,
    latest_dual_run_sqlite_path: str | Path,
    packet_path: str | Path,
    signoff_report_path: str | Path,
    import_verification_path: str | Path,
    restore_verification_path: str | Path,
    dual_run_report_paths: Iterable[str | Path],
    backup_manifest_path: str | Path,
    backup_file_path: str | Path,
    source_id: str,
    tenant_id: int,
    git_commit: str,
    image_digest: str,
    fresh_import_report_path: str | Path,
    fresh_dual_run_directory: str | Path,
) -> AccountingReleaseManifest:
    if not _COMMIT.fullmatch(git_commit):
        raise AccountingReleaseManifestError("git_commit must be a lowercase full SHA")
    if not _IMAGE.fullmatch(image_digest):
        raise AccountingReleaseManifestError(
            "image_digest must be an immutable sha256 container digest"
        )
    import_sqlite = Path(import_sqlite_path).expanduser().absolute()
    latest_sqlite = Path(latest_dual_run_sqlite_path).expanduser().absolute()
    fresh_import_path = Path(fresh_import_report_path).expanduser().absolute()
    fresh_directory = Path(fresh_dual_run_directory).expanduser().absolute()
    saved_dual_paths = [Path(item).expanduser().absolute() for item in dual_run_report_paths]
    fresh_paths = {
        scope: fresh_directory / f"fresh-dual-{scope}.json"
        for scope in _SCOPES
    }
    try:
        ensure_distinct_artifact_paths(
            inputs={
                "import_sqlite": import_sqlite,
                "latest_dual_sqlite": latest_sqlite,
                "packet": packet_path,
                "signoff_report": signoff_report_path,
                "import_verification": import_verification_path,
                "restore_verification": restore_verification_path,
                "backup_manifest": backup_manifest_path,
                "backup_file": backup_file_path,
                **{
                    f"saved_dual_{index}": path
                    for index, path in enumerate(saved_dual_paths)
                },
            },
            outputs={
                "fresh_import": fresh_import_path,
                **{f"fresh_dual_{scope}": path for scope, path in fresh_paths.items()},
            },
        )
    except SecureReportIOError as exc:
        raise AccountingReleaseManifestError(str(exc)) from exc

    artifacts = load_release_artifacts(
        packet_path=packet_path,
        signoff_report_path=signoff_report_path,
        import_verification_path=import_verification_path,
        restore_verification_path=restore_verification_path,
        dual_run_report_paths=saved_dual_paths,
        backup_manifest_path=backup_manifest_path,
        backup_file_path=backup_file_path,
        source_id=source_id,
        tenant_id=tenant_id,
    )
    manifest = AccountingReleaseManifest(
        decision="GO",
        release_id="",
        source_id=source_id,
        tenant_id=int(tenant_id),
        generated_at=datetime.now(UTC).isoformat(),
        git_commit=git_commit,
        image_digest=image_digest,
        latest_dual_run_date=artifacts.latest_date.isoformat(),
        artifact_sha256=dict(artifacts.hashes),
        fresh_import_report_sha256=None,
        fresh_dual_run_sha256={},
    )
    manifest.add(
        "signed_evidence_chain",
        artifacts.saved_signoff.get("decision") == "GO",
        "Saved and recomputed accounting sign-off evidence must remain GO",
    )
    manifest.add(
        "import_source_identity",
        import_sqlite.is_file()
        and not import_sqlite.is_symlink()
        and file_sha256(import_sqlite)
        == artifacts.import_verification.get("source_file_sha256"),
        "Fresh import verification must use the exact historically verified SQLite source",
    )

    fresh_import = AccountingImportVerifier(
        sqlite_path=import_sqlite,
        source_id=source_id,
        tenant_id=int(tenant_id),
    ).run()
    write_private_text(fresh_import_path, _render(fresh_import.to_dict()))
    fresh_import_sha = file_sha256(fresh_import_path)
    manifest.fresh_import_report_sha256 = fresh_import_sha
    manifest.add(
        "fresh_import_verification",
        fresh_import.decision == "VERIFIED"
        and not fresh_import.errors
        and all(item.status == "PASS" for item in fresh_import.checks),
        "Current PostgreSQL accounting import must still verify against the original source",
        errors=list(fresh_import.errors),
    )

    latest_day = artifacts.latest_date.isoformat()
    saved_latest = {
        key.split(":", 1)[1]: payload
        for key, payload in artifacts.dual_reports.items()
        if key.startswith(latest_day + ":")
    }
    latest_file_sha = file_sha256(latest_sqlite) if latest_sqlite.is_file() else ""
    latest_snapshot_ok = set(saved_latest) == set(_SCOPES) and all(
        payload.get("source_file_sha256") == latest_file_sha
        for payload in saved_latest.values()
    )
    manifest.add(
        "latest_dual_run_snapshot_identity",
        latest_snapshot_ok,
        "Fresh dual-runs must use the exact SQLite snapshot signed for the latest day",
    )

    fresh_dual_ok = latest_snapshot_ok
    fresh_dual_hashes: dict[str, str] = {}
    for scope in _SCOPES:
        shift = None if scope == "all" else scope
        fresh = compare_accounting_dual_run(
            sqlite_path=latest_sqlite,
            source_id=source_id,
            tenant_id=int(tenant_id),
            date_from=latest_day,
            date_to=latest_day,
            shift=shift,
        )
        path = fresh_paths[scope]
        write_private_text(path, _render(fresh.to_dict()))
        digest = file_sha256(path)
        fresh_dual_hashes[scope] = digest
        saved = saved_latest.get(scope, {})
        fresh_dual_ok = fresh_dual_ok and (
            fresh.decision == "GO"
            and not fresh.differences
            and not fresh.errors
            and fresh.source_file_sha256 == saved.get("source_file_sha256")
            and fresh.source_manifest_sha256 == saved.get("source_manifest_sha256")
        )
    manifest.fresh_dual_run_sha256 = dict(sorted(fresh_dual_hashes.items()))
    manifest.add(
        "fresh_latest_dual_run",
        fresh_dual_ok,
        "Latest all/morning/evening/night scopes must still be exact GO at manifest time",
    )

    manifest.artifact_sha256["fresh_import_verification"] = fresh_import_sha
    manifest.artifact_sha256["fresh_dual_run_reports"] = manifest.fresh_dual_run_sha256
    release_basis = {
        "source_id": source_id,
        "tenant_id": int(tenant_id),
        "git_commit": git_commit,
        "image_digest": image_digest,
        "latest_dual_run_date": latest_day,
        "artifact_sha256": manifest.artifact_sha256,
        "check_status": {item.code: item.status for item in manifest.checks},
    }
    manifest.release_id = hashlib.sha256(
        json.dumps(
            release_basis,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest.decision = "GO" if not manifest.errors else "NO_GO"
    return manifest
