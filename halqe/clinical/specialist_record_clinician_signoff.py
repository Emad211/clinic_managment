"""Public fail-closed clinician sign-off verifier.

The original artifact checks live in
:mod:`clinical._specialist_record_clinician_signoff_core`. This facade adds the
release-critical checks that require live PostgreSQL state and cross-field review
policy. It also rejects direct patient identity keys regardless of punctuation or
naming style, and scans retained free text for Iranian mobile/national identifiers
written with Latin, Persian or Arabic digits.
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
    "patientnationalid",
    "phonenumber",
    "patientphonenumber",
    "patientname",
    "patientfullname",
    "fullname",
    "firstname",
    "lastname",
    "familyname",
    "dateofbirth",
    "birthdate",
    "phone",
    "mobile",
    "mobilenumber",
    "mobilephone",
    "telephone",
    "address",
    "postaladdress",
    "email",
    "emailaddress",
    "نام",
    "نامبیمار",
    "نامخانوادگی",
    "کدملی",
    "شمارهتماس",
    "شمارهموبایل",
    "تلفن",
    "موبایل",
    "آدرس",
    "نشانی",
    "ایمیل",
    "تاریختولد",
}
_IDENTITY_KEY_FRAGMENTS = {
    "nationalid",
    "phonenumber",
    "mobilenumber",
    "mobilephone",
    "patientname",
    "patientfullname",
    "firstname",
    "lastname",
    "familyname",
    "dateofbirth",
    "birthdate",
    "postaladdress",
    "emailaddress",
    "کدملی",
    "شمارهموبایل",
    "شمارهتماس",
    "نامبیمار",
    "نامخانوادگی",
    "تاریختولد",
}
_core._FORBIDDEN_IDENTITY_KEYS = frozenset(
    set(_core._FORBIDDEN_IDENTITY_KEYS) | _EXTRA_IDENTITY_KEYS
)
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_MOBILE_RE = re.compile(
    r"(?<!\d)(?:(?:\+|00)?98[\s\-().]*|0)9(?:[\s\-().]*\d){9}(?!\d)"
)
_TEN_DIGIT_GROUP_RE = re.compile(r"(?<!\d)(?:\d[\s\-().]*){10}(?!\d)")
_KEY_CLEAN_RE = re.compile(r"[^0-9a-z\u0600-\u06ff]+", re.IGNORECASE)


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

        identity_key_failures = _review_identity_key_failures(packet)
        self.checks.append(
            SignoffCheck(
                key="review_identity_key_guard",
                status="fail" if identity_key_failures else "pass",
                detail=(
                    "Review packet contains no direct identity field under alternate "
                    "punctuation or naming styles."
                    if not identity_key_failures
                    else "Direct identity field detected: "
                    + ", ".join(identity_key_failures[:10])
                ),
            )
        )

        text_failures = _review_text_phi_failures(packet)
        self.checks.append(
            SignoffCheck(
                key="review_text_phi_guard",
                status="fail" if text_failures else "pass",
                detail=(
                    "Review free text contains no Iranian mobile number or valid "
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


def _review_identity_key_failures(value: Any, path: str = "packet") -> list[str]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            token = _normalized_identity_key(key)
            if token in _EXTRA_IDENTITY_KEYS or any(
                fragment in token for fragment in _IDENTITY_KEY_FRAGMENTS
            ):
                failures.append(f"{path}.{key}")
            failures.extend(_review_identity_key_failures(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            failures.extend(_review_identity_key_failures(child, f"{path}[{index}]"))
    return failures


def _normalized_identity_key(value: str) -> str:
    return _KEY_CLEAN_RE.sub("", value.casefold().replace("\u200c", ""))


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
    for match in _TEN_DIGIT_GROUP_RE.findall(normalized):
        candidate = re.sub(r"\D", "", match)
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
