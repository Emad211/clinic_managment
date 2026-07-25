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
    """Reconstruct the immutable portion covered by ``report_hash``."""
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
    }


def _current_report_ruleset(report: Any) -> bool:
    ruleset = report.get("ruleset") if isinstance(report, dict) else None
    return bool(
        isinstance(ruleset, dict)
        and ruleset.get("ruleset_code") == RULESET_CODE
        and is_current_package_version(ruleset.get("version"))
    )


def _current_report_validation(report: Any) -> bool:
    validation = report.get("validation") if isinstance(report, dict) else None
    return bool(
        isinstance(validation, dict)
        and validation.get("status") == "PASS"
        and validation.get("engine_version") == CURRENT_ENGINE_VERSION
        and validation.get("ruleset_code") == RULESET_CODE
        and validation.get("package_version") == CURRENT_BUNDLED_PACKAGE_VERSION
        and validation.get("validation_report_id") is not None
        and validation.get("validation_report_hash")
        and validation.get("package_hash")
        and validation.get("case_bundle_hash")
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

    def put_json(self, name: str, value: Any) -> None:
        # Activation becomes visible only after the immutable history it relies on
        # has been checkpointed. The repository augments and re-hashes the seal so
        # callers cannot accidentally omit the audit binding.
        if name == "seal":
            if not isinstance(value, dict):
                raise ValueError("activation seal must be an object")
            from src.services.clinical_audit_integrity import (
                ClinicalAuditIntegrityService,
            )

            actor = str(value.get("activated_by") or "").strip()
            checkpoint = ClinicalAuditIntegrityService().seal(
                created_by=actor or "activation-seal",
            )
            body = {
                key: item
                for key, item in value.items()
                if key != "seal_hash"
            }
            body.update(
                {
                    "audit_checkpoint_id": int(checkpoint["id"]),
                    "audit_checkpoint_hash": checkpoint["checkpoint_hash"],
                }
            )
            value = {**body, "seal_hash": content_hash(body)}
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
                engine_version=CURRENT_ENGINE_VERSION,
                ruleset_code=RULESET_CODE,
                package_version=CURRENT_BUNDLED_PACKAGE_VERSION,
                package_hash=str(seal.get("validation_package_hash") or ""),
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
        ):
            return False
        for role in ("clinical", "technical"):
            approval = self.get_json(f"approval_{role}")
            if (
                not isinstance(approval, dict)
                or approval.get("report_hash")
                != report["report_hash"]
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
        )
