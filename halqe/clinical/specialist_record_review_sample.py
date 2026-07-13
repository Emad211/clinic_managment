"""Public clinician-review sampler with strict verifier-report binding.

The deterministic query and set-cover implementation live in
:mod:`clinical._specialist_record_review_sample_core`.  This facade ensures a
review packet can only be generated from an owner-only verifier artifact whose
critical mechanical and clinical checks all explicitly passed.
"""
from __future__ import annotations

import re
import stat
from typing import Any

from clinical import _specialist_record_review_sample_core as _core


ReviewScenario = _core.ReviewScenario
ReviewCandidate = _core.ReviewCandidate
SpecialistRecordReviewSample = _core.SpecialistRecordReviewSample
SpecialistRecordReviewSampleError = _core.SpecialistRecordReviewSampleError
SCENARIOS = _core.SCENARIOS

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_PASS_CHECKS = frozenset(
    {
        "apply_report_contract",
        "apply_table_accounting",
        "unresolved_patient_policy",
        "apply_report_ledger_count",
        "idempotent_replay_report",
        "relational_dry_run_reproduction",
        "durable_ledger_count",
        "ledger_source_table_counts",
        "ledger_row_shape",
        "ledger_manifest",
        "ledger_target_existence",
        "target_payload_fingerprints",
        "medication_event_orphans",
        "verified_patient_self_reports",
        "lab_observation_visibility",
        "appointment_parent_orphans",
        "followup_appointment_orphans",
        "prescription_followup_orphans",
    }
)


class SpecialistRecordReviewSampler(_core.SpecialistRecordReviewSampler):
    """Sampler that accepts only a complete, untampered release-verifier result."""

    def _load_verification_report(self) -> tuple[dict[str, Any], str]:
        payload, report_hash = super()._load_verification_report()
        mode = stat.S_IMODE(self.verification_report_path.stat().st_mode)
        if mode & 0o077:
            raise SpecialistRecordReviewSampleError(
                "Verification report must be owner-only (mode 0600 or stricter)."
            )

        for key in ("source_file_sha256", "source_manifest_sha256"):
            value = payload.get(key)
            if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
                raise SpecialistRecordReviewSampleError(
                    f"Verification report field {key} is not a valid SHA-256 digest."
                )

        summary = payload.get("summary")
        if not isinstance(summary, dict) or int(summary.get("failed", -1)) != 0:
            raise SpecialistRecordReviewSampleError(
                "Verification report summary is missing or contains failed checks."
            )
        checks = payload.get("checks")
        if not isinstance(checks, list):
            raise SpecialistRecordReviewSampleError(
                "Verification report does not contain a checks list."
            )

        by_name: dict[str, str] = {}
        duplicates: set[str] = set()
        for item in checks:
            if not isinstance(item, dict):
                raise SpecialistRecordReviewSampleError(
                    "Verification report contains a malformed check entry."
                )
            name = item.get("name")
            status_value = item.get("status")
            if not isinstance(name, str) or not isinstance(status_value, str):
                raise SpecialistRecordReviewSampleError(
                    "Verification check name/status is malformed."
                )
            if name in by_name:
                duplicates.add(name)
            by_name[name] = status_value
        if duplicates:
            raise SpecialistRecordReviewSampleError(
                "Verification report contains duplicate check names: "
                + ", ".join(sorted(duplicates))
            )

        missing = sorted(_REQUIRED_PASS_CHECKS - set(by_name))
        nonpassing = sorted(
            name
            for name in _REQUIRED_PASS_CHECKS
            if by_name.get(name) != "pass"
        )
        if missing or nonpassing:
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if nonpassing:
                details.append("not_pass=" + ",".join(nonpassing))
            raise SpecialistRecordReviewSampleError(
                "Verification report is not sufficient for clinical sign-off sampling: "
                + "; ".join(details)
            )
        return payload, report_hash


__all__ = [
    "ReviewScenario",
    "ReviewCandidate",
    "SpecialistRecordReviewSample",
    "SpecialistRecordReviewSampleError",
    "SpecialistRecordReviewSampler",
    "SCENARIOS",
]
