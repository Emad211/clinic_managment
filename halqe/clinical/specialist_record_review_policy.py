"""Cross-field policy checks for completed clinician review packets."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import re
from typing import Any, Mapping, Optional


_MOBILE_RE = re.compile(r"(?<!\d)09\d{9}(?!\d)")
_TEN_DIGIT_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")
_MAX_REVIEW_TEXT = 4000


@dataclass
class ReviewPacketPolicyResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.failures:
            return "fail"
        if self.warnings:
            return "warning"
        return "pass"

    @property
    def detail(self) -> str:
        if self.failures:
            preview = ", ".join(self.failures[:12])
            suffix = "" if len(self.failures) <= 12 else f" (+{len(self.failures) - 12} more)"
            return f"Review packet policy failures: {preview}{suffix}"
        if self.warnings:
            return "Review packet policy warnings: " + ", ".join(self.warnings)
        return "Review packet timestamps, sample assignments and free text satisfy policy."



def verify_review_packet_policy(
    *, packet: Mapping[str, Any], verification: Mapping[str, Any]
) -> ReviewPacketPolicyResult:
    failures: list[str] = []
    warnings: list[str] = []

    generated_at = _aware_datetime(packet.get("generated_at"))
    signoff = packet.get("signoff")
    if not isinstance(signoff, Mapping):
        signoff = packet.get("signoff_template")
    if not isinstance(signoff, Mapping):
        signoff = {}
    reviewed_at = _aware_datetime(signoff.get("reviewed_at"))
    now = datetime.now(UTC)
    if generated_at is None:
        failures.append("packet-generated-at-missing-or-naive")
    if reviewed_at is None:
        failures.append("reviewed-at-missing-or-naive")
    if generated_at and reviewed_at and reviewed_at < generated_at:
        failures.append("reviewed-before-packet-generation")
    if reviewed_at and reviewed_at > now + timedelta(minutes=5):
        failures.append("reviewed-at-in-future")

    verification_generated = _aware_datetime(verification.get("generated_at"))
    if verification.get("generated_at") is not None and verification_generated is None:
        failures.append("verification-generated-at-invalid")
    elif verification_generated and generated_at and verification_generated > generated_at:
        failures.append("packet-generated-before-verification")
    elif verification.get("generated_at") is None:
        warnings.append("verification-report-has-no-generated-at")

    patients = packet.get("patients")
    scenarios = packet.get("scenarios")
    coverage = packet.get("coverage")
    max_patients = _positive_int(packet.get("max_patients"))
    per_scenario = _positive_int(packet.get("per_scenario"))
    if not isinstance(patients, list) or not patients:
        failures.append("patient-sample-empty")
        patients = []
    if max_patients is None:
        failures.append("max-patients-invalid")
    elif len(patients) > max_patients:
        failures.append("patient-sample-exceeds-max")
    if per_scenario is None:
        failures.append("per-scenario-invalid")
        per_scenario = 1

    scenario_keys: set[str] = set()
    if not isinstance(scenarios, list) or not scenarios:
        failures.append("scenario-catalog-empty")
        scenarios = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, Mapping):
            failures.append(f"scenario-{index}-malformed")
            continue
        key = _clean(scenario.get("key"))
        if not key or key in scenario_keys:
            failures.append(f"scenario-{index}-missing-or-duplicate-key")
        else:
            scenario_keys.add(key)

    actual: dict[str, set[int]] = {}
    for index, patient in enumerate(patients):
        if not isinstance(patient, Mapping):
            failures.append(f"patient-{index}-malformed")
            continue
        target_id = _positive_int(patient.get("target_patient_link_id"))
        assigned = patient.get("scenarios")
        if not isinstance(assigned, list) or not assigned:
            failures.append(f"patient-{index}-scenario-list-empty")
            assigned = []
        seen: set[str] = set()
        for row in assigned:
            key = _clean(row.get("key")) if isinstance(row, Mapping) else None
            if not key or key not in scenario_keys:
                failures.append(f"patient-{index}-unknown-scenario")
                continue
            if key in seen:
                failures.append(f"patient-{index}-duplicate-scenario-{key}")
                continue
            seen.add(key)
            if target_id is not None:
                actual.setdefault(key, set()).add(target_id)
        _scan_text(
            patient.get("review_notes"),
            path=f"patient-{index}-review-notes",
            failures=failures,
        )

    if not isinstance(coverage, Mapping):
        failures.append("coverage-malformed")
        coverage = {}
    for key in sorted(scenario_keys):
        row = coverage.get(key)
        if not isinstance(row, Mapping):
            failures.append(f"coverage-{key}-missing")
            continue
        eligible = _nonnegative_int(row.get("eligible_patients"))
        reported = _nonnegative_int(row.get("selected_patients"))
        status = _clean(row.get("status")) or ""
        actual_count = len(actual.get(key, set()))
        if eligible is None or reported is None:
            failures.append(f"coverage-{key}-invalid-count")
            continue
        if eligible == 0:
            if actual_count != 0 or reported != 0 or status not in {
                "not_present",
                "not_applicable",
                "absent",
            }:
                failures.append(f"coverage-{key}-zero-eligible-inconsistent")
        else:
            required = min(per_scenario, eligible)
            if (
                status != "covered"
                or actual_count < required
                or reported != actual_count
            ):
                failures.append(
                    f"coverage-{key}-required-{required}-actual-{actual_count}-reported-{reported}"
                )

    discrepancies = signoff.get("discrepancies") or []
    if isinstance(discrepancies, list):
        for index, item in enumerate(discrepancies):
            if not isinstance(item, Mapping):
                continue
            _scan_text(
                item.get("description"),
                path=f"discrepancy-{index}-description",
                failures=failures,
            )
            _scan_text(
                item.get("resolution_note"),
                path=f"discrepancy-{index}-resolution-note",
                failures=failures,
            )
            resolved_at = _aware_datetime(item.get("resolved_at"))
            if resolved_at and reviewed_at and resolved_at > reviewed_at:
                failures.append(f"discrepancy-{index}-resolved-after-signoff")
            if resolved_at and generated_at and resolved_at < generated_at:
                failures.append(f"discrepancy-{index}-resolved-before-packet")

    return ReviewPacketPolicyResult(
        passed=not failures,
        failures=failures,
        warnings=warnings,
    )



def _scan_text(value: Any, *, path: str, failures: list[str]) -> None:
    text = _clean(value)
    if not text:
        return
    if len(text) > _MAX_REVIEW_TEXT:
        failures.append(f"{path}-too-long")
    if _MOBILE_RE.search(text):
        failures.append(f"{path}-contains-mobile")
    for candidate in _TEN_DIGIT_RE.findall(text):
        if _is_iranian_national_id(candidate):
            failures.append(f"{path}-contains-national-id")
            break



def _is_iranian_national_id(value: str) -> bool:
    if len(value) != 10 or not value.isdigit() or len(set(value)) == 1:
        return False
    checksum = sum(int(value[index]) * (10 - index) for index in range(9)) % 11
    control = int(value[9])
    return control == (checksum if checksum < 2 else 11 - checksum)



def _aware_datetime(value: Any) -> Optional[datetime]:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)



def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None



def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None



def _nonnegative_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
