"""Build the final hash-bound release manifest for specialist record cutover.

This verifier is deliberately redundant with earlier gates.  It reopens the
source snapshot and every report immediately before release, re-hashes them,
reruns the clinician sign-off verifier, and checks replay idempotency.  A GO
manifest therefore proves that no artifact changed between database verification,
human review and the release decision.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Optional

from clinical.specialist_record_clinician_signoff import (
    SpecialistRecordClinicianSignoffError,
    SpecialistRecordClinicianSignoffVerifier,
)


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_JSON_BYTES = 20 * 1024 * 1024
_MAX_SOURCE_BYTES = 100 * 1024 * 1024 * 1024


class SpecialistRecordReleaseManifestError(Exception):
    """Unsafe or unreadable artifact prevents a trustworthy release decision."""


@dataclass(frozen=True)
class ReleaseCheck:
    key: str
    status: str
    detail: str


@dataclass
class SpecialistRecordReleaseManifest:
    decision: str
    release_id: str
    source_id: str
    tenant_id: int
    generated_at: str
    git_commit: str
    image_digest: Optional[str]
    source_file_sha256: Optional[str]
    source_manifest_sha256: Optional[str]
    artifact_sha256: dict[str, str]
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]
    selected_patient_count: int
    discrepancy_count: int
    checks: list[ReleaseCheck] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [asdict(item) for item in self.checks]
        return payload


class SpecialistRecordReleaseManifestBuilder:
    """Revalidate and bind every release artifact into one immutable manifest."""

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
    ):
        self.paths = {
            "apply_report": Path(apply_report_path).expanduser().absolute(),
            "replay_report": Path(replay_report_path).expanduser().absolute(),
            "verification_report": Path(verification_report_path)
            .expanduser()
            .absolute(),
            "review_packet": Path(review_packet_path).expanduser().absolute(),
            "clinician_signoff_report": Path(clinician_signoff_report_path)
            .expanduser()
            .absolute(),
        }
        self.source_snapshot_path = (
            Path(source_snapshot_path).expanduser().absolute()
        )
        self.source_id = source_id.strip()
        self.tenant_id = int(tenant_id)
        self.git_commit = git_commit.strip().lower()
        self.image_digest = image_digest.strip().lower() if image_digest else None
        self.checks: list[ReleaseCheck] = []

    def run(self) -> SpecialistRecordReleaseManifest:
        self._validate_arguments()
        source_hash = self._hash_private_source(self.source_snapshot_path)
        payloads: dict[str, dict[str, Any]] = {}
        raw: dict[str, bytes] = {}
        artifact_hashes: dict[str, str] = {}
        for key, path in self.paths.items():
            payload, body = self._load_private_json(path, key)
            payloads[key] = payload
            raw[key] = body
            artifact_hashes[key] = hashlib.sha256(body).hexdigest()

        self._check_import_reports(
            apply=payloads["apply_report"],
            replay=payloads["replay_report"],
        )
        self._check_source_hash_chain(
            source_hash=source_hash,
            payloads=payloads,
        )
        self._check_verification_hash_chain(
            payloads=payloads,
            artifact_hashes=artifact_hashes,
        )
        self._check_clinician_signoff(
            payloads=payloads,
            artifact_hashes=artifact_hashes,
        )
        self._check_actual_scenario_coverage(payloads["review_packet"])

        failed = sum(item.status == "fail" for item in self.checks)
        warnings = sum(item.status == "warning" for item in self.checks)
        passed = sum(item.status == "pass" for item in self.checks)
        decision = "GO" if failed == 0 else "NO_GO"
        signoff = payloads["clinician_signoff_report"]
        manifest_hash = self._clean(payloads["apply_report"].get("source_manifest_sha256"))
        release_basis = {
            "source_id": self.source_id,
            "tenant_id": self.tenant_id,
            "git_commit": self.git_commit,
            "image_digest": self.image_digest,
            "source_file_sha256": source_hash,
            "source_manifest_sha256": manifest_hash,
            "artifact_sha256": artifact_hashes,
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
            source_id=self.source_id,
            tenant_id=self.tenant_id,
            generated_at=datetime.now(UTC).isoformat(),
            git_commit=self.git_commit,
            image_digest=self.image_digest,
            source_file_sha256=source_hash,
            source_manifest_sha256=manifest_hash,
            artifact_sha256=artifact_hashes,
            reviewed_by=self._clean(signoff.get("reviewed_by")),
            reviewed_at=self._clean(signoff.get("reviewed_at")),
            selected_patient_count=self._integer_or_zero(
                signoff.get("selected_patient_count")
            ),
            discrepancy_count=self._integer_or_zero(
                signoff.get("discrepancy_count")
            ),
            checks=self.checks,
            summary={"passed": passed, "warnings": warnings, "failed": failed},
        )

    # ---------------------------------------------------------------- inputs
    def _validate_arguments(self) -> None:
        if not self.source_id:
            raise SpecialistRecordReleaseManifestError("source_id is required")
        if self.tenant_id <= 0:
            raise SpecialistRecordReleaseManifestError(
                "tenant_id must be a positive integer"
            )
        if not _COMMIT_RE.fullmatch(self.git_commit):
            raise SpecialistRecordReleaseManifestError(
                "git_commit must be a full 40-character lowercase hexadecimal SHA"
            )
        if self.image_digest and not _IMAGE_DIGEST_RE.fullmatch(self.image_digest):
            raise SpecialistRecordReleaseManifestError(
                "image_digest must use sha256:<64 lowercase hex>"
            )

    def _load_private_json(
        self, path: Path, label: str
    ) -> tuple[dict[str, Any], bytes]:
        self._require_private_regular_file(path, label, _MAX_JSON_BYTES)
        body = path.read_bytes()
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpecialistRecordReleaseManifestError(
                f"{label} is not valid UTF-8 JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise SpecialistRecordReleaseManifestError(
                f"{label} JSON root must be an object"
            )
        return payload, body

    def _hash_private_source(self, path: Path) -> str:
        self._require_private_regular_file(path, "source_snapshot", _MAX_SOURCE_BYTES)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _require_private_regular_file(path: Path, label: str, maximum: int) -> None:
        if path.is_symlink():
            raise SpecialistRecordReleaseManifestError(
                f"Refusing to read {label} through a symlink: {path}"
            )
        if not path.exists() or not path.is_file():
            raise SpecialistRecordReleaseManifestError(
                f"{label} is missing or is not a regular file: {path}"
            )
        size = path.stat().st_size
        if size <= 0 or size > maximum:
            raise SpecialistRecordReleaseManifestError(
                f"{label} size is outside the allowed safety bound"
            )
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise SpecialistRecordReleaseManifestError(
                f"{label} must be owner-only; current mode is {mode:04o}"
            )

    # -------------------------------------------------------------- reports
    def _check_import_reports(
        self, *, apply: Mapping[str, Any], replay: Mapping[str, Any]
    ) -> None:
        identity_ok = all(
            item.get("source_id") == self.source_id
            and self._integer_or_none(item.get("tenant_id")) == self.tenant_id
            for item in (apply, replay)
        )
        self._record(
            "import_report_identity",
            identity_ok,
            "Apply and replay reports match source_id and tenant_id.",
            "Apply/replay report identity mismatch.",
        )
        status_ok = all(
            item.get("mode") == "apply"
            and item.get("transaction_status") == "committed"
            and not item.get("error")
            for item in (apply, replay)
        )
        self._record(
            "import_reports_committed",
            status_ok,
            "Apply and replay reports both describe committed transactions.",
            "Apply or replay report is not a clean committed apply run.",
        )

        replay_inserted = self._sum_table_field(replay, "inserted")
        self._record(
            "replay_zero_inserts",
            replay_inserted == 0,
            "Replay inserted zero target rows.",
            f"Replay reports {replay_inserted} inserted rows; idempotency is not proven.",
        )
        apply_manifest = self._clean(apply.get("source_manifest_sha256"))
        replay_manifest = self._clean(replay.get("source_manifest_sha256"))
        self._record(
            "apply_replay_manifest_match",
            bool(
                apply_manifest
                and _HASH_RE.fullmatch(apply_manifest)
                and apply_manifest == replay_manifest
            ),
            "Apply and replay reference the same source manifest.",
            "Apply/replay manifest hashes are missing, malformed or different.",
        )

    def _check_source_hash_chain(
        self,
        *,
        source_hash: str,
        payloads: Mapping[str, Mapping[str, Any]],
    ) -> None:
        mismatches = []
        for name, payload in payloads.items():
            reported = self._clean(payload.get("source_file_sha256"))
            if reported is not None and reported != source_hash:
                mismatches.append(name)
        # Every artifact in this release chain must carry the source hash.
        missing = [
            name
            for name, payload in payloads.items()
            if self._clean(payload.get("source_file_sha256")) is None
        ]
        self._record(
            "source_snapshot_hash_chain",
            not mismatches and not missing,
            "Every release artifact references the current source snapshot hash.",
            "Source hash mismatch/missing in: "
            + ", ".join(sorted(set(mismatches + missing))),
        )

        manifests = {
            self._clean(payload.get("source_manifest_sha256"))
            for payload in payloads.values()
        }
        manifests.discard(None)
        valid_manifest = len(manifests) == 1 and all(
            _HASH_RE.fullmatch(item) for item in manifests
        )
        self._record(
            "source_manifest_hash_chain",
            bool(valid_manifest),
            "All artifacts reference one valid source manifest hash.",
            "Release artifacts do not share one valid source manifest hash.",
        )

    def _check_verification_hash_chain(
        self,
        *,
        payloads: Mapping[str, Mapping[str, Any]],
        artifact_hashes: Mapping[str, str],
    ) -> None:
        verification = payloads["verification_report"]
        packet = payloads["review_packet"]
        decision_ok = verification.get("decision") == "GO"
        self._record(
            "verification_go",
            decision_ok,
            "Migration verification report is GO.",
            "Migration verification report is not GO.",
        )
        bound = self._clean(packet.get("verification_report_sha256"))
        self._record(
            "review_packet_verification_binding",
            bound == artifact_hashes["verification_report"],
            "Review packet is bound to the supplied verification report.",
            "Review packet verification hash is stale or incorrect.",
        )

    def _check_clinician_signoff(
        self,
        *,
        payloads: Mapping[str, Mapping[str, Any]],
        artifact_hashes: Mapping[str, str],
    ) -> None:
        try:
            fresh = SpecialistRecordClinicianSignoffVerifier(
                review_packet_path=self.paths["review_packet"],
                verification_report_path=self.paths["verification_report"],
                source_id=self.source_id,
                tenant_id=self.tenant_id,
            ).run()
        except SpecialistRecordClinicianSignoffError as exc:
            self._record(
                "fresh_clinician_verification",
                False,
                "",
                f"Cannot rerun clinician sign-off verifier: {exc}",
            )
            return
        self._record(
            "fresh_clinician_verification",
            fresh.decision == "GO",
            "Completed packet still passes clinician sign-off verification.",
            "Completed packet no longer passes clinician sign-off verification.",
        )

        saved = payloads["clinician_signoff_report"]
        saved_summary = saved.get("summary")
        saved_go = (
            saved.get("decision") == "GO"
            and isinstance(saved_summary, Mapping)
            and self._integer_or_none(saved_summary.get("failed")) == 0
        )
        self._record(
            "saved_clinician_go",
            saved_go,
            "Saved clinician sign-off report is GO with zero failures.",
            "Saved clinician sign-off report is not a clean GO.",
        )
        hashes_match = (
            saved.get("review_packet_sha256")
            == artifact_hashes["review_packet"]
            == fresh.review_packet_sha256
            and saved.get("verification_report_sha256")
            == artifact_hashes["verification_report"]
            == fresh.verification_report_sha256
        )
        self._record(
            "clinician_signoff_artifact_binding",
            hashes_match,
            "Saved sign-off is bound to the current packet and verification report.",
            "Packet or verification report changed after clinician sign-off.",
        )
        counts_match = (
            self._integer_or_none(saved.get("selected_patient_count"))
            == fresh.selected_patient_count
            and self._integer_or_none(saved.get("discrepancy_count"))
            == fresh.discrepancy_count
        )
        self._record(
            "clinician_signoff_count_binding",
            counts_match,
            "Saved sign-off patient/discrepancy counts match a fresh verification.",
            "Saved sign-off counts differ from the current packet.",
        )

    def _check_actual_scenario_coverage(self, packet: Mapping[str, Any]) -> None:
        scenarios = packet.get("scenarios")
        coverage = packet.get("coverage")
        patients = packet.get("patients")
        per_scenario = max(1, self._integer_or_zero(packet.get("per_scenario")))
        if not isinstance(scenarios, list) or not isinstance(coverage, Mapping) or not isinstance(patients, list):
            self._record(
                "actual_scenario_coverage",
                False,
                "",
                "Review packet scenario/coverage/patient structures are malformed.",
            )
            return
        actual: dict[str, set[int]] = {}
        for patient in patients:
            if not isinstance(patient, Mapping):
                continue
            target_id = self._integer_or_none(patient.get("target_patient_link_id"))
            if target_id is None:
                continue
            for scenario in patient.get("scenarios") or []:
                if isinstance(scenario, Mapping):
                    key = self._clean(scenario.get("key"))
                    if key:
                        actual.setdefault(key, set()).add(target_id)
        failures = []
        for scenario in scenarios:
            if not isinstance(scenario, Mapping):
                failures.append("<malformed>")
                continue
            key = self._clean(scenario.get("key"))
            row = coverage.get(key) if key else None
            if not key or not isinstance(row, Mapping):
                failures.append(key or "<missing-key>")
                continue
            eligible = self._integer_or_zero(row.get("eligible_patients"))
            if eligible <= 0:
                continue
            required = min(per_scenario, eligible)
            actual_count = len(actual.get(key, set()))
            reported = self._integer_or_zero(row.get("selected_patients"))
            if actual_count < required or reported != actual_count:
                failures.append(
                    f"{key}:required={required},actual={actual_count},reported={reported}"
                )
        self._record(
            "actual_scenario_coverage",
            not failures,
            "Patient scenario assignments independently satisfy coverage counts.",
            "Scenario coverage is asserted but not demonstrated by patients: "
            + ", ".join(failures[:10]),
        )

    # ---------------------------------------------------------------- helpers
    def _record(
        self,
        key: str,
        passed: bool,
        pass_detail: str,
        fail_detail: str,
    ) -> None:
        self.checks.append(
            ReleaseCheck(
                key=key,
                status="pass" if passed else "fail",
                detail=pass_detail if passed else fail_detail,
            )
        )

    @staticmethod
    def _sum_table_field(report: Mapping[str, Any], field: str) -> int:
        tables = report.get("tables")
        if not isinstance(tables, Mapping):
            return -1
        total = 0
        for stats in tables.values():
            if not isinstance(stats, Mapping):
                return -1
            try:
                total += int(stats.get(field) or 0)
            except (TypeError, ValueError):
                return -1
        return total

    @staticmethod
    def _clean(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _integer_or_none(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer_or_zero(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
