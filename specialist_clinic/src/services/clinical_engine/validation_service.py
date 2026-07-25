"""Application service for immutable package validation and dual attestation."""
from __future__ import annotations

from pathlib import Path

from src.adapters.sqlite.clinical_validation_repo import (
    ClinicalValidationError,
    ClinicalValidationReportRepository,
)
from src.domain.clinical_engine.release import (
    CURRENT_BUNDLED_PACKAGE_VERSION,
    CURRENT_ENGINE_VERSION,
    RULESET_CODE,
)
from src.services.activity_logger import log_activity
from src.services.clinical_engine.validation_harness import (
    GoldenCaseValidationHarness,
)


class ClinicalValidationService:
    def __init__(self, *, repository=None, harness=None):
        self.repository = repository or ClinicalValidationReportRepository()
        self.harness = harness or GoldenCaseValidationHarness()

    def run_current(
        self,
        *,
        created_by: str,
        case_path: Path | None = None,
    ) -> dict:
        actor = " ".join(str(created_by or "").strip().split())
        if not actor:
            raise ClinicalValidationError("created_by is required")
        report = self.harness.run(
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
            case_path=case_path,
        )
        stored = self.repository.create(report, created_by=actor)
        log_activity(
            "clinical_validation_run",
            (
                f"Validation {report['status']} report={report['report_hash']} "
                f"package={CURRENT_BUNDLED_PACKAGE_VERSION}"
            ),
            user_id=0,
            username=actor,
        )
        return stored

    def attest_current(
        self,
        *,
        role: str,
        reviewer: str,
        note: str,
        report_hash: str,
        activation_report_hash: str,
    ) -> dict:
        report = self.repository.latest_passing(
            engine_version=CURRENT_ENGINE_VERSION,
            ruleset_code=RULESET_CODE,
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        )
        if not report or report["report_hash"] != report_hash:
            raise ClinicalValidationError(
                "attestation must reference the newest passing current-package report"
            )
        event = self.repository.attest(
            int(report["id"]),
            role=role,
            reviewer=reviewer,
            note=note,
            report_hash=report_hash,
            activation_report_hash=activation_report_hash,
        )
        log_activity(
            "clinical_validation_attest",
            (
                f"Validation role={event['role']} report={report_hash} "
                f"activation={activation_report_hash} reviewer={event['reviewer']}"
            ),
            user_id=0,
            username=event["reviewer"],
        )
        return event

    def current_release_evidence(
        self,
        *,
        activation_report_hash: str,
        package_hash: str | None = None,
    ) -> dict | None:
        return self.repository.release_evidence(
            engine_version=CURRENT_ENGINE_VERSION,
            ruleset_code=RULESET_CODE,
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
            package_hash=package_hash,
            activation_report_hash=activation_report_hash,
        )

    def dashboard(self, *, activation_report_hash: str | None = None) -> dict:
        report = self.repository.latest_current(
            engine_version=CURRENT_ENGINE_VERSION,
            ruleset_code=RULESET_CODE,
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        )
        attestations = (
            self.repository.attestations(
                int(report["id"]),
                activation_report_hash=activation_report_hash,
            )
            if report and activation_report_hash
            else {}
        )
        return {
            "report": report,
            "attestations": attestations,
            "release_evidence": (
                self.current_release_evidence(
                    activation_report_hash=activation_report_hash,
                    package_hash=report["package_hash"] if report else None,
                )
                if activation_report_hash
                else None
            ),
            "recent_reports": self.repository.recent(10),
            "package_version": CURRENT_BUNDLED_PACKAGE_VERSION,
            "engine_version": CURRENT_ENGINE_VERSION,
        }
