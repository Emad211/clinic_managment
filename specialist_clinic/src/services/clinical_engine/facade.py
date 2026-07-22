"""Read-only patient-detail projection for selected Clinical Engine v2 runs."""

from __future__ import annotations

from collections import Counter
from typing import Any

from src.adapters.sqlite.clinical_engine_audit_repo import ClinicalEngineAuditRepository
from src.adapters.sqlite.clinical_engine_fact_repo import ClinicalEngineFactRepository


_GROUPS = {
    "redflag": (0, "هشدارهای فوری", "danger"),
    "safety_alert": (1, "هشدارهای ایمنی", "warn"),
    "suggest_med": (2, "گزینه‌های دارویی", "info"),
    "set_target": (3, "اهداف پیشنهادی", "info"),
    "classify": (4, "ارزیابی و طبقه‌بندی", "info"),
    "flag_risk": (5, "ریسک‌های شناسایی‌شده", "info"),
    "create_followup": (6, "پیگیری پیشنهادی", "info"),
    "schedule_screening": (7, "غربالگری پیشنهادی", "info"),
    "vaccine": (8, "واکسیناسیون پیشنهادی", "info"),
    "educate": (9, "آموزش پیشنهادی", "info"),
}


class ClinicalEngineReadOnlyFacade:
    """Expose audited v2 output without evaluating, accepting, or mutating it."""

    def __init__(self, facts=None, audit=None):
        self.facts = facts or ClinicalEngineFactRepository()
        self.audit = audit or ClinicalEngineAuditRepository()

    def patient_detail(self, patient_link_id: int) -> dict[str, Any] | None:
        mode = self.facts.get_mode()
        if mode not in {"on_selected", "on"}:
            return None
        if mode == "on_selected" and not self.facts.is_selected_patient(patient_link_id):
            return None
        run = self.audit.latest_presentable_run(patient_link_id)
        if not run:
            return {
                "empty": True,
                "groups": [],
                "notices": [],
                "message_fa": "برای این بیمار هنوز اجرای قابل نمایش نسخهٔ ۲ ثبت نشده است.",
            }

        grouped: dict[str, list[dict[str, Any]]] = {}
        notices = []
        outcome_counts = Counter()
        for evaluation in run["evaluations"]:
            outcome = evaluation["outcome"]
            outcome_counts[outcome] += 1
            recommendation = evaluation.get("recommendation")
            if outcome == "FIRED" and recommendation:
                recommendation_event = evaluation.get("recommendation_event")
                if not recommendation_event:
                    notices.append({
                        "rule_code": evaluation["rule_code"],
                        "title": evaluation["rule_title"],
                        "outcome": "ERROR",
                        "reason_code": "RECOMMENDATION_AUDIT_MISSING",
                        "message": "پیشنهاد به دلیل نبود رویداد audit قابل نمایش نیست.",
                        "data_issues": [],
                    })
                    continue
                # Fail closed: a recommendation is not returned to the template
                # unless its actual presentation can be recorded durably.
                self.audit.append_presentation_once(
                    int(recommendation_event["id"]),
                    patient_link_id=patient_link_id,
                )
                action_type = recommendation["action_type"]
                grouped.setdefault(action_type, []).append(
                    self._recommendation_item(evaluation)
                )
                continue
            if outcome in {"NEEDS_DATA", "ERROR"}:
                notices.append(self._notice(evaluation))
            elif outcome == "SUPPRESSED":
                suppression = evaluation.get("suppression") or {}
                if suppression.get("reason_code") != "DEDUPLICATED":
                    notices.append(self._notice(evaluation))

        groups = []
        for action_type, items in grouped.items():
            order, label, tone = _GROUPS.get(
                action_type, (99, "سایر پیشنهادها", "info")
            )
            groups.append({
                "action_type": action_type,
                "label": label,
                "tone": tone,
                "order": order,
                "items": sorted(items, key=lambda item: item["rule_code"]),
            })
        groups.sort(key=lambda group: (group["order"], group["label"]))
        return {
            "empty": not groups and not notices,
            "run_id": run["run_id"],
            "as_of_at": run["as_of_at"],
            "run_status": run["run_status"],
            "engine_version": run["engine_version"],
            "groups": groups,
            "notices": notices,
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "message_fa": "در این اجرا پیشنهاد قابل نمایش یا مسئلهٔ داده‌ای وجود ندارد.",
        }

    @staticmethod
    def _recommendation_item(evaluation: dict[str, Any]) -> dict[str, Any]:
        recommendation = evaluation["recommendation"]
        merged_codes = recommendation.get("merged_rule_codes") or [
            evaluation["rule_code"]
        ]
        merged_titles = recommendation.get("merged_titles") or [
            recommendation.get("title_fa") or evaluation["rule_title"]
        ]
        return {
            "rule_code": evaluation["rule_code"],
            "action_type": recommendation["action_type"],
            "title": recommendation.get("title_fa") or evaluation["rule_title"],
            "text": recommendation["text_fa"],
            "presentation": recommendation["presentation"],
            "requires_confirmation": recommendation[
                "requires_clinician_confirmation"
            ],
            "suggestion_only": True,
            "merged_rule_codes": merged_codes,
            "reasons": merged_titles,
            "fact_ids": sorted(ClinicalEngineReadOnlyFacade._trace_values(
                evaluation.get("trace") or {}, "fact_ids"
            )),
            "data_issues": evaluation.get("data_issues") or [],
            "recommendation_event_id": int(
                evaluation["recommendation_event"]["id"]
            ),
            "current_decision": evaluation["recommendation_event"].get(
                "current_decision"
            ),
        }

    @staticmethod
    def _notice(evaluation: dict[str, Any]) -> dict[str, Any]:
        suppression = evaluation.get("suppression") or {}
        error = evaluation.get("error") or {}
        message = suppression.get("message_fa")
        if not message:
            message = {
                "NEEDS_DATA": "دادهٔ کافی برای ارزیابی ایمن این قاعده وجود ندارد.",
                "ERROR": "ارزیابی این قاعده با خطا متوقف شد.",
            }.get(evaluation["outcome"], "این خروجی به‌صورت ایمن متوقف شد.")
        return {
            "rule_code": evaluation["rule_code"],
            "title": evaluation["rule_title"],
            "outcome": evaluation["outcome"],
            "reason_code": suppression.get("reason_code") or error.get("code"),
            "message": message,
            "data_issues": evaluation.get("data_issues") or [],
        }

    @staticmethod
    def _trace_values(node: dict[str, Any], key: str) -> set[str]:
        values = {str(value) for value in (node.get(key) or [])}
        for child in node.get("children") or []:
            values.update(ClinicalEngineReadOnlyFacade._trace_values(child, key))
        return values
