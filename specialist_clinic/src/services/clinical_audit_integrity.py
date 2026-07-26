"""Hash-chain checkpoints over immutable Clinical Engine audit tables.

Only hashes, counts and row-id limits are persisted. No patient value, identifier or
clinical text is returned by this service or exposed through health endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
import sqlite3
from typing import Any, Mapping

from src.adapters.sqlite.clinical_audit_integrity_schema import (
    ensure_clinical_audit_integrity_storage,
)
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)
from src.adapters.sqlite.clinical_alert_schema import (
    ensure_clinical_alert_storage,
)
from src.common.utils import iran_now


SCOPE_VERSION = "1.5-clinical-alert-lifecycle"
CRITICAL_TABLES = (
    "clinical_rule_versions",
    "clinical_rulesets",
    "clinical_ruleset_members",
    "clinical_engine_runs",
    "clinical_rule_evaluations",
    "clinical_recommendation_events",
    "clinical_decision_events",
    "clinical_flag_events",
    "clinical_encounter_events",
    "clinical_data_conflict_events",
    "clinical_task_events",
    "clinical_outcome_events",
    "clinical_validation_reports",
    "clinical_validation_attestations",
    "specialist_program_enrollments",
    "care_journeys",
    "care_journey_events",
    "care_encounters",
    "care_encounter_events",
    "accounting_invoice_attribution_events",
    "followup_contact_events",
    "followup_booking_requests",
    "clinical_task_contracts",
    "clinical_outcome_canonical_links",
    "clinical_alerts",
    "clinical_alert_events",
    "security_permission_events",
)


class ClinicalAuditIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuditVerification:
    ok: bool
    checkpoint_id: int | None
    checkpoint_hash: str | None
    reason: str | None = None


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_value(value):
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    return value


def _now_text(value: datetime | None = None) -> str:
    current = value or iran_now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.isoformat(sep=" ", timespec="seconds")


class ClinicalAuditIntegrityService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self):
        db = self._connection or get_db()
        ensure_specialist_revenue_boundary_storage(db)
        ensure_clinical_alert_storage(db)
        ensure_clinical_audit_integrity_storage(db)
        return db

    @staticmethod
    def _available_tables(db) -> set[str]:
        return {
            str(row["name"])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    def _limits(self, db) -> tuple[dict[str, int], dict[str, int]]:
        available = self._available_tables(db)
        missing = sorted(set(CRITICAL_TABLES) - available)
        if missing:
            raise ClinicalAuditIntegrityError(
                "critical audit tables are missing: " + ", ".join(missing)
            )
        counts: dict[str, int] = {}
        max_rowids: dict[str, int] = {}
        for table in CRITICAL_TABLES:
            row = db.execute(
                f"SELECT COUNT(*) AS count, COALESCE(MAX(rowid), 0) AS max_rowid "
                f"FROM {table}"
            ).fetchone()
            counts[table] = int(row["count"] or 0)
            max_rowids[table] = int(row["max_rowid"] or 0)
        return counts, max_rowids

    def _root(
        self,
        db,
        *,
        max_rowids: Mapping[str, int],
    ) -> tuple[str, dict[str, int]]:
        digest = hashlib.sha256()
        counts: dict[str, int] = {}
        for table in CRITICAL_TABLES:
            if table not in max_rowids:
                raise ClinicalAuditIntegrityError(
                    f"checkpoint does not cover critical table {table}"
                )
            limit = int(max_rowids[table])
            digest.update(f"TABLE:{table}:{limit}\n".encode("utf-8"))
            rows = db.execute(
                f"SELECT rowid AS __audit_rowid__, * FROM {table} "
                "WHERE rowid<=? ORDER BY rowid",
                (limit,),
            ).fetchall()
            counts[table] = len(rows)
            for row in rows:
                payload = {
                    key: _safe_value(row[key])
                    for key in row.keys()
                }
                digest.update(_canonical(payload).encode("utf-8"))
                digest.update(b"\n")
        return digest.hexdigest(), counts

    @staticmethod
    def _checkpoint_body(
        *,
        root_hash: str,
        counts: Mapping[str, int],
        max_rowids: Mapping[str, int],
        previous_checkpoint_hash: str | None,
        created_at: str,
        created_by: str,
    ) -> dict[str, Any]:
        return {
            "scope_version": SCOPE_VERSION,
            "root_hash": root_hash,
            "table_counts": dict(counts),
            "table_max_rowid": dict(max_rowids),
            "previous_checkpoint_hash": previous_checkpoint_hash,
            "created_at": created_at,
            "created_by": created_by,
        }

    def seal(
        self,
        *,
        created_by: str,
        created_at: datetime | None = None,
    ) -> dict:
        actor = " ".join(str(created_by or "").strip().split())
        if not actor:
            raise ValueError("created_by is required")
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            counts, max_rowids = self._limits(db)
            root_hash, observed_counts = self._root(
                db,
                max_rowids=max_rowids,
            )
            if observed_counts != counts:
                raise ClinicalAuditIntegrityError(
                    "audit snapshot changed during checkpoint creation"
                )
            previous = db.execute(
                """SELECT checkpoint_hash FROM clinical_audit_checkpoints
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            previous_hash = (
                str(previous["checkpoint_hash"]) if previous else None
            )
            timestamp = _now_text(created_at)
            body = self._checkpoint_body(
                root_hash=root_hash,
                counts=counts,
                max_rowids=max_rowids,
                previous_checkpoint_hash=previous_hash,
                created_at=timestamp,
                created_by=actor,
            )
            checkpoint_hash = _hash(body)
            cursor = db.execute(
                """INSERT INTO clinical_audit_checkpoints
                   (scope_version, root_hash, table_counts_json,
                    table_max_rowid_json, previous_checkpoint_hash,
                    checkpoint_hash, created_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    SCOPE_VERSION,
                    root_hash,
                    _canonical(counts),
                    _canonical(max_rowids),
                    previous_hash,
                    checkpoint_hash,
                    timestamp,
                    actor,
                ),
            )
            checkpoint_id = int(cursor.lastrowid)
            db.commit()
            return {
                "id": checkpoint_id,
                **body,
                "checkpoint_hash": checkpoint_hash,
            }
        except Exception:
            db.rollback()
            raise

    def latest(self) -> dict | None:
        row = self._db().execute(
            """SELECT * FROM clinical_audit_checkpoints
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["table_counts"] = json.loads(result["table_counts_json"])
        result["table_max_rowid"] = json.loads(
            result["table_max_rowid_json"]
        )
        return result

    def verify_checkpoint(
        self,
        checkpoint_id: int,
        *,
        expected_hash: str | None = None,
    ) -> AuditVerification:
        db = self._db()
        row = db.execute(
            "SELECT * FROM clinical_audit_checkpoints WHERE id=?",
            (int(checkpoint_id),),
        ).fetchone()
        if not row:
            return AuditVerification(False, None, None, "checkpoint_missing")
        try:
            counts = json.loads(row["table_counts_json"])
            max_rowids = json.loads(row["table_max_rowid_json"])
            body = self._checkpoint_body(
                root_hash=str(row["root_hash"]),
                counts=counts,
                max_rowids=max_rowids,
                previous_checkpoint_hash=row["previous_checkpoint_hash"],
                created_at=str(row["created_at"]),
                created_by=str(row["created_by"]),
            )
            stored_checkpoint_hash = str(row["checkpoint_hash"])
            if not hmac.compare_digest(_hash(body), stored_checkpoint_hash):
                return AuditVerification(
                    False,
                    int(row["id"]),
                    stored_checkpoint_hash,
                    "checkpoint_hash_mismatch",
                )
            if expected_hash and not hmac.compare_digest(
                stored_checkpoint_hash,
                str(expected_hash),
            ):
                return AuditVerification(
                    False,
                    int(row["id"]),
                    stored_checkpoint_hash,
                    "activation_checkpoint_mismatch",
                )
            if row["previous_checkpoint_hash"]:
                previous = db.execute(
                    """SELECT checkpoint_hash FROM clinical_audit_checkpoints
                       WHERE id<? ORDER BY id DESC LIMIT 1""",
                    (int(row["id"]),),
                ).fetchone()
                if (
                    not previous
                    or previous["checkpoint_hash"]
                    != row["previous_checkpoint_hash"]
                ):
                    return AuditVerification(
                        False,
                        int(row["id"]),
                        stored_checkpoint_hash,
                        "checkpoint_chain_broken",
                    )
            root_hash, observed_counts = self._root(
                db,
                max_rowids=max_rowids,
            )
            if observed_counts != {
                key: int(value) for key, value in counts.items()
            }:
                return AuditVerification(
                    False,
                    int(row["id"]),
                    stored_checkpoint_hash,
                    "audit_row_count_mismatch",
                )
            if not hmac.compare_digest(root_hash, str(row["root_hash"])):
                return AuditVerification(
                    False,
                    int(row["id"]),
                    stored_checkpoint_hash,
                    "audit_root_mismatch",
                )
            return AuditVerification(
                True,
                int(row["id"]),
                stored_checkpoint_hash,
            )
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            return AuditVerification(
                False,
                int(row["id"]),
                str(row["checkpoint_hash"]),
                "audit_verification_error",
            )

    def verify_latest(self, *, require_checkpoint: bool = False) -> AuditVerification:
        latest = self.latest()
        if not latest:
            return AuditVerification(
                not require_checkpoint,
                None,
                None,
                "checkpoint_missing" if require_checkpoint else None,
            )
        return self.verify_checkpoint(int(latest["id"]))
