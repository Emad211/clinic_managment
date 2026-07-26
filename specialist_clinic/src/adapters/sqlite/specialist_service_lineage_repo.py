"""Repository for strict append-only specialist service-line snapshots."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_service_lineage_schema import (
    ensure_specialist_service_lineage_storage,
)
from src.common.utils import iran_now


class SpecialistServiceLineageConflict(RuntimeError):
    pass


class SpecialistServiceLineageValidationError(ValueError):
    pass


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime | str | None = None) -> str:
    current = value or iran_now()
    if isinstance(current, str):
        parsed = datetime.fromisoformat(current.replace("Z", "+00:00"))
    else:
        parsed = current
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


class SpecialistServiceLineageRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        installed = db.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='specialist_service_snapshot_manifests'"""
        ).fetchone()
        if not installed:
            if db.in_transaction:
                raise RuntimeError(
                    "service lineage storage is missing inside caller transaction"
                )
            ensure_specialist_service_lineage_storage(db)
        return db

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def current_manifest(self, accounting_invoice_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM specialist_service_snapshot_manifests
                   WHERE accounting_invoice_id=?
                   ORDER BY observed_at DESC,created_at DESC,rowid DESC LIMIT 1""",
                (int(accounting_invoice_id),),
            ).fetchone()
        )

    def manifest_for_identity(
        self,
        *,
        accounting_invoice_id: int,
        financial_observation_id: int,
        source_fingerprint: str,
    ) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM specialist_service_snapshot_manifests
                   WHERE accounting_invoice_id=? AND financial_observation_id=?
                     AND source_fingerprint=?""",
                (
                    int(accounting_invoice_id),
                    int(financial_observation_id),
                    str(source_fingerprint),
                ),
            ).fetchone()
        )

    def lines_for_snapshot(self, snapshot_id: str) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM specialist_service_line_observations
                   WHERE snapshot_id=? ORDER BY line_sequence,id""",
                (str(snapshot_id),),
            ).fetchall()
        ]

    def attach_snapshot(
        self,
        *,
        observation: dict,
        service_snapshot: dict | None,
        observed_at: datetime | str | None = None,
        created_by: str = "system:specialist-service-reconciliation",
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        service = dict(service_snapshot or {})
        status = str(service.get("status") or "LEGACY_UNAVAILABLE").upper()
        if status not in {"COMPLETE", "LEGACY_UNAVAILABLE"}:
            raise SpecialistServiceLineageValidationError(
                "invalid service snapshot status"
            )
        invoice_id = int(observation["accounting_invoice_id"])
        if service.get("accounting_invoice_id") is not None and int(
            service["accounting_invoice_id"]
        ) != invoice_id:
            raise SpecialistServiceLineageConflict("SERVICE_INVOICE_SCOPE_MISMATCH")
        if service.get("accounting_patient_id") is not None and int(
            service["accounting_patient_id"]
        ) != int(observation["accounting_patient_id"]):
            raise SpecialistServiceLineageConflict("SERVICE_PATIENT_SCOPE_MISMATCH")

        lines = list(service.get("lines") or []) if status == "COMPLETE" else []
        if status == "COMPLETE":
            expected_count = int(service.get("expected_line_count", -1))
            expected_total = int(service.get("expected_total_amount", -1))
            if expected_count != int(observation["billable_item_count"]):
                raise SpecialistServiceLineageConflict(
                    "SERVICE_FINANCIAL_ITEM_COUNT_MISMATCH"
                )
            if expected_total != int(observation["billed_amount"]):
                raise SpecialistServiceLineageConflict(
                    "SERVICE_FINANCIAL_TOTAL_MISMATCH"
                )
            if len(lines) != expected_count:
                raise SpecialistServiceLineageConflict(
                    "SERVICE_SNAPSHOT_LINE_COUNT_MISMATCH"
                )
            evidence = str(service.get("evidence_code") or "")
            if evidence != "ACCOUNTING_SERVICE_LINES_V1":
                raise SpecialistServiceLineageValidationError(
                    "complete service snapshot requires strict accounting evidence"
                )
        else:
            expected_count = 0
            expected_total = 0
            evidence = "LEGACY_UNAVAILABLE"

        source_fingerprint = str(
            service.get("source_fingerprint")
            or hashlib.sha256(
                (
                    f"legacy-service:{invoice_id}:{observation['id']}:"
                    f"{observation['source_fingerprint']}"
                ).encode("utf-8")
            ).hexdigest()
        )
        if len(source_fingerprint) != 64:
            raise SpecialistServiceLineageValidationError(
                "service source fingerprint must be sha256"
            )
        existing = self.manifest_for_identity(
            accounting_invoice_id=invoice_id,
            financial_observation_id=int(observation["id"]),
            source_fingerprint=source_fingerprint,
        )
        if existing:
            return existing, False

        when = _time(observed_at or observation["observed_at"])
        created_at = _time()
        snapshot_id = "service_snapshot_" + uuid.uuid4().hex
        current = self.current_manifest(invoice_id)
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            for line in lines:
                item_type = str(line.get("item_type") or "").upper()
                if item_type not in {"VISIT", "INJECTION", "PROCEDURE"}:
                    raise SpecialistServiceLineageValidationError(
                        "invalid service line type"
                    )
                description = str(line.get("description") or "").strip()
                if not description:
                    raise SpecialistServiceLineageValidationError(
                        "service line description is required"
                    )
                payload = {
                    "snapshot_id": snapshot_id,
                    "accounting_invoice_id": invoice_id,
                    "journey_id": str(observation["journey_id"]),
                    "encounter_id": str(observation["encounter_id"]),
                    "patient_link_id": int(observation["patient_link_id"]),
                    "item_type": item_type,
                    "accounting_item_id": int(line["accounting_item_id"]),
                    "line_sequence": int(line["line_sequence"]),
                    "description": description,
                    "performed_at": (
                        _time(line["performed_at"])
                        if line.get("performed_at")
                        else None
                    ),
                    "work_date": str(line.get("work_date") or "").strip() or None,
                    "quantity": line.get("quantity"),
                    "unit_amount": line.get("unit_amount"),
                    "total_amount": int(line.get("total_amount") or 0),
                    "performer_type": (
                        str(line.get("performer_type") or "").strip() or None
                    ),
                    "performer_accounting_id": line.get("performer_id"),
                    "performer_name": (
                        str(line.get("performer_name") or "").strip() or None
                    ),
                    "source_status": (
                        str(line.get("source_status") or "").strip() or None
                    ),
                    "source_fingerprint": str(line["source_fingerprint"]),
                }
                db.execute(
                    """INSERT INTO specialist_service_line_observations
                       (snapshot_id,accounting_invoice_id,journey_id,encounter_id,
                        patient_link_id,item_type,accounting_item_id,line_sequence,
                        description,performed_at,work_date,quantity,unit_amount,
                        total_amount,performer_type,performer_accounting_id,
                        performer_name,source_status,source_fingerprint,content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*payload.values(), _hash(payload)),
                )

            manifest = {
                "snapshot_id": snapshot_id,
                "financial_observation_id": int(observation["id"]),
                "accounting_invoice_id": invoice_id,
                "journey_id": str(observation["journey_id"]),
                "encounter_id": str(observation["encounter_id"]),
                "patient_link_id": int(observation["patient_link_id"]),
                "status": status,
                "expected_line_count": expected_count,
                "expected_total_amount": expected_total,
                "evidence_code": evidence,
                "source_fingerprint": source_fingerprint,
                "observed_at": when,
                "created_at": created_at,
                "created_by": str(created_by),
                "supersedes_snapshot_id": (
                    str(current["snapshot_id"]) if current else None
                ),
            }
            db.execute(
                """INSERT INTO specialist_service_snapshot_manifests
                   (snapshot_id,financial_observation_id,accounting_invoice_id,
                    journey_id,encounter_id,patient_link_id,status,
                    expected_line_count,expected_total_amount,evidence_code,
                    source_fingerprint,observed_at,created_at,created_by,
                    supersedes_snapshot_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*manifest.values(), _hash(manifest)),
            )
            if commit:
                db.commit()
            return self.current_manifest(invoice_id), True
        except Exception:
            if commit:
                db.rollback()
            raise

    def current_lines_for_patient(
        self,
        patient_link_id: int,
        *,
        limit: int = 200,
    ) -> list[dict]:
        rows = self._db().execute(
            """SELECT line.*,manifest.observed_at AS snapshot_observed_at,
                      manifest.financial_observation_id
               FROM specialist_service_snapshot_manifests manifest
               JOIN specialist_service_line_observations line
                 ON line.snapshot_id=manifest.snapshot_id
               WHERE manifest.patient_link_id=?
                 AND manifest.status='COMPLETE'
                 AND manifest.snapshot_id=(
                     SELECT head.snapshot_id
                     FROM specialist_service_snapshot_manifests head
                     WHERE head.accounting_invoice_id=manifest.accounting_invoice_id
                     ORDER BY head.observed_at DESC,head.created_at DESC,head.rowid DESC
                     LIMIT 1
                 )
                 AND manifest.financial_observation_id=(
                     SELECT latest.id FROM specialist_financial_observations latest
                     WHERE latest.accounting_invoice_id=manifest.accounting_invoice_id
                     ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
                 )
               ORDER BY COALESCE(line.performed_at,line.work_date) DESC,
                        line.accounting_invoice_id DESC,line.line_sequence
               LIMIT ?""",
            (int(patient_link_id), int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]

    def coverage_scope(self) -> dict:
        row = self._db().execute(
            """WITH current_observation AS (
                   SELECT observation.*
                   FROM specialist_financial_observations observation
                   WHERE observation.id=(
                       SELECT latest.id FROM specialist_financial_observations latest
                       WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
                       ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
                   )
               ), current_manifest AS (
                   SELECT manifest.*
                   FROM specialist_service_snapshot_manifests manifest
                   WHERE manifest.snapshot_id=(
                       SELECT head.snapshot_id
                       FROM specialist_service_snapshot_manifests head
                       WHERE head.accounting_invoice_id=manifest.accounting_invoice_id
                       ORDER BY head.observed_at DESC,head.created_at DESC,head.rowid DESC
                       LIMIT 1
                   )
               )
               SELECT COUNT(observation.id) AS observed_invoices,
                      COALESCE(SUM(CASE WHEN manifest.status='COMPLETE'
                        AND manifest.financial_observation_id=observation.id
                        THEN 1 ELSE 0 END),0) AS complete_invoices,
                      COALESCE(SUM(CASE WHEN manifest.status='LEGACY_UNAVAILABLE'
                        THEN 1 ELSE 0 END),0) AS legacy_invoices,
                      COALESCE(SUM(CASE WHEN manifest.snapshot_id IS NULL
                        OR manifest.financial_observation_id<>observation.id
                        THEN 1 ELSE 0 END),0) AS missing_or_stale
               FROM current_observation observation
               LEFT JOIN current_manifest manifest
                 ON manifest.accounting_invoice_id=observation.accounting_invoice_id"""
        ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}


__all__ = [
    "SpecialistServiceLineageConflict",
    "SpecialistServiceLineageRepository",
    "SpecialistServiceLineageValidationError",
]
