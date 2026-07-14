"""Public fail-closed clinician sign-off verifier.

The original artifact checks live in
:mod:`clinical._specialist_record_clinician_signoff_core`.  This facade adds the
release-critical checks that require the live PostgreSQL state and cross-field
review policy:

* every pseudonymous patient must still match source ledger → clinical link →
  accounting UUID;
* timestamps, scenario assignments, coverage counts and free-text PHI rules must
  satisfy the completed-review policy.

The extra checks are part of the returned decision, not optional post-processing.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from django.db import DatabaseError

from clinical import _specialist_record_clinician_signoff_core as _core
from clinical.specialist_record_review_database import verify_review_patient_bindings
from clinical.specialist_record_review_policy import verify_review_packet_policy


SpecialistRecordClinicianSignoffError = _core.SpecialistRecordClinicianSignoffError
SignoffCheck = _core.SignoffCheck
ClinicianSignoffResult = _core.ClinicianSignoffResult


class SpecialistRecordClinicianSignoffVerifier(
    _core.SpecialistRecordClinicianSignoffVerifier
):
    """Artifact, live-database and cross-field verifier for clinician approval."""

    def run(self) -> ClinicianSignoffResult:
        result = super().run()
        packet, _packet_raw = self._load_private_json(
            self.review_packet_path,
            "clinician review packet",
        )
        verification, _verification_raw = self._load_private_json(
            self.verification_report_path,
            "migration verification report",
        )

        try:
            binding = verify_review_patient_bindings(
                packet=packet,
                source_id=self.source_id,
                tenant_id=self.tenant_id,
            )
        except DatabaseError:
            binding = None
        if binding is None:
            self.checks.append(
                SignoffCheck(
                    key="patient_database_binding",
                    status="fail",
                    detail=(
                        "Live patient binding could not be verified because the "
                        "database lookup failed."
                    ),
                )
            )
        else:
            self.checks.append(
                SignoffCheck(
                    key="patient_database_binding",
                    status="pass" if binding.passed else "fail",
                    detail=binding.detail,
                )
            )

        policy_packet = _normalize_packet_for_policy(packet)
        policy = verify_review_packet_policy(
            packet=policy_packet,
            verification=verification,
        )
        self.checks.append(
            SignoffCheck(
                key="review_packet_policy",
                status=policy.status,
                detail=policy.detail,
            )
        )

        failed = sum(item.status == "fail" for item in self.checks)
        warnings = sum(item.status == "warning" for item in self.checks)
        passed = sum(item.status == "pass" for item in self.checks)
        result.decision = "GO" if failed == 0 else "NO_GO"
        result.checks = self.checks
        result.summary = {
            "passed": passed,
            "warnings": warnings,
            "failed": failed,
        }
        return result


def _normalize_packet_for_policy(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt sampler field names to the stricter policy's canonical vocabulary."""
    normalized = deepcopy(dict(packet))
    coverage = normalized.get("coverage")
    if isinstance(coverage, Mapping):
        converted: dict[str, Any] = {}
        for key, value in coverage.items():
            if not isinstance(value, Mapping):
                converted[str(key)] = value
                continue
            row = dict(value)
            if "selected_patients" not in row and "selected_samples" in row:
                row["selected_patients"] = row.get("selected_samples")
            if row.get("status") == "not_present_in_source":
                row["status"] = "not_present"
            converted[str(key)] = row
        normalized["coverage"] = converted
    return normalized


__all__ = [
    "SpecialistRecordClinicianSignoffError",
    "SignoffCheck",
    "ClinicianSignoffResult",
    "SpecialistRecordClinicianSignoffVerifier",
]
