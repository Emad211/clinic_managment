"""Persistence and release qualification for golden-case validation."""
from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.clinical_validation_schema import (
    ensure_clinical_validation_storage,
)
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class ClinicalValidationError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def report_core(report: dict[str, Any]) -> dict[str, Any]:
    """Return the complete immutable report body covered by report_hash."""
    return {
        key: report.get(key)
        for key in (
            "schema_version",
            "engine_version",
            "ruleset_code",
            "package_version",
            "package_hash",
            "case_bundle_hash",
            "rule_identity",
            "rule_identity_hash",
            "case_count",
            "categories",
            "missing_categories",
            "checks",
            "metrics",
            "totals",
            "cases",
            "status",
        )
    }


def _now_text(value: datetime | None = None) -> str:
    current = value or iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.isoformat(sep=" ", timespec="seconds")


class ClinicalValidationReportRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self):
        db = self._connection or get_db()
        ensure_clinical_validation_storage(db)
        return db

    @staticmethod
    def _decode(row) -> dict | None:
        if not row:
            return None
        result = dict(row)
        result["report"] = json.loads(result["report_json"])
        return result

    def create(
        self,
        report: dict[str, Any],
        *,
        created_by: str,
        created_at: datetime | None = None,
    ) -> dict:
        actor = " ".join(str(created_by or "").strip().split())
        if not actor:
            raise ClinicalValidationError("created_by is required")
        checks = report.get("checks") or {}
        derived_status = "PASS" if checks and all(checks.values()) else "BLOCKED"
        if report.get("status") != derived_status:
            raise ClinicalValidationError(
                "validation report status does not match its checks"
            )
        core = report_core(report)
        expected_hash = content_hash(core)
        if not hmac.compare_digest(
            expected_hash,
            str(report.get("report_hash") or ""),
        ):
            raise ClinicalValidationError("validation report hash is invalid")
        if int(report.get("case_count") or 0) <= 0:
            raise ClinicalValidationError("validation report has no cases")
        if len(str(report.get("package_hash") or "")) != 64:
            raise ClinicalValidationError("validation package hash is invalid")
        if len(str(report.get("case_bundle_hash") or "")) != 64:
            raise ClinicalValidationError("validation case bundle hash is invalid")

        db = self._db()
        existing = db.execute(
            "SELECT * FROM clinical_validation_reports WHERE report_hash=?",
            (expected_hash,),
        ).fetchone()
        if existing:
            stored = self._decode(existing)
            if canonical_json(stored["report"]) != canonical_json(report):
                raise ClinicalValidationError(
                    "report_hash already exists with different content"
                )
            return stored

        timestamp = _now_text(created_at)
        with db:
            cursor = db.execute(
                """INSERT INTO clinical_validation_reports
                   (engine_version, ruleset_code, package_version, package_hash,
                    case_bundle_hash, status, case_count, report_json,
                    report_hash, created_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report["engine_version"],
                    report["ruleset_code"],
                    report["package_version"],
                    report["package_hash"],
                    report["case_bundle_hash"],
                    report["status"],
                    int(report["case_count"]),
                    canonical_json(report),
                    expected_hash,
                    timestamp,
                    actor,
                ),
            )
            row = db.execute(
                "SELECT * FROM clinical_validation_reports WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._decode(row)

    def get(self, report_id: int) -> dict | None:
        row = self._db().execute(
            "SELECT * FROM clinical_validation_reports WHERE id=?",
            (int(report_id),),
        ).fetchone()
        return self._decode(row)

    def recent(self, limit: int = 10) -> list[dict]:
        safe_limit = max(1, min(int(limit), 100))
        rows = self._db().execute(
            "SELECT * FROM clinical_validation_reports ORDER BY id DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
        return [self._decode(row) for row in rows]

    def latest_current(
        self,
        *,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
        package_hash: str | None = None,
    ) -> dict | None:
        sql = """SELECT * FROM clinical_validation_reports
                 WHERE engine_version=? AND ruleset_code=? AND package_version=?"""
        params: list[Any] = [engine_version, ruleset_code, package_version]
        if package_hash is not None:
            sql += " AND package_hash=?"
            params.append(package_hash)
        sql += " ORDER BY id DESC LIMIT 1"
        return self._decode(self._db().execute(sql, params).fetchone())

    def latest_passing(
        self,
        *,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
        package_hash: str | None = None,
    ) -> dict | None:
        """Only the newest exact report may qualify; an older PASS never wins."""
        report = self.latest_current(
            engine_version=engine_version,
            ruleset_code=ruleset_code,
            package_version=package_version,
            package_hash=package_hash,
        )
        return report if report and report["status"] == "PASS" else None

    def attest(
        self,
        report_id: int,
        *,
        role: str,
        reviewer: str,
        note: str,
        report_hash: str,
        activation_report_hash: str,
        created_at: datetime | None = None,
    ) -> dict:
        normalized_role = str(role or "").strip().upper()
        if normalized_role not in {"CLINICAL", "TECHNICAL"}:
            raise ClinicalValidationError(
                "validation attestation role must be CLINICAL or TECHNICAL"
            )
        actor = " ".join(str(reviewer or "").strip().split())
        explanation = " ".join(str(note or "").strip().split())
        if not actor or len(explanation) < 3 or len(explanation) > 2000:
            raise ClinicalValidationError(
                "validation reviewer and a 3-to-2000 character note are required"
            )
        if len(str(activation_report_hash or "")) != 64:
            raise ClinicalValidationError("activation report hash is invalid")
        report = self.get(report_id)
        if (
            not report
            or report["status"] != "PASS"
            or not hmac.compare_digest(
                report["report_hash"], str(report_hash or "")
            )
        ):
            raise ClinicalValidationError(
                "attestation must reference the exact passing validation report"
            )
        latest = self.latest_passing(
            engine_version=report["engine_version"],
            ruleset_code=report["ruleset_code"],
            package_version=report["package_version"],
            package_hash=report["package_hash"],
        )
        if not latest or int(latest["id"]) != int(report_id):
            raise ClinicalValidationError(
                "attestation must reference the newest exact validation report"
            )

        timestamp = _now_text(created_at)
        body = {
            "validation_report_id": int(report_id),
            "activation_report_hash": str(activation_report_hash),
            "role": normalized_role,
            "reviewer": actor,
            "note": explanation,
            "report_hash": report["report_hash"],
            "package_hash": report["package_hash"],
            "case_bundle_hash": report["case_bundle_hash"],
            "created_at": timestamp,
        }
        db = self._db()
        try:
            with db:
                cursor = db.execute(
                    """INSERT INTO clinical_validation_attestations
                       (validation_report_id, activation_report_hash, role,
                        reviewer, note, report_hash, package_hash,
                        case_bundle_hash, created_at, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(report_id),
                        str(activation_report_hash),
                        normalized_role,
                        actor,
                        explanation,
                        report["report_hash"],
                        report["package_hash"],
                        report["case_bundle_hash"],
                        timestamp,
                        content_hash(body),
                    ),
                )
                row = db.execute(
                    "SELECT * FROM clinical_validation_attestations WHERE id=?",
                    (cursor.lastrowid,),
                ).fetchone()
            return dict(row)
        except sqlite3.IntegrityError as exc:
            raise ClinicalValidationError(str(exc)) from exc

    def attestations(
        self,
        report_id: int,
        *,
        activation_report_hash: str,
    ) -> dict[str, dict]:
        rows = self._db().execute(
            """SELECT event.* FROM clinical_validation_attestations event
               WHERE event.validation_report_id=?
                 AND event.activation_report_hash=?
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_validation_attestations newer
                     WHERE newer.validation_report_id=event.validation_report_id
                       AND newer.activation_report_hash=event.activation_report_hash
                       AND newer.role=event.role AND newer.id>event.id
                 )
               ORDER BY event.id""",
            (int(report_id), str(activation_report_hash)),
        ).fetchall()
        return {str(row["role"]): dict(row) for row in rows}

    def release_evidence(
        self,
        *,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
        activation_report_hash: str,
        package_hash: str | None = None,
    ) -> dict | None:
        report = self.latest_passing(
            engine_version=engine_version,
            ruleset_code=ruleset_code,
            package_version=package_version,
            package_hash=package_hash,
        )
        if not report:
            return None
        attestations = self.attestations(
            int(report["id"]),
            activation_report_hash=activation_report_hash,
        )
        if set(attestations) != {"CLINICAL", "TECHNICAL"}:
            return None
        if attestations["CLINICAL"]["reviewer"] == attestations["TECHNICAL"]["reviewer"]:
            return None
        if any(
            not hmac.compare_digest(item["report_hash"], report["report_hash"])
            or not hmac.compare_digest(item["package_hash"], report["package_hash"])
            or not hmac.compare_digest(
                item["case_bundle_hash"], report["case_bundle_hash"]
            )
            for item in attestations.values()
        ):
            return None
        body = {
            "validation_report_id": int(report["id"]),
            "validation_report_hash": report["report_hash"],
            "activation_report_hash": str(activation_report_hash),
            "package_hash": report["package_hash"],
            "case_bundle_hash": report["case_bundle_hash"],
            "clinical_attestation_hash": attestations["CLINICAL"]["content_hash"],
            "technical_attestation_hash": attestations["TECHNICAL"]["content_hash"],
        }
        return {
            **body,
            "release_evidence_hash": content_hash(body),
            "attestations": attestations,
        }

    def verify_release_reference(
        self,
        *,
        report_id: int,
        report_hash: str,
        activation_report_hash: str,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
        package_hash: str,
        case_bundle_hash: str,
        clinical_attestation_hash: str,
        technical_attestation_hash: str,
        release_evidence_hash: str,
    ) -> bool:
        evidence = self.release_evidence(
            engine_version=engine_version,
            ruleset_code=ruleset_code,
            package_version=package_version,
            package_hash=package_hash,
            activation_report_hash=activation_report_hash,
        )
        return bool(
            evidence
            and int(evidence["validation_report_id"]) == int(report_id)
            and hmac.compare_digest(
                evidence["validation_report_hash"], str(report_hash)
            )
            and hmac.compare_digest(
                evidence["case_bundle_hash"], str(case_bundle_hash)
            )
            and hmac.compare_digest(
                evidence["clinical_attestation_hash"],
                str(clinical_attestation_hash),
            )
            and hmac.compare_digest(
                evidence["technical_attestation_hash"],
                str(technical_attestation_hash),
            )
            and hmac.compare_digest(
                evidence["release_evidence_hash"],
                str(release_evidence_hash),
            )
        )
