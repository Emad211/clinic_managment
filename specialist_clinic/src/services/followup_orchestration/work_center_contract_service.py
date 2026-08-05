"""Presentation contract for Work Center outcome and evidence forms.

The UI receives only options accepted by the authoritative clinical task contract or
encounter-plan commitment type. This module adds no clinical rule; it translates the
existing immutable contracts into labels and field requirements.
"""
from __future__ import annotations

import sqlite3

from src.security.permissions import Permission
from src.services.encounter_plan_commitment_service import (
    EVIDENCE_LABELS,
    OUTCOME_LABELS as PLAN_OUTCOME_LABELS,
    _ALLOWED_EVIDENCE,
)
from src.services.followup_orchestration.work_center_action_service import (
    WorkCenterActionService,
)


CLINICAL_OUTCOME_LABELS = {
    "OBSERVATION": "مشاهده یا اندازه‌گیری",
    "PATIENT_REPORTED": "گزارش بیمار",
    "ENCOUNTER_COMPLETED": "مراجعه انجام شد",
    "PROCEDURE_COMPLETED": "اقدام انجام شد",
    "LAB_COMPLETED": "آزمایش انجام شد",
    "OTHER": "سایر",
}


class WorkCenterContractService:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def build(
        self,
        episode_id: str,
        *,
        permissions: frozenset[Permission],
    ) -> dict:
        action = WorkCenterActionService(self.db).describe(
            episode_id,
            permissions=permissions,
        )
        action["can_message"] = Permission.SMS_APPROVAL_REVIEW in permissions
        action["clinical_contract"] = None
        action["plan_contract"] = None

        if not action.get("available"):
            return action

        if action.get("kind") == "clinical":
            contract = action.get("task_contract") or None
            if not contract:
                action["can_complete_clinical"] = False
                action["clinical_contract_reason"] = (
                    "قرارداد نتیجهٔ این پیگیری در دسترس نیست."
                )
                return action
            allowed = [
                {
                    "code": code,
                    "label": CLINICAL_OUTCOME_LABELS.get(code, code),
                }
                for code in contract.get("allowed_outcome_types") or []
                if code in CLINICAL_OUTCOME_LABELS
            ]
            required_fact_keys = [
                str(value)
                for value in contract.get("required_fact_keys") or []
                if str(value).strip()
            ]
            action["clinical_contract"] = {
                "allowed_outcomes": allowed,
                "required_fact_keys": required_fact_keys,
                "requires_fact": bool(required_fact_keys),
                "requires_value": (
                    str(contract.get("canonical_ingestion") or "").upper()
                    == "REQUIRED"
                ),
                "minimum_verification": str(
                    contract.get("minimum_verification") or "CONFIRMED"
                ),
                "canonical_ingestion": str(
                    contract.get("canonical_ingestion") or "NONE"
                ),
                "urgency": str(contract.get("urgency") or "ROUTINE"),
            }
            action["can_complete_clinical"] = bool(
                action.get("can_complete_clinical") and allowed
            )

        if action.get("kind") == "plan":
            context = action.get("plan_context") or {}
            commitment_type = str(
                context.get("commitment_type") or ""
            ).strip().upper()
            allowed_codes = sorted(_ALLOWED_EVIDENCE.get(commitment_type, set()))
            action["plan_contract"] = {
                "commitment_type": commitment_type,
                "commitment_label": str(
                    context.get("commitment_type_label")
                    or context.get("instruction")
                    or commitment_type
                ),
                "allowed_evidence": [
                    {"code": code, "label": EVIDENCE_LABELS.get(code, code)}
                    for code in allowed_codes
                ],
                "allowed_outcomes": [
                    {"code": code, "label": label}
                    for code, label in PLAN_OUTCOME_LABELS.items()
                ],
            }
            action["can_complete_plan"] = bool(
                action.get("can_complete_plan") and allowed_codes
            )

        return action


__all__ = [
    "CLINICAL_OUTCOME_LABELS",
    "WorkCenterContractService",
]
