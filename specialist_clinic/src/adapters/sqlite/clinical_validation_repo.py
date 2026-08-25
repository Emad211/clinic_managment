"""Atomic persistence and release qualification for golden-case validation."""
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
    return {
        key: report.get(key)
        for key in (
            "schema_version",
            "engine_version",
            "ruleset_code",
            "package_version",
            "package_hash",
            "case_bundle_hash",
            "status",
            "case_count",
            "categories",
            "missing_categories",
            "checks",
            "metrics",
            "totals",
            "cases",
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
        if report.get("status") not in {"PASS", "BLOCKED"}:
            raise ClinicalValidationError("validation report status is invalid")
        core = report_core(report)
        expected_hash = content_hash(core)
        if not hmac.compare_digest(
            expected_hash,
            str(report.get("report_hash") or ""),
        ):
            raise ClinicalValidationError("validation report hash is invalid")
        if int(report.get("case_count") or 0) <= 0:
            raise ClinicalValidationError("validation report has no cases")
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

    def attest(
        self,
        report_id: int,
        *,
        role: str,
        reviewer: str,
        note: str,
        report_hash: str,
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
        timestamp = _now_text(created_at)
        body = {
            "validation_report_id": int(report_id),
            "role": normalized_role,
            "reviewer": actor,
            "note": explanation,
            "report_hash": report["report_hash"],
            "created_at": timestamp,
        }
        db = self._db()
        try:
            with db:
                cursor = db.execute(
                    """INSERT INTO clinical_validation_attestations
                       (validation_report_id, role, reviewer, note,
                        report_hash, created_at, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(report_id),
                        normalized_role,
                        actor,
                        explanation,
                        report["report_hash"],
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

    def attestations(self, report_id: int) -> dict[str, dict]:
        rows = self._db().execute(
            """SELECT * FROM clinical_validation_attestations
               WHERE validation_report_id=? ORDER BY id""",
            (int(report_id),),
        ).fetchall()
        return {str(row["role"]): dict(row) for row in rows}

    def latest_for_identity(
        self,
        *,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
        package_hash: str | None = None,
    ) -> dict | None:
        sql = """SELECT * FROM clinical_validation_reports
                 WHERE engine_version=? AND ruleset_code=?
                   AND package_version=?"""
        params: list[Any] = [
            engine_version,
            ruleset_code,
            package_version,
        ]
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
        """Return PASS only when the newest exact-identity report is PASS.

        A newer BLOCKED report invalidates every older PASS. Release qualification may
        never search backwards through history for a convenient successful result.
        """
        latest = self.latest_for_identity(
            engine_version=engine_version,
            ruleset_code=ruleset_code,
            package_version=package_version,
            package_hash=package_hash,
        )
        return latest if latest and latest["status"] == "PASS" else None

    def release_evidence(
        self,
        *,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
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
        attestations = self.attestations(int(report["id"]))
        if set(attestations) != {"CLINICAL", "TECHNICAL"}:
            return None
        if any(
            not hmac.compare_digest(item["report_hash"], report["report_hash"])
            for item in attestations.values()
        ):
            return None
        return {
            "validation_report_id": int(report["id"]),
            "validation_report_hash": report["report_hash"],
            "package_version": report["package_version"],
            "package_hash": report["package_hash"],
            "case_bundle_hash": report["case_bundle_hash"],
            "attestations": attestations,
        }

    def verify_release_reference(
        self,
        *,
        report_id: int,
        report_hash: str,
        engine_version: str,
        ruleset_code: str,
        package_version: str,
        package_hash: str,
    ) -> bool:
        evidence = self.release_evidence(
            engine_version=engine_version,
            ruleset_code=ruleset_code,
            package_version=package_version,
            package_hash=package_hash,
        )
        return bool(
            evidence
            and int(evidence["validation_report_id"]) == int(report_id)
            and hmac.compare_digest(
                evidence["validation_report_hash"], str(report_hash)
            )
        )
