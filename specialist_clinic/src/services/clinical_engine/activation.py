"""Evidence-bound comparison, approval, activation and rollback gates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository, content_hash, report_core, valid_report,
)
from src.adapters.sqlite.clinical_engine_audit_repo import ClinicalEngineAuditRepository
from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository
from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository
from src.common.utils import iran_now
from src.services.clinical_engine.fact_builder import ShadowFactCapture
from src.services.rule_engine import RuleEngine
from src.services.activity_logger import log_activity


DEMO_IDS = tuple(f"TEST{i:04d}" for i in range(1, 11))
SAFETY_ACTIONS = {"redflag", "safety_alert"}


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
    """Build a reproducible ten-patient gate; never self-approve or self-activate."""

    def __init__(self, *, state=None, rules=None, audit=None,
                 legacy=None, capture_factory=None):
        self.state = state or ClinicalEngineActivationRepository()
        self.rules = rules or ClinicalEngineRulesRepository()
        self.audit = audit or ClinicalEngineAuditRepository()
        self.legacy = legacy or RuleEngine(capture_shadow=False)
        self.capture_factory = capture_factory or self._capture

    def _capture(self):
        facts = _ForcedShadowFacts()
        return ShadowFactCapture(repository=facts, audit=self.audit, rules=self.rules)

    @staticmethod
    def _safety_diff(diff_type: str, national_id: str, legacy_id=None, rule_code=None):
        body = {"type": diff_type, "national_id": national_id,
                "legacy_rule_id": legacy_id, "v2_rule_code": rule_code}
        return {**body, "difference_id": content_hash(body)[:20]}

    def build_report(self, *, as_of_at: datetime | None = None,
                     created_by: str = "activation-audit") -> dict[str, Any]:
        as_of_at = as_of_at or iran_now()
        patients = self.state.demo_patients()
        found = {str(p["national_id"]).upper(): p for p in patients}
        rows, failures, all_differences = [], [], []
        ruleset = self.rules.active_ruleset("general-outpatient")
        adjudications = self.state.get_json("adjudications", {}) or {}

        for national_id in DEMO_IDS:
            patient = found.get(national_id)
            if not patient:
                failures.append({"national_id": national_id, "code": "DEMO_PATIENT_MISSING"})
                continue
            pid = int(patient["id"])
            try:
                legacy = self.legacy.evaluate(pid, as_of_at=as_of_at)
                run_id = self.capture_factory().capture(
                    pid, as_of_at=as_of_at, created_by=created_by,
                )
                run = self.audit.decoded_run(run_id) if run_id else None
                if not run:
                    raise RuntimeError("v2 audit run was not persisted")
            except Exception as exc:
                failures.append({"national_id": national_id,
                                 "code": "COMPARISON_RUN_FAILED",
                                 "detail": type(exc).__name__})
                continue

            legacy_safety = {int(r["id"]): r for r in legacy
                             if r.get("action_type") in SAFETY_ACTIONS}
            v2_fired = [e for e in run["evaluations"]
                        if e.get("outcome") == "FIRED" and e.get("recommendation")]
            mapped_fired = {int(e["legacy_rule_id"]): e for e in v2_fired
                            if e.get("legacy_rule_id") is not None}
            differences = []
            for legacy_id in sorted(set(legacy_safety) - set(mapped_fired)):
                differences.append(self._safety_diff(
                    "LEGACY_SAFETY_MISSING_IN_V2", national_id, legacy_id=legacy_id,
                ))
            for evaluation in v2_fired:
                if evaluation.get("action_type") not in SAFETY_ACTIONS:
                    continue
                legacy_id = evaluation.get("legacy_rule_id")
                if legacy_id is None or int(legacy_id) not in legacy_safety:
                    differences.append(self._safety_diff(
                        "V2_SAFETY_NOT_IN_LEGACY", national_id,
                        legacy_id=legacy_id, rule_code=evaluation.get("rule_code"),
                    ))
            for item in differences:
                decision = adjudications.get(item["difference_id"])
                item["adjudication"] = decision if self._valid_adjudication(decision) else None
                item["gate_cleared"] = bool(
                    item["adjudication"]
                    and item["adjudication"]["classification"]
                    in {"EXPLAINED_ACCEPTABLE", "LEGACY_DEFECT"}
                )
            all_differences.extend(differences)
            rows.append({
                "national_id": national_id, "patient_link_id": pid,
                "legacy_rule_ids": sorted(int(r["id"]) for r in legacy),
                "legacy_recommendations": len(legacy), "v2_run_id": run_id,
                "v2_fact_snapshot_hash": run.get("fact_snapshot_hash"),
                "v2_run_status": run["run_status"],
                "v2_rule_codes": sorted(e["rule_code"] for e in v2_fired),
                "v2_recommendations": len(v2_fired),
                "v2_errors": sum(e.get("outcome") == "ERROR" for e in run["evaluations"]),
                "safety_differences": differences,
            })

        unexplained = sum(not d.get("gate_cleared") for d in all_differences)
        error_count = sum(row["v2_errors"] for row in rows)
        max_cards = max((row["v2_recommendations"] for row in rows), default=0)
        checks = {
            "exact_demo_cohort": len(rows) == 10 and not failures,
            "ruleset_frozen": bool(ruleset and ruleset["status"] in {"SILENT", "ACTIVE"}),
            "zero_run_failures": not failures and all(
                row["v2_run_status"] == "COMPLETED" for row in rows
            ),
            "zero_rule_errors": error_count == 0,
            "zero_unexplained_safety_differences": unexplained == 0,
            # Conservative technical default. Clinical/product owner must approve
            # the report that contains this exact threshold before activation.
            "burden_at_most_12_cards_per_patient": max_cards <= 12,
        }
        report_body = {
            "schema_version": "1.0", "as_of_at": as_of_at.isoformat(sep=" ", timespec="seconds"),
            "cohort": list(DEMO_IDS),
            "ruleset": ({k: ruleset[k] for k in ("id", "ruleset_code", "version", "content_hash", "status")}
                        if ruleset else None),
            "patients": [{k: v for k, v in row.items() if k != "v2_run_id"} for row in rows],
            "failures": failures, "checks": checks,
        }
        report = {**report_body, "patients": rows}
        report["report_hash"] = content_hash(report_core(report))
        report.update({
                  "generated_at": iran_now().isoformat(sep=" ", timespec="seconds"),
                  "status": "PASS" if all(checks.values()) else "BLOCKED",
        })
        self.state.put_json("last_report", report)
        log_activity(
            "clinical_v2_compare", f"Activation report {report['status']} {report['report_hash']}",
            user_id=0, username=(created_by or "activation-audit").strip(),
        )
        return report

    @staticmethod
    def render_text(report: dict[str, Any]) -> str:
        """Compact operator-facing rendering; JSON remains the machine contract."""
        lines = [
            f"Clinical Engine v2 activation report: {report.get('status', 'UNKNOWN')}",
            f"report_hash: {report.get('report_hash', '-')}",
            f"as_of_at: {report.get('as_of_at', '-')}",
            f"ruleset: {(report.get('ruleset') or {}).get('version', 'NONE')}",
            "checks:",
        ]
        for name, passed in (report.get("checks") or {}).items():
            lines.append(f"  {'PASS' if passed else 'FAIL'}  {name}")
        lines.append("patients:")
        for row in report.get("patients") or []:
            unexplained = sum(not item.get("gate_cleared")
                              for item in row.get("safety_differences") or [])
            lines.append(
                f"  {row['national_id']}: legacy={row['legacy_recommendations']} "
                f"v2={row['v2_recommendations']} errors={row['v2_errors']} "
                f"unexplained_safety={unexplained}"
            )
        for failure in report.get("failures") or []:
            lines.append(f"  FAILURE {failure['national_id']}: {failure['code']}")
        return "\n".join(lines)

    @staticmethod
    def _valid_adjudication(value) -> bool:
        return bool(isinstance(value, dict) and value.get("reviewer")
                    and value.get("classification") in {"EXPLAINED_ACCEPTABLE", "V2_DEFECT", "LEGACY_DEFECT"}
                    and value.get("note"))

    def adjudicate(self, difference_id: str, *, reviewer: str,
                   classification: str, note: str) -> None:
        decision = {"reviewer": reviewer.strip(), "classification": classification.strip().upper(),
                    "note": note.strip(), "recorded_at": iran_now().isoformat(sep=" ", timespec="seconds")}
        if not difference_id or not self._valid_adjudication(decision):
            raise ActivationGateError("complete, valid safety adjudication is required")
        values = self.state.get_json("adjudications", {}) or {}
        values[difference_id] = decision
        self.state.put_json("adjudications", values)
        log_activity("clinical_v2_adjudicate", f"Safety difference {difference_id}: {decision['classification']}",
                     user_id=0, username=decision["reviewer"])

    def approve(self, role: str, *, reviewer: str, report_hash: str,
                note: str) -> None:
        role = role.strip().lower()
        if role not in {"clinical", "technical"}:
            raise ActivationGateError("role must be clinical or technical")
        report = self.state.get_json("last_report")
        if not valid_report(report) or report.get("report_hash") != report_hash:
            raise ActivationGateError("approval must reference the current passing report")
        if not reviewer.strip() or not note.strip():
            raise ActivationGateError("reviewer and note are required")
        self.state.put_json(f"approval_{role}", {
            "role": role, "reviewer": reviewer.strip(), "note": note.strip(),
            "report_hash": report_hash,
            "approved_at": iran_now().isoformat(sep=" ", timespec="seconds"),
        })
        log_activity("clinical_v2_approve", f"{role} approval for report {report_hash}",
                     user_id=0, username=reviewer.strip())

    def activate(self, mode: str, *, activated_by: str) -> dict:
        mode = mode.strip().lower()
        if mode not in {"on_selected", "on"}:
            raise ActivationGateError("activation mode must be on_selected or on")
        report = self.state.get_json("last_report")
        if not valid_report(report):
            raise ActivationGateError("a current passing comparison report is required")
        for role in ("clinical", "technical"):
            approval = self.state.get_json(f"approval_{role}")
            if not approval or approval.get("report_hash") != report["report_hash"]:
                raise ActivationGateError(f"current {role} approval is required")
        ruleset = report.get("ruleset") or {}
        current = self.rules.get_ruleset(int(ruleset.get("id") or 0))
        if not current or current["status"] not in {"SILENT", "ACTIVE"}:
            raise ActivationGateError("the compared ruleset is no longer frozen")
        if mode == "on":
            verification = self.state.get_json("selected_rollout_verification")
            if not self.state.valid_seal("on_selected") or not verification \
                    or verification.get("report_hash") != report["report_hash"]:
                raise ActivationGateError("on requires verified on_selected rollout")
            if current["status"] != "ACTIVE":
                raise ActivationGateError("on requires an ACTIVE ruleset")
        actor = activated_by.strip()
        if not actor:
            raise ActivationGateError("activated_by is required")
        body = {"mode": mode, "ruleset_id": int(current["id"]),
                "report_hash": report["report_hash"], "activated_by": actor,
                "activated_at": iran_now().isoformat(sep=" ", timespec="seconds")}
        seal = {**body, "seal_hash": content_hash(body)}
        self.state.put_json("seal", seal)
        self.state.set_raw_mode(mode)
        log_activity("clinical_v2_activate", f"Activated mode {mode} for report {report['report_hash']}",
                     user_id=0, username=actor)
        return seal

    def verify_selected_rollout(self, *, reviewer: str, note: str) -> None:
        report = self.state.get_json("last_report")
        if not self.state.valid_seal("on_selected") or not report:
            raise ActivationGateError("selected rollout is not active")
        if not reviewer.strip() or not note.strip():
            raise ActivationGateError("reviewer and note are required")
        self.state.put_json("selected_rollout_verification", {
            "report_hash": report["report_hash"], "reviewer": reviewer.strip(),
            "note": note.strip(), "verified_at": iran_now().isoformat(sep=" ", timespec="seconds"),
        })
        log_activity("clinical_v2_verify_selected", f"Verified selected rollout for {report['report_hash']}",
                     user_id=0, username=reviewer.strip())

    def promote_compared_ruleset(self, *, promoted_by: str) -> None:
        """Promote only after the selected rollout tied to this report is verified."""
        report = self.state.get_json("last_report")
        verification = self.state.get_json("selected_rollout_verification")
        if not valid_report(report) or not self.state.valid_seal("on_selected"):
            raise ActivationGateError("a valid selected rollout is required")
        if not verification or verification.get("report_hash") != report["report_hash"]:
            raise ActivationGateError("selected rollout verification is required")
        ruleset_id = int((report.get("ruleset") or {}).get("id") or 0)
        self.rules.promote_silent_ruleset(ruleset_id, promoted_by=promoted_by)
        log_activity("clinical_v2_promote_ruleset", f"Promoted ruleset #{ruleset_id} to ACTIVE",
                     user_id=0, username=promoted_by.strip())

    def rollback(self, *, rolled_back_by: str, reason: str) -> None:
        if not rolled_back_by.strip() or not reason.strip():
            raise ActivationGateError("rollback actor and reason are required")
        previous = self.state.raw_mode()
        self.state.set_raw_mode("off")
        self.state.delete("seal")
        self.state.put_json("last_rollback", {
            "previous_mode": previous, "rolled_back_by": rolled_back_by.strip(),
            "reason": reason.strip(),
            "rolled_back_at": iran_now().isoformat(sep=" ", timespec="seconds"),
        })
        log_activity("clinical_v2_rollback", f"Rolled back from {previous}: {reason.strip()}",
                     user_id=0, username=rolled_back_by.strip())
