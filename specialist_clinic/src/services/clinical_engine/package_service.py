"""Guided import and clinical review of bundled v2 rule packages."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from src.adapters.sqlite.clinical_engine_rules_repo import ClinicalEngineRulesRepository
from src.adapters.sqlite.clinical_engine_activation_repo import ClinicalEngineActivationRepository
from src.services.activity_logger import log_activity
from src.services.clinical_engine.compiler import RuleCompiler
from src.services.clinical_engine.package_contract import load_rule_package
from src.common.utils import iran_now
from src.domain.clinical_engine.release import (
    CURRENT_BUNDLED_PACKAGE_VERSION as PACKAGE_VERSION,
    RULESET_CODE,
    base_ruleset_version,
)


_FACT_LABELS = {
    "condition.codes": "فهرست تشخیص‌های فعال",
    "condition.diabetes": "تشخیص دیابت",
    "demographic.age_years": "سن کامل بیمار",
    "observation.bp_systolic": "آخرین فشار خون سیستولیک",
    "observation.bp_diastolic": "آخرین فشار خون دیاستولیک",
    "observation.egfr": "آخرین eGFR",
    "medication.classes": "فهرست داروهای فعال",
}
_OPERATOR_LABELS = {
    "==": "برابر با",
    "!=": "نابرابر با",
    ">": "بیشتر از",
    ">=": "بیشتر یا مساوی",
    "<": "کمتر از",
    "<=": "کمتر یا مساوی",
    "has": "شامل",
}
_VALUE_LABELS = {
    True: "تأییدشده",
    False: "ردشده",
    "diabetes": "دیابت",
    "metformin": "متفورمین",
}
_UNIT_LABELS = {
    "a": "سال",
    "mm[Hg]": "میلی‌متر جیوه",
    "mL/min/{1.73_m2}": "میلی‌لیتر در دقیقه به‌ازای ۱٫۷۳ مترمربع",
}


def _condition_lines(node: dict) -> tuple[str, list[dict]]:
    """Render a reviewed DSL predicate without changing its semantics."""
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        lines: list[dict] = []
        for child in node[key]:
            _, child_lines = _condition_lines(child)
            lines.extend(child_lines)
        return ("همهٔ شرط‌ها" if key == "all" else "حداقل یکی از شرط‌ها"), lines

    selector = node.get("selector") or {}
    within_days = selector.get("within_days")
    return "شرط", [{
        "fact": _FACT_LABELS.get(node.get("fact"), node.get("fact", "دادهٔ نامشخص")),
        "operator": _OPERATOR_LABELS.get(node.get("op"), node.get("op", "")),
        "value": _VALUE_LABELS.get(node.get("value"), node.get("value")),
        "unit": _UNIT_LABELS.get(node.get("unit"), node.get("unit")) if node.get("unit") else "",
        "within_days": within_days,
    }]


def _automation_limit(raw: dict) -> str:
    params = raw["recommendation"].get("params") or {}
    if params.get("do_not_modify_medication"):
        return "هیچ دارو یا نسخه‌ای را خودکار تغییر نمی‌دهد؛ تصمیم نهایی با پزشک است."
    if params.get("do_not_auto_refer") or params.get("do_not_auto_message"):
        return "هیچ ارجاع یا پیامی را خودکار ثبت یا ارسال نمی‌کند؛ تصمیم نهایی با پزشک است."
    return "فقط پیشنهاد تصمیم‌یار نمایش می‌دهد و اقدام بالینی خودکار انجام نمی‌دهد."


def _package_dir() -> Path:
    relative = Path("src/domain/clinical_engine/rule_artifacts") / PACKAGE_VERSION
    source = Path(__file__).resolve().parents[2] / "domain" / "clinical_engine" / "rule_artifacts" / PACKAGE_VERSION
    if source.exists():
        return source
    bundle_root = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return bundle_root / relative


class ClinicalRulePackageService:
    """Turn bundled, compiled drafts into a clinician-approved SILENT package.

    Preparation is technical and idempotent. Freezing is a separate explicit
    clinical attestation and never happens as a side-effect of preparation.
    """

    def __init__(self, *, rules=None, compiler=None, activation=None):
        self.rules = rules or ClinicalEngineRulesRepository()
        self.compiler = compiler or RuleCompiler()
        self.activation = activation or ClinicalEngineActivationRepository()

    def prepare(self, *, actor: str) -> dict:
        actor = (actor or "").strip()
        if not actor:
            raise ValueError("نام کاربر آماده‌ساز الزامی است")
        package = load_rule_package(
            _package_dir(),
            expected_version=PACKAGE_VERSION,
            expected_ruleset_code=RULESET_CODE,
            compiler=self.compiler,
        )
        manifest = package.manifest
        latest = self.rules.latest_ruleset(RULESET_CODE)
        same_package = bool(
            latest
            and base_ruleset_version(latest.get("version")) == manifest["version"]
        )
        if latest and latest["status"] == "DRAFT" and same_package:
            return latest

        members = []
        for item, compiled in zip(
            manifest.get("rules") or [], package.compiled_rules, strict=True
        ):
            rule_id = self.rules.create_rule_version(
                compiled, created_by=actor,
                change_note="Imported by the guided clinical package workflow",
            )
            stored = self.rules.get_rule_version(rule_id)
            if stored["lifecycle_status"] == "DRAFT":
                self.rules.mark_validated(rule_id, compiled)
            members.append({
                "rule_version_id": rule_id,
                "sort_order": int(item.get("sort_order", 100)),
            })
        version = manifest["version"]
        if latest and same_package:
            version = f"{manifest['version']}-attempt.{int(latest['id']) + 1}"
        ruleset_id = self.rules.create_ruleset(
            manifest["ruleset_code"], version, members,
            created_by=actor,
            note="بستهٔ اولیهٔ فنی؛ نیازمند بازبینی و تأیید بالینی",
        )
        log_activity(
            "clinical_v2_package_prepare",
            f"Prepared ruleset {ruleset_id} ({len(members)} rules)",
            user_id=0, username=actor,
        )
        return self.rules.get_ruleset(ruleset_id)

    def approve_and_freeze(self, ruleset_id: int, *, reviewer: str,
                           attested_codes: list[str], note: str) -> dict:
        reviewer = (reviewer or "").strip()
        note = (note or "").strip()
        if not reviewer or not note:
            raise ValueError("نام بازبین و یادداشت بالینی الزامی است")
        package = load_rule_package(
            _package_dir(),
            expected_version=PACKAGE_VERSION,
            expected_ruleset_code=RULESET_CODE,
            compiler=self.compiler,
        )
        ruleset = self.rules.get_ruleset(int(ruleset_id))
        if not ruleset or ruleset["ruleset_code"] != RULESET_CODE:
            raise LookupError("بستهٔ قواعد پیدا نشد")
        if base_ruleset_version(ruleset.get("version")) != PACKAGE_VERSION:
            raise ValueError("این بسته قدیمی است؛ ابتدا بستهٔ اصلاح‌شدهٔ فعلی را آماده کنید")
        if ruleset["status"] != "DRAFT":
            raise ValueError("فقط بستهٔ درحال بازبینی قابل تأیید است")
        expected_hashes = {
            compiled.definition.rule_code: compiled.content_hash
            for compiled in package.compiled_rules
        }
        stored_hashes = {
            str(member["rule_code"]): str(member["content_hash"])
            for member in ruleset["members"]
        }
        if stored_hashes != expected_hashes:
            raise ValueError("اعضای بستهٔ ذخیره‌شده با بستهٔ immutable برنامه یکسان نیستند")
        expected = set(expected_hashes)
        if set(attested_codes or []) != expected:
            raise ValueError("هر قاعده باید جداگانه مطالعه و علامت‌گذاری شود")
        for member in ruleset["members"]:
            if member["lifecycle_status"] == "VALIDATED":
                self.rules.approve_rule_version(
                    int(member["rule_version_id"]), approved_by=reviewer,
                )
            elif member["lifecycle_status"] not in {"APPROVED", "SILENT", "ACTIVE"}:
                raise ValueError(f"قاعدهٔ {member['rule_code']} آمادهٔ تأیید نیست")
        self.rules.activate_ruleset(
            int(ruleset["id"]), activated_by=reviewer, silent=True,
        )
        for key in (
            "last_report", "approval_clinical", "approval_technical",
            "selected_rollout_verification", "seal",
        ):
            self.activation.delete(key)
        self.activation.set_raw_mode("off")
        log_activity(
            "clinical_v2_package_freeze",
            f"Clinically approved and froze ruleset {ruleset_id}: {note}; "
            f"package={package.package_hash}; cases={package.case_bundle_hash}",
            user_id=0, username=reviewer,
        )
        return self.rules.get_ruleset(int(ruleset_id))

    def reset(self, *, actor: str, reason: str) -> dict:
        actor = (actor or "").strip()
        reason = (reason or "").strip()
        if not actor or not reason:
            raise ValueError("نام کاربر و علت ریست الزامی است")
        previous_mode = self.activation.raw_mode()
        retired = self.rules.retire_workflow_rulesets(
            RULESET_CODE, retired_by=actor,
        )
        self.activation.set_raw_mode("off")
        for key in (
            "last_report", "approval_clinical", "approval_technical",
            "selected_rollout_verification", "seal",
        ):
            self.activation.delete(key)
        reset_record = {
            "previous_mode": previous_mode,
            "retired_rulesets": retired,
            "reason": reason,
            "reset_by": actor,
            "reset_at": iran_now().isoformat(sep=" ", timespec="seconds"),
        }
        self.activation.put_json("last_reset", reset_record)
        log_activity(
            "clinical_v2_workflow_reset",
            f"Reset workflow from {previous_mode}; retired {retired} rulesets: {reason}",
            user_id=0, username=actor,
        )
        return reset_record

    def projection(self) -> dict:
        ruleset = self.rules.latest_ruleset(RULESET_CODE)
        same_package = bool(
            ruleset
            and base_ruleset_version(ruleset.get("version")) == PACKAGE_VERSION
        )
        if not ruleset or ruleset["status"] == "RETIRED" or not same_package:
            return {
                "state": "missing",
                "ruleset": None,
                "rules": [],
                # A retired attempt of the same current package means the user
                # intentionally reset the workflow; it is a restart, not an
                # upgrade warning. Only a genuinely older package is upgrade_from.
                "upgrade_from": ruleset if ruleset and not same_package else None,
                "expected_version": PACKAGE_VERSION,
            }
        rules = []
        for member in ruleset["members"]:
            raw = json.loads(member["rule_json"])
            eligibility_mode, eligibility_conditions = _condition_lines(raw["eligibility"])
            trigger_mode, trigger_conditions = _condition_lines(raw["condition"])
            rules.append({
                "code": raw["rule_code"],
                "title": raw["title"],
                "phase": raw["phase"],
                "severity": raw["severity"],
                "population": raw["scope"]["population"],
                "out_of_scope": raw["scope"].get("out_of_scope") or [],
                "required_inputs": [fact["prompt_fa"] for fact in raw["required_facts"]],
                "eligibility_mode": eligibility_mode,
                "eligibility_conditions": eligibility_conditions,
                "trigger_mode": trigger_mode,
                "trigger_conditions": trigger_conditions,
                "recommendation": raw["recommendation"]["text_fa"],
                "automation_limit": _automation_limit(raw),
                "source_title": raw["evidence"]["source_title"],
                "source_locator": raw["evidence"]["source_locator"],
                "source_url": raw["evidence"].get("source_url"),
                "validation_status": raw["evidence"]["local_validation_status"],
                "lifecycle_status": member["lifecycle_status"],
            })
        state = "review" if ruleset["status"] == "DRAFT" else "frozen"
        return {
            "state": state,
            "ruleset": ruleset,
            "rules": rules,
            "upgrade_from": None,
            "expected_version": PACKAGE_VERSION,
        }
