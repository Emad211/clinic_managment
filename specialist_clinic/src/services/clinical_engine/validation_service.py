"""Application service for immutable package validation and dual attestation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.adapters.sqlite.clinical_validation_repo import (
    ClinicalValidationError,
    ClinicalValidationReportRepository,
)
from src.common.utils import iran_now
from src.domain.clinical_engine.release import (
    CURRENT_BUNDLED_PACKAGE_VERSION,
    CURRENT_ENGINE_VERSION,
    RULESET_CODE,
)
from src.services.activity_logger import log_activity
from src.services.clinical_engine.validation_harness import (
    GoldenCaseValidationHarness,
)

FRESH_VALIDATION_MAX_AGE_MINUTES = 60


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

    def _latest_passing_report(self) -> dict | None:
        return self.repository.latest_passing(
            engine_version=CURRENT_ENGINE_VERSION,
            ruleset_code=RULESET_CODE,
            package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
        )

    @staticmethod
    def _is_fresh(report: dict | None) -> bool:
        if not report:
            return False
        try:
            created_at = datetime.fromisoformat(str(report["created_at"]))
        except (TypeError, ValueError):
            return False
        now = iran_now()
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        age_seconds = (now - created_at).total_seconds()
        return 0 <= age_seconds <= FRESH_VALIDATION_MAX_AGE_MINUTES * 60

    def ensure_fresh_release_evidence(self, *, actor: str) -> dict | None:
        """Guarantee a current, fresh, fully-attested release evidence set.

        Single-operator mode: the same actor may hold both attestation roles;
        idempotency comes from UNIQUE(validation_report_id, role).
        """
        operator = " ".join(str(actor or "").split())
        if not operator:
            raise ClinicalValidationError("actor is required")
        report = self._latest_passing_report()
        if not self._is_fresh(report):
            report = self.run_current(created_by=operator)
            if report["status"] != "PASS":
                raise ClinicalValidationError(
                    "اعتبارسنجی golden-case موفق نشد؛ فعال‌سازی تک‌اپراتور مسدود است"
                )
        attestations = self.repository.attestations(int(report["id"]))
        for role in ("CLINICAL", "TECHNICAL"):
            if role not in attestations:
                self.attest_current(
                    role=role.lower(),
                    reviewer=operator,
                    note="تأیید خودکار تک‌اپراتور",
                    report_hash=report["report_hash"],
                )
        return self.current_release_evidence()

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
