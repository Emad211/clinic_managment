"""Evidence-bound comparison, approval, activation and rollback gates."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
    content_hash,
    report_core,
    valid_report,
)
from src.adapters.sqlite.clinical_engine_audit_repo import (
    ClinicalEngineAuditRepository,
)
from src.adapters.sqlite.clinical_engine_fact_repo import (
    ClinicalEngineFactRepository,
)
from src.adapters.sqlite.clinical_engine_rules_repo import (
    ClinicalEngineRulesRepository,
)
from src.common.utils import iran_now
from src.domain.clinical_engine.release import CURRENT_ENGINE_VERSION
from src.services.activity_logger import log_activity
from src.services.clinical_engine.fact_builder import ShadowFactCapture


DEMO_IDS = tuple(f"TEST{i:04d}" for i in range(1, 11))
EXPECTED_POSITIVE_CONTROLS = {
    "TEST0008": "T2-REDFLAG-BP",
    "TEST0010": "T2-SAFE-MET-STOP",
}


class ActivationGateError(RuntimeError):
    pass


class _ForcedShadowFacts:
    def __init__(self, delegate=None):
        self.delegate = delegate or ClinicalEngineFactRepository()

    def get_mode(self):
        return "shadow"

    def load_bundle(self, patient_link_id):
        return self.delegate.load_bundle(patient_link_id)

    def is_selected_patient(self, patient_link_id):
        return self.delegate.is_selected_patient(patient_link_id)


class ClinicalEngineActivationService:
    """Build reproducible evidence; never self-approve or silently activate."""

    def __init__(
        self,
        *,
        state=None,
        rules=None,
        audit=None,
        capture_factory=None,
        cohort_summary_factory=None,
        enforce_positive_controls: bool = True,
    ):
        self.state = state or ClinicalEngineActivationRepository()
        self.rules = rules or ClinicalEngineRulesRepository()
        self.audit = audit or ClinicalEngineAuditRepository()
        self.capture_factory = capture_factory or self._capture
        self.cohort_summary_factory = (
            cohort_summary_factory or self._cohort_summary
        )
        self.enforce_positive_controls = enforce_positive_controls

    @staticmethod
    def _cohort_summary():
        from src.services.clinical_engine.demo_cohort import DemoCohortService

        return DemoCohortService().summary()

    def _capture(self):
        facts = _ForcedShadowFacts()
        return ShadowFactCapture(
            repository=facts,
            audit=self.audit,
            rules=self.rules,
        )

    def dashboard(self) -> dict[str, Any]:
        report = self.state.get_json("last_report") or {}
        checks = report.get("checks") or {}
        approvals = {
            role: self.state.get_json(f"approval_{role}")
            for role in ("clinical", "technical")
        }
        raw_mode = self.state.raw_mode()
        effective_mode = ClinicalEngineFactRepository().get_mode()
        seal = self.state.get_json("seal")
        verification = self.state.get_json(
            "selected_rollout_verification"
        )
        ruleset = self.rules.active_ruleset("general-outpatient")
        report_ok = valid_report(report)
        selected_valid = self.state.valid_seal("on_selected")
        global_valid = self.state.valid_seal("on")

        check_labels = {
            "exact_demo_cohort": "هر ۱۰ بیمار نمونه ارزیابی شده‌اند",
            "ruleset_frozen": "مجموعه‌قواعد تأییدشده و فریز شده است",
            "zero_run_failures": "همهٔ اجراها بدون شکست پایان یافته‌اند",
            "zero_rule_errors": "هیچ قاعده‌ای خطای اجرا ندارد",
            "burden_at_most_12_cards_per_patient": (
                "بار شناختی پیشنهادها در محدوده است"
            ),
            "longitudinal_cohort_complete": (
                "پرونده‌های نمونه طولی و کامل هستند"
            ),
            "expected_positive_controls": (
                "هر دو هشدار کنترل مثبت فعال شده‌اند"
            ),
        }
        blockers = [
            check_labels.get(key, key)
            for key, passed in checks.items()
            if not passed
        ]
        if not report:
            blockers.append(
                "هنوز گزارش مقایسهٔ ده بیمار ساخته نشده است"
            )
        if report_ok and not approvals["clinical"]:
            blockers.append("تأیید مسئول بالینی ثبت نشده است")
        if report_ok and not approvals["technical"]:
            blockers.append("تأیید فنی ثبت نشده است")

        stages = [
            {
                "key": "compare",
                "title": "مقایسهٔ ایمن",
                "done": report_ok,
                "detail": "اجرای هم‌زمان روی ده بیمار نمونه",
            },
            {
                "key": "approve",
                "title": "تأیید دوگانه",
                "done": bool(
                    approvals["clinical"] and approvals["technical"]
                ),
                "detail": "امضای بالینی و بازبینی فنی",
            },
            {
                "key": "selected",
                "title": "انتشار محدود",
                "done": selected_valid or global_valid,
                "detail": "نمایش فقط برای بیماران منتخب",
            },
            {
                "key": "global",
                "title": "انتشار عمومی",
                "done": global_valid,
                "detail": "فعال‌سازی پس از پایش انتشار محدود",
            },
        ]
        return {
            "raw_mode": raw_mode,
            "effective_mode": effective_mode,
            "mode_fa": {
                "off": "خاموش",
                "shadow": "سایه",
                "on_selected": "انتشار محدود",
                "on": "انتشار عمومی",
            }.get(effective_mode, "خاموش"),
            "mode_tone": (
                "ok"
                if global_valid
                else "info"
                if selected_valid
                else "warn"
                if raw_mode == "shadow"
                else "danger"
            ),
            "report": report,
            "report_ok": report_ok,
            "checks": checks,
            "check_labels": check_labels,
            "approvals": approvals,
            "seal": seal,
            "seal_valid": selected_valid or global_valid,
            "verification": verification,
            "ruleset": ruleset,
            "last_rollback": self.state.get_json("last_rollback"),
            "blockers": blockers,
            "stages": stages,
            "patient_count": len(report.get("patients") or []),
            "v2_error_count": sum(
                int(row.get("v2_errors") or 0)
                for row in (report.get("patients") or [])
            ),
            "can_approve": report_ok,
            "can_activate_selected": bool(
                report_ok
                and approvals["clinical"]
                and approvals["technical"]
            ),
            "can_verify_selected": selected_valid,
            "can_promote": bool(
                selected_valid
                and verification
                and ruleset
                and ruleset.get("status") == "SILENT"
            ),
            "can_activate_global": bool(
                selected_valid
                and verification
                and ruleset
                and ruleset.get("status") == "ACTIVE"
            ),
            "can_rollback": raw_mode != "off" or bool(seal),
        }

    def build_report(
        self,
        *,
        as_of_at: datetime | None = None,
        created_by: str = "activation-audit",
    ) -> dict[str, Any]:
        as_of_at = as_of_at or iran_now()
        found = {
            str(patient["national_id"]).upper(): patient
            for patient in self.state.demo_patients()
        }
        rows: list[dict] = []
        failures: list[dict] = []
        ruleset = self.rules.active_ruleset("general-outpatient")

        for national_id in DEMO_IDS:
            patient = found.get(national_id)
            if not patient:
                failures.append(
                    {
                        "national_id": national_id,
                        "code": "DEMO_PATIENT_MISSING",
                    }
                )
                continue
            patient_id = int(patient["id"])
            try:
                run_id = self.capture_factory().capture(
                    patient_id,
                    as_of_at=as_of_at,
                    created_by=created_by,
                )
                run = self.audit.decoded_run(run_id) if run_id else None
                if not run:
                    raise RuntimeError("v2 audit run was not persisted")
                if run.get("engine_version") != CURRENT_ENGINE_VERSION:
                    raise RuntimeError("activation run used another engine build")
            except Exception as exc:
                failures.append(
                    {
                        "national_id": national_id,
                        "code": "COMPARISON_RUN_FAILED",
                        "detail": type(exc).__name__,
                    }
                )
                continue

            fired = [
                evaluation
                for evaluation in run["evaluations"]
                if evaluation.get("outcome") == "FIRED"
                and evaluation.get("recommendation")
            ]
            rows.append(
                {
                    "national_id": national_id,
                    "patient_link_id": patient_id,
                    "v2_run_id": run_id,
                    "v2_fact_snapshot_hash": run.get(
                        "fact_snapshot_hash"
                    ),
                    "v2_run_status": run["run_status"],
                    "v2_rule_codes": sorted(
                        evaluation["rule_code"]
                        for evaluation in fired
                    ),
                    "v2_recommendations": len(fired),
                    "v2_errors": sum(
                        evaluation.get("outcome") == "ERROR"
                        for evaluation in run["evaluations"]
                    ),
                }
            )

        error_count = sum(row["v2_errors"] for row in rows)
        max_cards = max(
            (row["v2_recommendations"] for row in rows),
            default=0,
        )
        cohort_summary = self.cohort_summary_factory()
        totals = cohort_summary.get("totals") or {}
        row_by_nid = {row["national_id"]: row for row in rows}
        positive_controls_ok = all(
            rule_code
            in (
                row_by_nid.get(national_id, {}).get(
                    "v2_rule_codes"
                )
                or []
            )
            for national_id, rule_code in EXPECTED_POSITIVE_CONTROLS.items()
        )
        checks = {
            "exact_demo_cohort": len(rows) == 10 and not failures,
            "ruleset_frozen": bool(
                ruleset and ruleset["status"] in {"SILENT", "ACTIVE"}
            ),
            "zero_run_failures": not failures
            and all(
                row["v2_run_status"] == "COMPLETED"
                for row in rows
            ),
            "zero_rule_errors": error_count == 0,
            "burden_at_most_12_cards_per_patient": max_cards <= 12,
            "longitudinal_cohort_complete": bool(
                cohort_summary.get("ready")
                and cohort_summary.get("patient_count") == 10
                and totals.get("vitals", 0) >= 2000
                and totals.get("labs", 0) >= 1200
                and totals.get("notes", 0) >= 200
                and totals.get("medication_events", 0) >= 50
            ),
            "expected_positive_controls": (
                positive_controls_ok
                if self.enforce_positive_controls
                else True
            ),
        }
        report_body = {
            "schema_version": "1.1",
            "engine_version": CURRENT_ENGINE_VERSION,
            "as_of_at": as_of_at.isoformat(
                sep=" ", timespec="seconds"
            ),
            "cohort": list(DEMO_IDS),
            "ruleset": (
                {
                    key: ruleset[key]
                    for key in (
                        "id",
                        "ruleset_code",
                        "version",
                        "content_hash",
                        "status",
                    )
                }
                if ruleset
                else None
            ),
            "patients": [
                {
                    key: value
                    for key, value in row.items()
                    if key != "v2_run_id"
                }
                for row in rows
            ],
            "failures": failures,
            "checks": checks,
        }
        report = {**report_body, "patients": rows}
        report["report_hash"] = content_hash(report_core(report))
        report.update(
            {
                "generated_at": iran_now().isoformat(
                    sep=" ", timespec="seconds"
                ),
                "status": (
                    "PASS" if all(checks.values()) else "BLOCKED"
                ),
            }
        )
        self.state.put_json("last_report", report)
        log_activity(
            "clinical_v2_compare",
            (
                f"Activation report {report['status']} "
                f"{report['report_hash']} engine={CURRENT_ENGINE_VERSION}"
            ),
            user_id=0,
            username=(created_by or "activation-audit").strip(),
        )
        return report

    @staticmethod
    def render_text(report: dict[str, Any]) -> str:
        lines = [
            (
                "Clinical Engine v2 activation report: "
                f"{report.get('status', 'UNKNOWN')}"
            ),
            f"report_hash: {report.get('report_hash', '-')}",
            f"engine_version: {report.get('engine_version', '-')}",
            f"as_of_at: {report.get('as_of_at', '-')}",
            (
                "ruleset: "
                f"{(report.get('ruleset') or {}).get('version', 'NONE')}"
            ),
            "checks:",
        ]
        for name, passed in (report.get("checks") or {}).items():
            lines.append(
                f"  {'PASS' if passed else 'FAIL'}  {name}"
            )
        lines.append("patients:")
        for row in report.get("patients") or []:
            lines.append(
                f"  {row['national_id']}: "
                f"v2={row['v2_recommendations']} "
                f"errors={row['v2_errors']} "
                f"status={row['v2_run_status']}"
            )
        for failure in report.get("failures") or []:
            lines.append(
                f"  FAILURE {failure['national_id']}: "
                f"{failure['code']}"
            )
        return "\n".join(lines)

    def approve(
        self,
        role: str,
        *,
        reviewer: str,
        report_hash: str,
        note: str,
    ) -> None:
        role = role.strip().lower()
        if role not in {"clinical", "technical"}:
            raise ActivationGateError(
                "role must be clinical or technical"
            )
        report = self.state.get_json("last_report")
        if (
            not valid_report(report)
            or report.get("report_hash") != report_hash
        ):
            raise ActivationGateError(
                "approval must reference the current passing report"
            )
        if not reviewer.strip() or not note.strip():
            raise ActivationGateError("reviewer and note are required")
        self.state.put_json(
            f"approval_{role}",
            {
                "role": role,
                "reviewer": reviewer.strip(),
                "note": note.strip(),
                "report_hash": report_hash,
                "engine_version": CURRENT_ENGINE_VERSION,
                "approved_at": iran_now().isoformat(
                    sep=" ", timespec="seconds"
                ),
            },
        )
        log_activity(
            "clinical_v2_approve",
            f"{role} approval for report {report_hash}",
            user_id=0,
            username=reviewer.strip(),
        )

    def activate(self, mode: str, *, activated_by: str) -> dict:
        mode = mode.strip().lower()
        if mode not in {"on_selected", "on"}:
            raise ActivationGateError(
                "activation mode must be on_selected or on"
            )
        report = self.state.get_json("last_report")
        if not valid_report(report):
            raise ActivationGateError(
                "a current passing comparison report is required"
            )
        for role in ("clinical", "technical"):
            approval = self.state.get_json(f"approval_{role}")
            if (
                not approval
                or approval.get("report_hash")
                != report["report_hash"]
                or approval.get("engine_version")
                != CURRENT_ENGINE_VERSION
            ):
                raise ActivationGateError(
                    f"current {role} approval is required"
                )
        ruleset = report.get("ruleset") or {}
        current = self.rules.get_ruleset(
            int(ruleset.get("id") or 0)
        )
        if not current or current["status"] not in {
            "SILENT",
            "ACTIVE",
        }:
            raise ActivationGateError(
                "the compared ruleset is no longer frozen"
            )
        if mode == "on":
            verification = self.state.get_json(
                "selected_rollout_verification"
            )
            if (
                not self.state.valid_seal("on_selected")
                or not verification
                or verification.get("report_hash")
                != report["report_hash"]
                or verification.get("engine_version")
                != CURRENT_ENGINE_VERSION
            ):
                raise ActivationGateError(
                    "on requires verified on_selected rollout"
                )
            if current["status"] != "ACTIVE":
                raise ActivationGateError(
                    "on requires an ACTIVE ruleset"
                )
        actor = activated_by.strip()
        if not actor:
            raise ActivationGateError("activated_by is required")
        body = {
            "mode": mode,
            "engine_version": CURRENT_ENGINE_VERSION,
            "ruleset_id": int(current["id"]),
            "report_hash": report["report_hash"],
            "activated_by": actor,
            "activated_at": iran_now().isoformat(
                sep=" ", timespec="seconds"
            ),
        }
        seal = {**body, "seal_hash": content_hash(body)}
        self.state.put_json("seal", seal)
        self.state.set_raw_mode(mode)
        log_activity(
            "clinical_v2_activate",
            (
                f"Activated {mode} engine={CURRENT_ENGINE_VERSION} "
                f"report={report['report_hash']}"
            ),
            user_id=0,
            username=actor,
        )
        return seal

    def verify_selected_rollout(
        self,
        *,
        reviewer: str,
        note: str,
    ) -> None:
        report = self.state.get_json("last_report")
        if not self.state.valid_seal("on_selected") or not report:
            raise ActivationGateError(
                "selected rollout is not active"
            )
        if not reviewer.strip() or not note.strip():
            raise ActivationGateError("reviewer and note are required")
        self.state.put_json(
            "selected_rollout_verification",
            {
                "report_hash": report["report_hash"],
                "engine_version": CURRENT_ENGINE_VERSION,
                "reviewer": reviewer.strip(),
                "note": note.strip(),
                "verified_at": iran_now().isoformat(
                    sep=" ", timespec="seconds"
                ),
            },
        )
        log_activity(
            "clinical_v2_verify_selected",
            f"Verified selected rollout for {report['report_hash']}",
            user_id=0,
            username=reviewer.strip(),
        )

    def promote_compared_ruleset(self, *, promoted_by: str) -> None:
        report = self.state.get_json("last_report")
        verification = self.state.get_json(
            "selected_rollout_verification"
        )
        if (
            not valid_report(report)
            or not self.state.valid_seal("on_selected")
        ):
            raise ActivationGateError(
                "a valid selected rollout is required"
            )
        if (
            not verification
            or verification.get("report_hash")
            != report["report_hash"]
            or verification.get("engine_version")
            != CURRENT_ENGINE_VERSION
        ):
            raise ActivationGateError(
                "selected rollout verification is required"
            )
        ruleset_id = int(
            (report.get("ruleset") or {}).get("id") or 0
        )
        self.rules.promote_silent_ruleset(
            ruleset_id,
            promoted_by=promoted_by,
        )
        self.activate("on_selected", activated_by=promoted_by)
        log_activity(
            "clinical_v2_promote_ruleset",
            f"Promoted ruleset #{ruleset_id} to ACTIVE",
            user_id=0,
            username=promoted_by.strip(),
        )

    def rollback(self, *, rolled_back_by: str, reason: str) -> None:
        if not rolled_back_by.strip() or not reason.strip():
            raise ActivationGateError(
                "rollback actor and reason are required"
            )
        previous = self.state.raw_mode()
        self.state.set_raw_mode("off")
        self.state.delete("seal")
        self.state.put_json(
            "last_rollback",
            {
                "previous_mode": previous,
                "engine_version": CURRENT_ENGINE_VERSION,
                "rolled_back_by": rolled_back_by.strip(),
                "reason": reason.strip(),
                "rolled_back_at": iran_now().isoformat(
                    sep=" ", timespec="seconds"
                ),
            },
        )
        log_activity(
            "clinical_v2_rollback",
            f"Rolled back from {previous}: {reason.strip()}",
            user_id=0,
            username=rolled_back_by.strip(),
        )
