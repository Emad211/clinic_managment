"""Public fail-closed clinician sign-off verifier.

The original artifact checks live in
:mod:`clinical._specialist_record_clinician_signoff_core`. This facade adds the
release-critical checks that require the live PostgreSQL state and cross-field
review policy:

* every pseudonymous patient must still match source ledger → clinical link →
  accounting UUID;
* timestamps, scenario assignments, coverage counts and free-text PHI rules must
  satisfy the completed-review policy;
* sampler vocabulary is normalized before the core verifier runs;
* direct identity fields and mobile/national-ID strings written with Persian,
  Arabic or Latin digits are rejected from the retained review artifact.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Mapping

from clinical import _specialist_record_clinician_signoff_core as _core
from clinical.specialist_record_review_database import verify_review_patient_bindings
from clinical.specialist_record_review_policy import verify_review_packet_policy


_EXTRA_IDENTITY_KEYS = {
    "nationalid",
    "phone",
    "mobile",
    "mobile_number",
    "mobile_phone",
    "telephone",
    "نام",
    "نام_بیمار",
    "کدملی",
    "کد_ملی",
    "شماره_تماس",
    "شماره_موبایل",
}
_core._FORBIDDEN_IDENTITY_KEYS = frozenset(
    set(_core._FORBIDDEN_IDENTITY_KEYS) | _EXTRA_IDENTITY_KEYS
)
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_MOBILE_RE = re.compile(r"(?<!\d)09\d{9}(?!\d)")
_TEN_DIGIT_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")


SpecialistRecordClinicianSignoffError = _core.SpecialistRecordClinicianSignoffError
SignoffCheck = _core.SignoffCheck
ClinicianSignoffResult = _core.ClinicianSignoffResult


class SpecialistRecordClinicianSignoffVerifier(
    _core.SpecialistRecordClinicianSignoffVerifier
):
    """Artifact, live-database and cross-field verifier for clinician approval."""

    def _load_private_json(
        self,
        path: Path,
        label: str,
    ) -> tuple[dict[str, Any], bytes]:
        payload, raw = super()._load_private_json(path, label)
        if label == "clinician review packet":
            payload = _normalize_packet_for_policy(payload)
        return payload, raw

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
        except Exception:
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

        policy = verify_review_packet_policy(
            packet=packet,
            verification=verification,
        )
        self.checks.append(
            SignoffCheck(
                key="review_packet_policy",
                status=policy.status,
                detail=policy.detail,
            )
        )
        text_failures = _review_text_phi_failures(packet)
        self.checks.append(
            SignoffCheck(
                key="review_text_phi_guard",
                status="fail" if text_failures else "pass",
                detail=(
                    "Review free text contains no mobile number or valid Iranian "
                    "national ID in Latin/Persian/Arabic digits."
                    if not text_failures
                    else "Review free-text PHI detected: "
                    + ", ".join(text_failures[:10])
                ),
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
    """Adapt sampler field names to one canonical release-policy vocabulary."""
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


def _review_text_phi_failures(packet: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    patients = packet.get("patients")
    if isinstance(patients, list):
        for index, item in enumerate(patients):
            if isinstance(item, Mapping):
                _scan_identity_text(
                    item.get("review_notes"),
                    f"patient-{index}-review-notes",
                    failures,
                )
    signoff = packet.get("signoff")
    if not isinstance(signoff, Mapping):
        signoff = packet.get("signoff_template")
    if isinstance(signoff, Mapping):
        _scan_identity_text(signoff.get("reviewed_by"), "reviewed-by", failures)
        discrepancies = signoff.get("discrepancies")
        if isinstance(discrepancies, list):
            for index, item in enumerate(discrepancies):
                if not isinstance(item, Mapping):
                    continue
                _scan_identity_text(
                    item.get("description"),
                    f"discrepancy-{index}-description",
                    failures,
                )
                _scan_identity_text(
                    item.get("resolution_note"),
                    f"discrepancy-{index}-resolution-note",
                    failures,
                )
    return failures


def _scan_identity_text(value: Any, path: str, failures: list[str]) -> None:
    if value is None:
        return
    normalized = str(value).translate(_DIGIT_TRANSLATION)
    if _MOBILE_RE.search(normalized):
        failures.append(path + "-contains-mobile")
    for candidate in _TEN_DIGIT_RE.findall(normalized):
        if _is_iranian_national_id(candidate):
            failures.append(path + "-contains-national-id")
            break


def _is_iranian_national_id(value: str) -> bool:
    if len(value) != 10 or not value.isdigit() or len(set(value)) == 1:
        return False
    checksum = sum(int(value[index]) * (10 - index) for index in range(9)) % 11
    control = int(value[9])
    return control == (checksum if checksum < 2 else 11 - checksum)


__all__ = [
    "SpecialistRecordClinicianSignoffError",
    "SignoffCheck",
    "ClinicianSignoffResult",
    "SpecialistRecordClinicianSignoffVerifier",
]
