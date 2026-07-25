"""Durable, build-bound governance state for Clinical Engine v2 rollout."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from src.adapters.sqlite.core import get_db
from src.domain.clinical_engine.release import (
    CURRENT_BUNDLED_PACKAGE_VERSION,
    CURRENT_ENGINE_VERSION,
    RULESET_CODE,
    is_current_package_version,
)


_PREFIX = "clinical_engine_v2_activation_"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def report_core(report: dict) -> dict:
    """Reconstruct every immutable field covered by the activation report hash."""
    return {
        "schema_version": report.get("schema_version"),
        "engine_version": report.get("engine_version"),
        "as_of_at": report.get("as_of_at"),
        "cohort": report.get("cohort"),
        "ruleset": report.get("ruleset"),
        "validation": report.get("validation"),
        "patients": [
            {
                key: value
                for key, value in row.items()
                if key != "v2_run_id"
            }
            for row in (report.get("patients") or [])
        ],
        "failures": report.get("failures"),
        "checks": report.get("checks"),
        "status": report.get("status"),
    }


def _current_report_ruleset(report: Any) -> bool:
    ruleset = report.get("ruleset") if isinstance(report, dict) else None
    return bool(
        isinstance(ruleset, dict)
        and ruleset.get("ruleset_code") == RULESET_CODE
        and is_current_package_version(ruleset.get("version"))
        and ruleset.get("content_hash")
    )


def _current_report_validation(report: Any) -> bool:
    validation = report.get("validation") if isinstance(report, dict) else None
    return bool(
        isinstance(validation, dict)
        and validation.get("status") == "PASS"
        and validation.get("engine_version") == CURRENT_ENGINE_VERSION
        and validation.get("ruleset_code") == RULESET_CODE
        and validation.get("package_version")
        == CURRENT_BUNDLED_PACKAGE_VERSION
        and validation.get("validation_report_id") is not None
        and validation.get("validation_report_hash")
        and validation.get("package_hash")
        and validation.get("case_bundle_hash")
        and validation.get("rule_identity_hash")
        and validation.get("ruleset_identity_match") is True
    )


def valid_report(report: Any) -> bool:
    return bool(
        isinstance(report, dict)
        and report.get("status") == "PASS"
        and report.get("engine_version") == CURRENT_ENGINE_VERSION
        and report.get("checks")
        and all(report["checks"].values())
        and _current_report_ruleset(report)
        and _current_report_validation(report)
        and report.get("report_hash")
        == content_hash(report_core(report))
    )


class ClinicalEngineActivationRepository:
    """Store activation evidence without mutating historical clinical audit rows."""

    def _key(self, name: str) -> str:
        return _PREFIX + name

    def get_json(self, name: str, default=None):
        row = get_db().execute(
            "SELECT value FROM settings WHERE key=?",
            (self._key(name),),
        ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return default

    def _ruleset_identity(self, ruleset_id: int) -> list[dict]:
        rows = get_db().execute(
            """SELECT rule.rule_code, rule.version, rule.content_hash
               FROM clinical_ruleset_members member
               JOIN clinical_rule_versions rule
                 ON rule.id=member.rule_version_id
               WHERE member.ruleset_id=?
               ORDER BY rule.rule_code""",
            (int(ruleset_id),),
        ).fetchall()
        return [
            {
                "rule_code": str(row["rule_code"]),
                "version": str(row["version"]),
                "content_hash": str(row["content_hash"]),
            }
            for row in rows
        ]

    def _augment_activation_report(self, report: dict) -> dict:
        from src.services.clinical_engine.validation_service import (
            ClinicalValidationService,
        )

        stored = ClinicalValidationService().run_current(
            created_by="activation-report"
        )
        validation_report = stored["report"]
        ruleset = report.get("ruleset") or {}
        ruleset_identity = self._ruleset_identity(
            int(ruleset.get("id") or 0)
        )
        identity_match = bool(
            ruleset_identity
            and ruleset_identity
            == validation_report.get("rule_identity")
        )
        checks = dict(report.get("checks") or {})
        checks.update(
            {
                "golden_case_validation_passed": (
                    validation_report.get("status") == "PASS"
                    and all(
                        (validation_report.get("checks") or {}).values()
                    )
                ),
                "validation_ruleset_identity_matches": identity_match,
            }
        )
        validation = {
            "status": validation_report.get("status"),
            "engine_version": validation_report.get("engine_version"),
            "ruleset_code": validation_report.get("ruleset_code"),
            "package_version": validation_report.get("package_version"),
            "validation_report_id": int(stored["id"]),
            "validation_report_hash": stored["report_hash"],
            "package_hash": stored["package_hash"],
            "case_bundle_hash": stored["case_bundle_hash"],
            "rule_identity_hash": validation_report.get("rule_identity_hash"),
            "ruleset_identity_match": identity_match,
            "case_count": validation_report.get("case_count"),
            "checks": validation_report.get("checks"),
            "totals": validation_report.get("totals"),
            "metrics": validation_report.get("metrics"),
            "cases": validation_report.get("cases"),
        }
        report["validation"] = validation
        report["checks"] = checks
        report["status"] = "PASS" if checks and all(checks.values()) else "BLOCKED"
        report["report_hash"] = content_hash(report_core(report))
        return report

    def _augment_approval(self, name: str, approval: dict) -> dict:
        report = self.get_json("last_report")
        if not valid_report(report):
            raise ValueError(
                "validation attestation requires the current passing activation report"
            )
        validation = report["validation"]
        role = name.removeprefix("approval_")
        from src.services.clinical_engine.validation_service import (
            ClinicalValidationService,
        )

        event = ClinicalValidationService().attest_current(
            role=role,
            reviewer=str(approval.get("reviewer") or ""),
            note=str(approval.get("note") or ""),
            report_hash=validation["validation_report_hash"],
            activation_report_hash=report["report_hash"],
        )
        approval.update(
            {
                "validation_report_id": int(event["validation_report_id"]),
                "validation_report_hash": event["report_hash"],
                "validation_activation_report_hash": event[
                    "activation_report_hash"
                ],
                "validation_attestation_id": int(event["id"]),
                "validation_attestation_hash": event["content_hash"],
            }
        )
        return approval

    def _augment_seal(self, seal: dict) -> dict:
        report = self.get_json("last_report")
        if not valid_report(report):
            raise ValueError(
                "activation seal requires the current passing validated report"
            )
        validation = report["validation"]
        from src.services.clinical_engine.validation_service import (
            ClinicalValidationService,
        )

        evidence = ClinicalValidationService().current_release_evidence(
            activation_report_hash=report["report_hash"],
            package_hash=validation["package_hash"],
        )
        if not evidence:
            raise ValueError(
                "independent clinical and technical validation attestations are required"
            )
        if (
            int(evidence["validation_report_id"])
            != int(validation["validation_report_id"])
            or evidence["validation_report_hash"]
            != validation["validation_report_hash"]
            or evidence["case_bundle_hash"]
            != validation["case_bundle_hash"]
        ):
            raise ValueError("validation release evidence is stale")

        ruleset = self.ruleset_state(int(seal.get("ruleset_id") or 0))
        if not ruleset:
            raise ValueError("activation ruleset was not found")
        from src.services.clinical_audit_integrity import (
            ClinicalAuditIntegrityService,
        )

        actor = str(seal.get("activated_by") or "").strip()
        checkpoint = ClinicalAuditIntegrityService().seal(
            created_by=actor or "activation-seal",
        )
        body = {
            key: item
            for key, item in seal.items()
            if key != "seal_hash"
        }
        body.update(
            {
                "ruleset_content_hash": ruleset["content_hash"],
                "validation_report_id": evidence["validation_report_id"],
                "validation_report_hash": evidence[
                    "validation_report_hash"
                ],
                "validation_activation_report_hash": evidence[
                    "activation_report_hash"
                ],
                "validation_package_hash": evidence["package_hash"],
                "validation_case_bundle_hash": evidence[
                    "case_bundle_hash"
                ],
                "validation_clinical_attestation_hash": evidence[
                    "clinical_attestation_hash"
                ],
                "validation_technical_attestation_hash": evidence[
                    "technical_attestation_hash"
                ],
                "validation_release_evidence_hash": evidence[
                    "release_evidence_hash"
                ],
                "audit_checkpoint_id": int(checkpoint["id"]),
                "audit_checkpoint_hash": checkpoint["checkpoint_hash"],
            }
        )
        seal.clear()
        seal.update({**body, "seal_hash": content_hash(body)})
        return seal

    def put_json(self, name: str, value: Any) -> None:
        if name == "last_report":
            if not isinstance(value, dict):
                raise ValueError("activation report must be an object")
            self._augment_activation_report(value)
        elif name in {"approval_clinical", "approval_technical"}:
            if not isinstance(value, dict):
                raise ValueError("activation approval must be an object")
            self._augment_approval(name, value)
        elif name == "seal":
            if not isinstance(value, dict):
                raise ValueError("activation seal must be an object")
            self._augment_seal(value)

        payload = canonical_json(value)
        with get_db() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self._key(name), payload),
            )

    def delete(self, name: str) -> None:
        with get_db() as db:
            db.execute(
                "DELETE FROM settings WHERE key=?",
                (self._key(name),),
            )

    def raw_mode(self) -> str:
        row = get_db().execute(
            "SELECT value FROM settings "
            "WHERE key='clinical_engine_v2_mode'"
        ).fetchone()
        return str(
            row["value"] if row else "off"
        ).strip().lower()

    def set_raw_mode(self, mode: str) -> None:
        with get_db() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES "
                "('clinical_engine_v2_mode', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (mode,),
            )

    def demo_patients(self) -> list[dict]:
        ids = [f"TEST{i:04d}" for i in range(1, 11)]
        marks = ",".join("?" for _ in ids)
        rows = get_db().execute(
            f"SELECT id, national_id, full_name FROM patient_links "
            f"WHERE upper(trim(national_id)) IN ({marks}) "
            f"ORDER BY national_id",
            ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def ruleset_state(self, ruleset_id: int) -> dict | None:
        row = get_db().execute(
            "SELECT id, ruleset_code, version, content_hash, status "
            "FROM clinical_rulesets WHERE id=?",
            (ruleset_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _audit_checkpoint_valid(seal: dict) -> bool:
        checkpoint_id = seal.get("audit_checkpoint_id")
        checkpoint_hash = seal.get("audit_checkpoint_hash")
        if checkpoint_id is None or not checkpoint_hash:
            return False
        try:
            from src.services.clinical_audit_integrity import (
                ClinicalAuditIntegrityService,
            )

            service = ClinicalAuditIntegrityService()
            verification = service.verify_checkpoint(
                int(checkpoint_id),
                expected_hash=str(checkpoint_hash),
            )
            latest = service.verify_latest(require_checkpoint=True)
            return verification.ok and latest.ok
        except Exception:
            return False

    @staticmethod
    def _validation_release_valid(seal: dict) -> bool:
        try:
            from src.adapters.sqlite.clinical_validation_repo import (
                ClinicalValidationReportRepository,
            )

            return ClinicalValidationReportRepository().verify_release_reference(
                report_id=int(seal.get("validation_report_id") or 0),
                report_hash=str(seal.get("validation_report_hash") or ""),
                activation_report_hash=str(
                    seal.get("validation_activation_report_hash") or ""
                ),
                engine_version=CURRENT_ENGINE_VERSION,
                ruleset_code=RULESET_CODE,
                package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
                package_hash=str(seal.get("validation_package_hash") or ""),
                case_bundle_hash=str(
                    seal.get("validation_case_bundle_hash") or ""
                ),
                clinical_attestation_hash=str(
                    seal.get("validation_clinical_attestation_hash") or ""
                ),
                technical_attestation_hash=str(
                    seal.get("validation_technical_attestation_hash") or ""
                ),
                release_evidence_hash=str(
                    seal.get("validation_release_evidence_hash") or ""
                ),
            )
        except Exception:
            return False

    def valid_seal(self, mode: str) -> bool:
        seal = self.get_json("seal")
        if (
            not isinstance(seal, dict)
            or seal.get("mode") != mode
            or seal.get("engine_version") != CURRENT_ENGINE_VERSION
        ):
            return False
        supplied = seal.get("seal_hash")
        body = {
            key: value
            for key, value in seal.items()
            if key != "seal_hash"
        }
        if not supplied or supplied != content_hash(body):
            return False
        if not self._audit_checkpoint_valid(seal):
            return False
        if not self._validation_release_valid(seal):
            return False

        report = self.get_json("last_report")
        if (
            not valid_report(report)
            or report["report_hash"] != seal.get("report_hash")
            or report["report_hash"]
            != seal.get("validation_activation_report_hash")
        ):
            return False
        validation = report["validation"]
        if (
            int(validation["validation_report_id"])
            != int(seal.get("validation_report_id") or 0)
            or validation["validation_report_hash"]
            != seal.get("validation_report_hash")
            or validation["package_hash"]
            != seal.get("validation_package_hash")
            or validation["case_bundle_hash"]
            != seal.get("validation_case_bundle_hash")
        ):
            return False
        for role in ("clinical", "technical"):
            approval = self.get_json(f"approval_{role}")
            if (
                not isinstance(approval, dict)
                or approval.get("report_hash")
                != report["report_hash"]
                or approval.get("validation_attestation_hash")
                != seal.get(f"validation_{role}_attestation_hash")
            ):
                return False
        ruleset = self.ruleset_state(
            int(seal.get("ruleset_id") or 0)
        )
        allowed = (
            {"SILENT", "ACTIVE"}
            if mode == "on_selected"
            else {"ACTIVE"}
        )
        return bool(
            ruleset
            and ruleset["ruleset_code"] == RULESET_CODE
            and is_current_package_version(ruleset["version"])
            and ruleset["status"] in allowed
            and ruleset["content_hash"]
            == seal.get("ruleset_content_hash")
        )
