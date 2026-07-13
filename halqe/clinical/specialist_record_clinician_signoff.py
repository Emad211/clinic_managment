"""Fail-closed verifier for the final clinician record-migration sign-off.

The migration verifier proves database integrity.  The clinician review packet
proves that a deterministic sample has been rendered and compared by a human.
This module binds those two artifacts and emits one release-level GO/NO_GO
result without writing any clinical or accounting data.

The input packet is intentionally pseudonymous.  Direct patient identity keys
are rejected so the sign-off artifact can be retained with the migration change
record without becoming a second uncontrolled patient registry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Optional
from uuid import UUID


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
_PASS_STATUSES = frozenset({"pass", "passed", "ok", "warning", "warn"})
_FORBIDDEN_IDENTITY_KEYS = frozenset(
    {
        "national_id",
        "phone_number",
        "full_name",
        "patient_name",
        "first_name",
        "last_name",
        "family_name",
        "address",
        "birthdate",
        "date_of_birth",
    }
)
_ALLOWED_SEVERITIES = frozenset({"minor", "major", "critical"})
_ALLOWED_DISPOSITIONS = frozenset(
    {"fixed", "accepted_risk", "false_positive", "deferred"}
)


class SpecialistRecordClinicianSignoffError(Exception):
    """Artifact-level error that prevents a trustworthy sign-off decision."""


@dataclass(frozen=True)
class SignoffCheck:
    key: str
    status: str
    detail: str


@dataclass
class ClinicianSignoffResult:
    decision: str
    source_id: str
    tenant_id: int
    generated_at: str
    review_packet_sha256: str
    verification_report_sha256: str
    source_file_sha256: Optional[str]
    source_manifest_sha256: Optional[str]
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]
    selected_patient_count: int
    covered_scenario_count: int
    discrepancy_count: int
    checks: list[SignoffCheck] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [asdict(item) for item in self.checks]
        return payload


class SpecialistRecordClinicianSignoffVerifier:
    """Validate a completed clinician packet against the exact GO report.

    Content problems produce a normal ``NO_GO`` result.  Unreadable, unsafe or
    malformed artifacts raise ``SpecialistRecordClinicianSignoffError`` because
    no meaningful review decision can be made from them.
    """

    def __init__(
        self,
        *,
        review_packet_path: str | Path,
        verification_report_path: str | Path,
        source_id: str,
        tenant_id: int,
    ):
        self.review_packet_path = Path(review_packet_path).expanduser().absolute()
        self.verification_report_path = (
            Path(verification_report_path).expanduser().absolute()
        )
        self.source_id = source_id.strip()
        self.tenant_id = int(tenant_id)
        self.checks: list[SignoffCheck] = []

    def run(self) -> ClinicianSignoffResult:
        self._validate_arguments()
        packet, packet_raw = self._load_private_json(
            self.review_packet_path, "clinician review packet"
        )
        verification, verification_raw = self._load_private_json(
            self.verification_report_path, "migration verification report"
        )
        packet_hash = hashlib.sha256(packet_raw).hexdigest()
        verification_hash = hashlib.sha256(verification_raw).hexdigest()

        self._check_identity_and_binding(
            packet=packet,
            verification=verification,
            verification_hash=verification_hash,
        )
        self._check_verification_contract(verification)
        self._check_phi_minimization(packet)
        covered_scenarios = self._check_scenario_coverage(packet)
        selected_patients = self._check_patient_reviews(packet)
        signoff = self._check_signoff(packet)
        discrepancy_count = self._check_discrepancies(signoff)
        self._check_warning_acknowledgement(packet, signoff)

        failed = sum(item.status == "fail" for item in self.checks)
        warnings = sum(item.status == "warning" for item in self.checks)
        passed = sum(item.status == "pass" for item in self.checks)
        decision = "GO" if failed == 0 else "NO_GO"

        return ClinicianSignoffResult(
            decision=decision,
            source_id=self.source_id,
            tenant_id=self.tenant_id,
            generated_at=datetime.now(UTC).isoformat(),
            review_packet_sha256=packet_hash,
            verification_report_sha256=verification_hash,
            source_file_sha256=self._string_or_none(
                packet.get("source_file_sha256")
            ),
            source_manifest_sha256=self._string_or_none(
                packet.get("source_manifest_sha256")
            ),
            reviewed_by=self._clean(signoff.get("reviewed_by")),
            reviewed_at=self._clean(signoff.get("reviewed_at")),
            selected_patient_count=selected_patients,
            covered_scenario_count=covered_scenarios,
            discrepancy_count=discrepancy_count,
            checks=self.checks,
            summary={"passed": passed, "warnings": warnings, "failed": failed},
        )

    # ------------------------------------------------------------------ files
    def _validate_arguments(self) -> None:
        if not _SOURCE_ID_RE.fullmatch(self.source_id):
            raise SpecialistRecordClinicianSignoffError(
                "source_id must use only letters, digits and . _ : / -"
            )
        if self.tenant_id <= 0:
            raise SpecialistRecordClinicianSignoffError(
                "tenant_id must be a positive integer"
            )

    def _load_private_json(
        self, path: Path, label: str
    ) -> tuple[dict[str, Any], bytes]:
        if path.is_symlink():
            raise SpecialistRecordClinicianSignoffError(
                f"Refusing to read {label} through a symlink: {path}"
            )
        if not path.exists() or not path.is_file():
            raise SpecialistRecordClinicianSignoffError(
                f"{label.capitalize()} is missing or not a regular file: {path}"
            )
        size = path.stat().st_size
        if size <= 0 or size > _MAX_ARTIFACT_BYTES:
            raise SpecialistRecordClinicianSignoffError(
                f"{label.capitalize()} size is outside the 1..20 MiB safety limit."
            )
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise SpecialistRecordClinicianSignoffError(
                f"{label.capitalize()} must be owner-only (0600-compatible); "
                f"current mode is {mode:04o}."
            )
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpecialistRecordClinicianSignoffError(
                f"{label.capitalize()} is not valid UTF-8 JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise SpecialistRecordClinicianSignoffError(
                f"{label.capitalize()} root must be a JSON object."
            )
        return payload, raw

    # -------------------------------------------------------------- base bind
    def _check_identity_and_binding(
        self,
        *,
        packet: Mapping[str, Any],
        verification: Mapping[str, Any],
        verification_hash: str,
    ) -> None:
        packet_identity = (
            packet.get("source_id") == self.source_id
            and self._integer_or_none(packet.get("tenant_id")) == self.tenant_id
        )
        verification_identity = (
            verification.get("source_id") == self.source_id
            and self._integer_or_none(verification.get("tenant_id"))
            == self.tenant_id
        )
        self._record(
            "artifact_identity",
            packet_identity and verification_identity,
            "Both artifacts match the requested source_id and tenant_id.",
            "Artifact source_id/tenant_id does not match the command arguments.",
        )

        bound_hash = self._clean(packet.get("verification_report_sha256"))
        self._record(
            "verification_report_binding",
            bound_hash == verification_hash,
            "Review packet is cryptographically bound to this verifier report.",
            "Review packet verification_report_sha256 does not match the supplied report.",
        )

        packet_file_hash = self._clean(packet.get("source_file_sha256"))
        packet_manifest = self._clean(packet.get("source_manifest_sha256"))
        verification_file_hash = self._clean(verification.get("source_file_sha256"))
        verification_manifest = self._clean(
            verification.get("source_manifest_sha256")
        )
        hashes_valid = all(
            value is not None and _HASH_RE.fullmatch(value)
            for value in (
                packet_file_hash,
                packet_manifest,
                verification_file_hash,
                verification_manifest,
            )
        )
        hashes_match = (
            packet_file_hash == verification_file_hash
            and packet_manifest == verification_manifest
        )
        self._record(
            "source_hash_binding",
            bool(hashes_valid and hashes_match),
            "Packet and verifier report reference the same valid source file and manifest hashes.",
            "Source file/manifest hashes are missing, malformed or inconsistent.",
        )

    def _check_verification_contract(self, verification: Mapping[str, Any]) -> None:
        self._record(
            "verification_decision",
            verification.get("decision") == "GO",
            "Underlying migration verifier decision is GO.",
            "Underlying migration verifier is not GO.",
        )
        summary = verification.get("summary")
        summary_ok = (
            isinstance(summary, Mapping)
            and self._integer_or_none(summary.get("failed")) == 0
        )
        self._record(
            "verification_failed_count",
            summary_ok,
            "Underlying verifier reports zero failed checks.",
            "Verifier summary is missing or reports failed checks.",
        )

        checks = verification.get("checks")
        if not isinstance(checks, list) or not checks:
            self._record(
                "verification_checks_present",
                False,
                "",
                "Verifier report has no explicit check list.",
            )
            return
        bad = []
        for item in checks:
            if not isinstance(item, Mapping):
                bad.append("<malformed>")
                continue
            status = str(item.get("status") or "").strip().lower()
            if status not in _PASS_STATUSES:
                bad.append(str(item.get("key") or item.get("name") or "<unknown>"))
        self._record(
            "verification_checks_present",
            True,
            f"Verifier report contains {len(checks)} explicit checks.",
            "",
        )
        self._record(
            "verification_checks_nonfailing",
            not bad,
            "All verifier checks are pass/warning.",
            "Verifier contains non-passing checks: " + ", ".join(bad[:10]),
        )

    # ------------------------------------------------------------ PHI guard
    def _check_phi_minimization(self, packet: Mapping[str, Any]) -> None:
        found: list[str] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    normalized = str(key).strip().lower()
                    child_path = f"{path}.{key}" if path else str(key)
                    if normalized in _FORBIDDEN_IDENTITY_KEYS:
                        found.append(child_path)
                    walk(child, child_path)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{path}[{index}]")

        walk(packet, "")
        self._record(
            "phi_minimized_packet",
            not found,
            "Packet contains no forbidden direct-identity fields.",
            "Packet contains forbidden identity fields: " + ", ".join(found[:10]),
        )

    # ----------------------------------------------------------- coverage
    def _check_scenario_coverage(self, packet: Mapping[str, Any]) -> int:
        scenarios = packet.get("scenarios")
        coverage = packet.get("coverage")
        if not isinstance(scenarios, list) or not scenarios:
            self._record(
                "scenario_catalog",
                False,
                "",
                "Review packet has no scenario catalog.",
            )
            return 0
        scenario_keys: list[str] = []
        for item in scenarios:
            if isinstance(item, Mapping):
                key = self._clean(item.get("key"))
                if key:
                    scenario_keys.append(key)
        unique = len(scenario_keys) == len(set(scenario_keys)) == len(scenarios)
        self._record(
            "scenario_catalog",
            unique,
            f"Scenario catalog contains {len(scenario_keys)} unique keys.",
            "Scenario catalog contains missing or duplicate keys.",
        )

        if not isinstance(coverage, Mapping):
            self._record(
                "scenario_coverage",
                False,
                "",
                "Review packet coverage is missing or malformed.",
            )
            return 0

        covered = 0
        failures: list[str] = []
        for key in scenario_keys:
            row = coverage.get(key)
            if not isinstance(row, Mapping):
                failures.append(f"{key}:missing")
                continue
            eligible = self._integer_or_none(row.get("eligible_patients")) or 0
            status = self._clean(row.get("status")) or ""
            if eligible > 0:
                if status != "covered":
                    failures.append(f"{key}:{status or 'missing'}")
                else:
                    covered += 1
            elif status not in {"not_present", "not_applicable", "absent"}:
                failures.append(f"{key}:{status or 'missing'}")
        self._record(
            "scenario_coverage",
            not failures,
            f"All {covered} present scenarios are covered.",
            "Incomplete scenario coverage: " + ", ".join(failures[:10]),
        )
        return covered

    # ------------------------------------------------------------- patients
    def _check_patient_reviews(self, packet: Mapping[str, Any]) -> int:
        patients = packet.get("patients")
        if not isinstance(patients, list) or not patients:
            self._record(
                "patient_sample_nonempty",
                False,
                "",
                "Review packet contains no selected patients.",
            )
            return 0
        self._record(
            "patient_sample_nonempty",
            True,
            f"Review packet contains {len(patients)} selected patients.",
            "",
        )

        source_ids: set[int] = set()
        target_ids: set[int] = set()
        uuids: set[str] = set()
        failures: list[str] = []
        for index, item in enumerate(patients):
            if not isinstance(item, Mapping):
                failures.append(f"row {index}:malformed")
                continue
            source_id = self._integer_or_none(item.get("source_patient_link_id"))
            target_id = self._integer_or_none(item.get("target_patient_link_id"))
            patient_uuid = self._clean(item.get("patient_uuid"))
            status = (self._clean(item.get("review_status")) or "pending").lower()
            if source_id is None or source_id <= 0 or source_id in source_ids:
                failures.append(f"row {index}:source-id")
            else:
                source_ids.add(source_id)
            if target_id is None or target_id <= 0 or target_id in target_ids:
                failures.append(f"row {index}:target-id")
            else:
                target_ids.add(target_id)
            try:
                parsed_uuid = str(UUID(patient_uuid or ""))
            except ValueError:
                parsed_uuid = ""
                failures.append(f"row {index}:uuid")
            if parsed_uuid:
                if parsed_uuid in uuids:
                    failures.append(f"row {index}:duplicate-uuid")
                uuids.add(parsed_uuid)
                if item.get("cockpit_path") != f"/patients/{parsed_uuid}":
                    failures.append(f"row {index}:cockpit-path")
            if status != "approved":
                failures.append(f"row {index}:review_status={status}")
            scenarios = item.get("scenarios")
            if not isinstance(scenarios, list) or not scenarios:
                failures.append(f"row {index}:scenarios")
            notes = item.get("review_notes")
            if status == "rejected" and not self._clean(notes):
                failures.append(f"row {index}:rejection-without-note")

        self._record(
            "patient_reviews_complete",
            not failures,
            "Every selected patient has a unique identity and approved clinical review.",
            "Incomplete/invalid patient reviews: " + ", ".join(failures[:15]),
        )
        return len(patients)

    # -------------------------------------------------------------- signoff
    def _check_signoff(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        signoff = packet.get("signoff")
        if not isinstance(signoff, Mapping):
            signoff = packet.get("signoff_template")
        if not isinstance(signoff, Mapping):
            signoff = {}
            self._record(
                "clinician_signoff_present",
                False,
                "",
                "Completed signoff object is missing.",
            )
            return signoff

        reviewed_by = self._clean(signoff.get("reviewed_by"))
        decision = (self._clean(signoff.get("decision")) or "").lower()
        reviewed_at_raw = self._clean(signoff.get("reviewed_at"))
        reviewed_at = self._parse_datetime(reviewed_at_raw)
        now = datetime.now(UTC)
        time_ok = (
            reviewed_at is not None
            and reviewed_at.tzinfo is not None
            and reviewed_at <= now + timedelta(minutes=5)
        )
        valid = bool(
            reviewed_by
            and len(reviewed_by) <= 200
            and decision == "approved"
            and time_ok
        )
        self._record(
            "clinician_signoff_present",
            valid,
            "Clinician identity, timestamp and approved decision are complete.",
            "Signoff requires reviewed_by, timezone-aware reviewed_at and decision=approved.",
        )
        return signoff

    def _check_discrepancies(self, signoff: Mapping[str, Any]) -> int:
        discrepancies = signoff.get("discrepancies", [])
        if not isinstance(discrepancies, list):
            self._record(
                "discrepancy_disposition",
                False,
                "",
                "Signoff discrepancies must be a list.",
            )
            return 0
        failures: list[str] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(discrepancies):
            if not isinstance(item, Mapping):
                failures.append(f"row {index}:malformed")
                continue
            discrepancy_id = self._clean(item.get("id") or item.get("key"))
            severity = (self._clean(item.get("severity")) or "").lower()
            disposition = (self._clean(item.get("disposition")) or "").lower()
            owner = self._clean(item.get("owner"))
            description = self._clean(item.get("description"))
            resolution_note = self._clean(item.get("resolution_note"))
            resolved_at = self._parse_datetime(self._clean(item.get("resolved_at")))
            if not discrepancy_id or discrepancy_id in seen_ids:
                failures.append(f"row {index}:id")
            else:
                seen_ids.add(discrepancy_id)
            if severity not in _ALLOWED_SEVERITIES:
                failures.append(f"{discrepancy_id or index}:severity")
            if disposition not in _ALLOWED_DISPOSITIONS:
                failures.append(f"{discrepancy_id or index}:disposition")
            if not owner or not description or resolved_at is None:
                failures.append(f"{discrepancy_id or index}:resolution-metadata")
            if disposition in {"accepted_risk", "false_positive"} and not resolution_note:
                failures.append(f"{discrepancy_id or index}:resolution-note")
            if disposition == "deferred":
                failures.append(f"{discrepancy_id or index}:deferred")
            if severity in {"major", "critical"} and disposition != "fixed":
                failures.append(f"{discrepancy_id or index}:must-be-fixed")

        self._record(
            "discrepancy_disposition",
            not failures,
            f"All {len(discrepancies)} discrepancies are fully dispositioned.",
            "Unresolved discrepancy fields: " + ", ".join(failures[:15]),
        )
        return len(discrepancies)

    def _check_warning_acknowledgement(
        self, packet: Mapping[str, Any], signoff: Mapping[str, Any]
    ) -> None:
        warnings = packet.get("warnings") or []
        acknowledged = signoff.get("acknowledged_warnings") or []
        if not isinstance(warnings, list) or not all(
            isinstance(item, str) for item in warnings
        ):
            self._record(
                "warning_acknowledgement",
                False,
                "",
                "Packet warnings are malformed.",
            )
            return
        if not isinstance(acknowledged, list) or not all(
            isinstance(item, str) for item in acknowledged
        ):
            self._record(
                "warning_acknowledgement",
                False,
                "",
                "acknowledged_warnings must be a list of exact warning strings.",
            )
            return
        self._record(
            "warning_acknowledgement",
            set(warnings) == set(acknowledged),
            f"All {len(warnings)} packet warnings are explicitly acknowledged.",
            "Packet warnings and acknowledged_warnings do not match exactly.",
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
            SignoffCheck(
                key=key,
                status="pass" if passed else "fail",
                detail=pass_detail if passed else fail_detail,
            )
        )

    @staticmethod
    def _clean(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _string_or_none(value: Any) -> Optional[str]:
        return SpecialistRecordClinicianSignoffVerifier._clean(value)

    @staticmethod
    def _integer_or_none(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)
