"""Public final release manifest with a mandatory fresh database reconciliation.

The artifact-chain implementation lives in
:mod:`clinical._specialist_record_release_manifest_core`.  This facade adds the
last cutover-time invariant: after validating all saved artifacts and clinician
approval, rerun ``verify_specialist_record_import`` against the current database
and exact SQLite snapshot.  The private fresh report and its normalized semantic
fingerprint are bound into the final deterministic release id.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Optional

from clinical import _specialist_record_release_manifest_core as _core
from clinical.specialist_record_fresh_verification import (
    run_fresh_import_verification,
)


SpecialistRecordReleaseManifestError = _core.SpecialistRecordReleaseManifestError
ReleaseCheck = _core.ReleaseCheck


@dataclass
class SpecialistRecordReleaseManifest(_core.SpecialistRecordReleaseManifest):
    fresh_verification_report_sha256: Optional[str] = None
    fresh_verification_semantic_fingerprint: Optional[str] = None


class SpecialistRecordReleaseManifestBuilder(
    _core.SpecialistRecordReleaseManifestBuilder
):
    """Artifact-chain builder that also proves the live database is still GO."""

    def __init__(
        self,
        *,
        source_snapshot_path: str | Path,
        apply_report_path: str | Path,
        replay_report_path: str | Path,
        verification_report_path: str | Path,
        review_packet_path: str | Path,
        clinician_signoff_report_path: str | Path,
        source_id: str,
        tenant_id: int,
        git_commit: str,
        image_digest: Optional[str] = None,
        fresh_verification_report_path: str | Path | None = None,
    ):
        super().__init__(
            source_snapshot_path=source_snapshot_path,
            apply_report_path=apply_report_path,
            replay_report_path=replay_report_path,
            verification_report_path=verification_report_path,
            review_packet_path=review_packet_path,
            clinician_signoff_report_path=clinician_signoff_report_path,
            source_id=source_id,
            tenant_id=tenant_id,
            git_commit=git_commit,
            image_digest=image_digest,
        )
        verification_path = Path(verification_report_path).expanduser().absolute()
        self.fresh_verification_report_path = (
            Path(fresh_verification_report_path).expanduser().absolute()
            if fresh_verification_report_path is not None
            else verification_path.with_name(
                verification_path.stem + ".fresh-verification.json"
            )
        )

    def run(self) -> SpecialistRecordReleaseManifest:
        base = super().run()
        saved_verification, _raw = self._load_private_json(
            self.paths["verification_report"],
            "verification_report",
        )
        fresh = run_fresh_import_verification(
            sqlite_path=self.source_snapshot_path,
            apply_report_path=self.paths["apply_report"],
            replay_report_path=self.paths["replay_report"],
            saved_verification_report=saved_verification,
            source_id=self.source_id,
            tenant_id=self.tenant_id,
            report_path=self.fresh_verification_report_path,
        )
        self.checks.append(
            ReleaseCheck(
                key="fresh_database_reconciliation",
                status="pass" if fresh.passed else "fail",
                detail=fresh.detail,
            )
        )

        artifact_hashes = dict(base.artifact_sha256)
        if fresh.report_sha256:
            artifact_hashes["fresh_verification_report"] = fresh.report_sha256

        failed = sum(item.status == "fail" for item in self.checks)
        warnings = sum(item.status == "warning" for item in self.checks)
        passed = sum(item.status == "pass" for item in self.checks)
        decision = "GO" if failed == 0 else "NO_GO"
        release_basis = {
            "artifact_chain_release_id": base.release_id,
            "fresh_verification_report_sha256": fresh.report_sha256,
            "fresh_verification_semantic_fingerprint": fresh.semantic_fingerprint,
        }
        release_id = hashlib.sha256(
            json.dumps(
                release_basis,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        return SpecialistRecordReleaseManifest(
            decision=decision,
            release_id=release_id,
            source_id=base.source_id,
            tenant_id=base.tenant_id,
            generated_at=base.generated_at,
            git_commit=base.git_commit,
            image_digest=base.image_digest,
            source_file_sha256=base.source_file_sha256,
            source_manifest_sha256=base.source_manifest_sha256,
            artifact_sha256=artifact_hashes,
            reviewed_by=base.reviewed_by,
            reviewed_at=base.reviewed_at,
            selected_patient_count=base.selected_patient_count,
            discrepancy_count=base.discrepancy_count,
            checks=self.checks,
            summary={"passed": passed, "warnings": warnings, "failed": failed},
            fresh_verification_report_sha256=fresh.report_sha256,
            fresh_verification_semantic_fingerprint=fresh.semantic_fingerprint,
        )


__all__ = [
    "SpecialistRecordReleaseManifestError",
    "ReleaseCheck",
    "SpecialistRecordReleaseManifest",
    "SpecialistRecordReleaseManifestBuilder",
]
