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
    ) -> dict:
        report = self.repository.latest_passing(
            engine_version=CURRENT_ENGINE_VERSION,
            ruleset_code=RULESET_CODE,
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        )
        if not report or report["report_hash"] != report_hash:
            raise ClinicalValidationError(
                "attestation must reference the latest passing current-package report"
            )
        event = self.repository.attest(
            int(report["id"]),
            role=role,
            reviewer=reviewer,
            note=note,
            report_hash=report_hash,
        )
        log_activity(
            "clinical_validation_attest",
            (
                f"Validation role={event['role']} report={report_hash} "
                f"reviewer={event['reviewer']}"
            ),
            user_id=0,
            username=event["reviewer"],
        )
        return event

    def current_release_evidence(self) -> dict | None:
        return self.repository.release_evidence(
            engine_version=CURRENT_ENGINE_VERSION,
            ruleset_code=RULESET_CODE,
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        )

    def dashboard(self) -> dict:
        latest = self.repository.latest_for_identity(
            engine_version=CURRENT_ENGINE_VERSION,
            ruleset_code=RULESET_CODE,
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        )
        attestations = (
            self.repository.attestations(int(latest["id"]))
            if latest and latest["status"] == "PASS"
            else {}
        )
        evidence = self.current_release_evidence()
        blockers: list[str] = []
        if not latest:
            blockers.append("هنوز گزارش اعتبارسنجی برای نسخهٔ جاری ساخته نشده است.")
        elif latest["status"] != "PASS":
            blockers.append("جدیدترین اجرای اعتبارسنجی مسدود است؛ PASS قدیمی قابل استفاده نیست.")
        if latest and latest["status"] == "PASS" and "CLINICAL" not in attestations:
            blockers.append("تأیید مستقل مسئول بالینی ثبت نشده است.")
        if latest and latest["status"] == "PASS" and "TECHNICAL" not in attestations:
            blockers.append("تأیید مستقل بازبین فنی ثبت نشده است.")
        return {
            "report": latest,
            "attestations": attestations,
            "release_evidence": evidence,
            "release_ready": bool(evidence),
            "blockers": blockers,
            "package_version": CURRENT_BUNDLED_PACKAGE_VERSION,
            "engine_version": CURRENT_ENGINE_VERSION,
            "ruleset_code": RULESET_CODE,
        }
