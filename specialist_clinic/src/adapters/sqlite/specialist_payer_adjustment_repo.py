"""Repository for A7 payer evidence, financial adjustments, and review state."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_payer_adjustment_schema import (
    ensure_specialist_payer_adjustment_storage,
)
from src.common.utils import iran_now


class SpecialistFinancialReviewConflict(RuntimeError):
    pass


class SpecialistFinancialReviewValidationError(ValueError):
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


class SpecialistPayerAdjustmentRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        installed = db.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table'
                 AND name='specialist_payer_breakdown_observations'"""
        ).fetchone()
        if not installed:
            if db.in_transaction:
                raise RuntimeError(
                    "A7 payer adjustment storage is missing inside a transaction"
                )
            ensure_specialist_payer_adjustment_storage(db)
        return db

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def current_observation(self, accounting_invoice_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM specialist_financial_observations
                   WHERE accounting_invoice_id=?
                   ORDER BY observed_at DESC,id DESC LIMIT 1""",
                (int(accounting_invoice_id),),
            ).fetchone()
        )

    def observation(self, observation_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM specialist_financial_observations WHERE id=?",
                (int(observation_id),),
            ).fetchone()
        )

    # ------------------------------------------------------------- payer evidence
    def payer_breakdown(self, financial_observation_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM specialist_payer_breakdown_observations
                   WHERE financial_observation_id=?""",
                (int(financial_observation_id),),
            ).fetchone()
        )

    def record_payer_breakdown_once(
        self,
        *,
        observation: dict,
        snapshot: dict,
        observed_at: datetime | str | None = None,
        created_by: str = "system:financial-reconciliation",
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.payer_breakdown(int(observation["id"]))
            if existing:
                if existing["source_fingerprint"] != snapshot["source_fingerprint"]:
                    raise SpecialistFinancialReviewConflict(
                        "PAYER_BREAKDOWN_FINGERPRINT_CONFLICT"
                    )
                if commit:
                    db.commit()
                return existing, False
            evidence_code = str(
                snapshot.get("payer_breakdown_evidence") or ""
            ).strip()
            if evidence_code:
                collected_components = {
                    "patient_cash_collected": int(
                        snapshot.get("patient_cash_collected") or 0
                    ),
                    "patient_card_collected": int(
                        snapshot.get("patient_card_collected") or 0
                    ),
                    "insurance_collected": int(
                        snapshot.get("insurance_collected") or 0
                    ),
                    "unknown_collected": int(
                        snapshot.get("unknown_collected") or 0
                    ),
                }
            else:
                collected_components = {
                    "patient_cash_collected": 0,
                    "patient_card_collected": 0,
                    "insurance_collected": 0,
                    "unknown_collected": int(
                        observation["collected_amount"] or 0
                    ),
                }
                evidence_code = "LEGACY_UNAVAILABLE"
            if sum(collected_components.values()) != int(
                observation["collected_amount"] or 0
            ):
                raise SpecialistFinancialReviewValidationError(
                    "payer breakdown does not match financial observation"
                )
            observed = _time(observed_at or observation["observed_at"])
            created = _time()
            payload = {
                "financial_observation_id": int(observation["id"]),
                "accounting_invoice_id": int(
                    observation["accounting_invoice_id"]
                ),
                "journey_id": str(observation["journey_id"]),
                "encounter_id": str(observation["encounter_id"]),
                "patient_link_id": int(observation["patient_link_id"]),
                **collected_components,
                "unpaid_amount": int(snapshot.get("unpaid_amount") or 0),
                "paid_item_count": int(
                    snapshot.get("paid_item_count") or 0
                ),
                "unpaid_item_count": int(
                    snapshot.get("unpaid_item_count") or 0
                ),
                "unknown_payment_type_count": int(
                    snapshot.get("unknown_payment_type_count") or 0
                ),
                "evidence_code": evidence_code,
                "source_fingerprint": str(snapshot["source_fingerprint"]),
                "observed_at": observed,
                "created_at": created,
                "created_by": str(created_by),
            }
            cursor = db.execute(
                """INSERT INTO specialist_payer_breakdown_observations
                   (financial_observation_id,accounting_invoice_id,journey_id,
                    encounter_id,patient_link_id,patient_cash_collected,
                    patient_card_collected,insurance_collected,unknown_collected,
                    unpaid_amount,paid_item_count,unpaid_item_count,
                    unknown_payment_type_count,evidence_code,source_fingerprint,
                    observed_at,created_at,created_by,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                """SELECT * FROM specialist_payer_breakdown_observations
                   WHERE id=?""",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row), True
        except Exception:
            if commit:
                db.rollback()
            raise

    # ------------------------------------------------------------- review stream
    def current_review(self, accounting_invoice_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM specialist_financial_review_events
                   WHERE accounting_invoice_id=?
                   ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (int(accounting_invoice_id),),
            ).fetchone()
        )

    def ensure_review_required(
        self,
        *,
        observation: dict,
        actor_username: str = "system:financial-reconciliation",
        force: bool = False,
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            current = self.current_review(
                int(observation["accounting_invoice_id"])
            )
            if (
                current
                and int(current["financial_observation_id"])
                == int(observation["id"])
                and current["status"] in {"REVIEW_REQUIRED", "REVIEWED"}
                and not force
            ):
                if commit:
                    db.commit()
                return current, False
            event_type = "REVIEW_REQUIRED" if current is None else "REOPENED"
            if current is None:
                review_key = (
                    f"financial-review-required:"
                    f"{observation['accounting_invoice_id']}:"
                    f"{observation['id']}"
                )
            elif force:
                review_key = (
                    f"financial-review-reopen:"
                    f"{observation['accounting_invoice_id']}:"
                    f"{observation['id']}:after:{current['id']}"
                )
            else:
                review_key = (
                    f"financial-review-required:"
                    f"{observation['accounting_invoice_id']}:"
                    f"{observation['id']}"
                )
            recorded = _time()
            payload = {
                "accounting_invoice_id": int(
                    observation["accounting_invoice_id"]
                ),
                "financial_observation_id": int(observation["id"]),
                "journey_id": str(observation["journey_id"]),
                "encounter_id": str(observation["encounter_id"]),
                "patient_link_id": int(observation["patient_link_id"]),
                "event_type": event_type,
                "status": "REVIEW_REQUIRED",
                "effective_at": str(observation["observed_at"]),
                "recorded_at": recorded,
                "actor_username": str(actor_username),
                "actor_user_id": None,
                "note": (
                    "Current accounting snapshot requires explicit refund/"
                    "chargeback/settlement review."
                ),
                "idempotency_key": review_key,
                "supersedes_event_id": int(current["id"]) if current else None,
            }
            cursor = db.execute(
                """INSERT OR IGNORE INTO specialist_financial_review_events
                   (accounting_invoice_id,financial_observation_id,journey_id,
                    encounter_id,patient_link_id,event_type,status,effective_at,
                    recorded_at,actor_username,actor_user_id,note,
                    idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                """SELECT * FROM specialist_financial_review_events
                   WHERE idempotency_key=?""",
                (payload["idempotency_key"],),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row), cursor.rowcount == 1
        except Exception:
            if commit:
                db.rollback()
            raise

    def mark_reviewed(
        self,
        *,
        accounting_invoice_id: int,
        actor_username: str,
        actor_user_id: int | None,
        with_adjustment: bool,
        note: str,
        expected_current_event_id: int,
        idempotency_key: str,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            observation = self.current_observation(accounting_invoice_id)
            if not observation:
                raise LookupError("financial observation not found")
            current = self.current_review(accounting_invoice_id)
            if not current or int(current["id"]) != int(
                expected_current_event_id
            ):
                raise SpecialistFinancialReviewConflict(
                    "STALE_FINANCIAL_REVIEW"
                )
            if int(current["financial_observation_id"]) != int(
                observation["id"]
            ):
                raise SpecialistFinancialReviewConflict(
                    "CURRENT_OBSERVATION_REVIEW_REQUIRED"
                )
            if current["status"] == "REVIEWED":
                return current
            active = self.active_adjustments(accounting_invoice_id)
            stale_adjustments = [
                row for row in active
                if int(row["financial_observation_id"]) != int(observation["id"])
            ]
            if stale_adjustments:
                raise SpecialistFinancialReviewValidationError(
                    "active adjustments belong to an older financial observation; "
                    "correct or reverse them before review"
                )
            if with_adjustment and not active:
                raise SpecialistFinancialReviewValidationError(
                    "review with adjustment requires an active adjustment"
                )
            if not with_adjustment and active:
                raise SpecialistFinancialReviewValidationError(
                    "active adjustments require REVIEWED_WITH_ADJUSTMENT"
                )
            if not str(note or "").strip():
                raise SpecialistFinancialReviewValidationError(
                    "financial review note is required"
                )
            recorded = _time()
            event_type = (
                "REVIEWED_WITH_ADJUSTMENT"
                if with_adjustment
                else "REVIEWED_NO_ADJUSTMENT"
            )
            payload = {
                "accounting_invoice_id": int(accounting_invoice_id),
                "financial_observation_id": int(observation["id"]),
                "journey_id": str(observation["journey_id"]),
                "encounter_id": str(observation["encounter_id"]),
                "patient_link_id": int(observation["patient_link_id"]),
                "event_type": event_type,
                "status": "REVIEWED",
                "effective_at": recorded,
                "recorded_at": recorded,
                "actor_username": str(actor_username),
                "actor_user_id": actor_user_id,
                "note": str(note).strip(),
                "idempotency_key": str(idempotency_key),
                "supersedes_event_id": int(current["id"]),
            }
            cursor = db.execute(
                """INSERT INTO specialist_financial_review_events
                   (accounting_invoice_id,financial_observation_id,journey_id,
                    encounter_id,patient_link_id,event_type,status,effective_at,
                    recorded_at,actor_username,actor_user_id,note,
                    idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                "SELECT * FROM specialist_financial_review_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    # ------------------------------------------------------------- adjustment streams
    def current_adjustment(self, adjustment_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM specialist_financial_adjustment_events
                   WHERE adjustment_id=?
                   ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (str(adjustment_id),),
            ).fetchone()
        )

    def active_adjustments(self, accounting_invoice_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT adjustment.*
               FROM specialist_financial_adjustment_events adjustment
               WHERE adjustment.accounting_invoice_id=?
                 AND adjustment.id=(
                     SELECT head.id
                     FROM specialist_financial_adjustment_events head
                     WHERE head.adjustment_id=adjustment.adjustment_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 ) AND adjustment.status='ACTIVE'
               ORDER BY adjustment.recorded_at,adjustment.id""",
            (int(accounting_invoice_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_adjustment(
        self,
        *,
        accounting_invoice_id: int,
        adjustment_type: str,
        signed_amount: int,
        evidence_type: str,
        evidence_ref: str,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        occurred_at: datetime | str | None = None,
        note: str | None = None,
        adjustment_id: str | None = None,
        expected_current_event_id: int | None = None,
        commit: bool = True,
    ) -> dict:
        normalized_type = str(adjustment_type or "").strip().upper()
        normalized_evidence = str(evidence_type or "").strip().upper()
        allowed_types = {
            "REFUND",
            "CHARGEBACK",
            "INSURANCE_SETTLEMENT_CORRECTION",
            "WRITE_OFF",
            "OTHER",
        }
        allowed_evidence = {
            "BANK_REFERENCE",
            "INSURANCE_DOCUMENT",
            "ACCOUNTING_ACTIVITY_LOG",
            "RECEIPT_DOCUMENT",
            "MANUAL_VERIFIED",
        }
        if normalized_type not in allowed_types:
            raise SpecialistFinancialReviewValidationError(
                "invalid financial adjustment type"
            )
        if normalized_evidence not in allowed_evidence:
            raise SpecialistFinancialReviewValidationError(
                "invalid financial adjustment evidence"
            )
        amount = int(signed_amount)
        if amount == 0:
            raise SpecialistFinancialReviewValidationError(
                "financial adjustment amount cannot be zero"
            )
        if normalized_type in {"REFUND", "CHARGEBACK", "WRITE_OFF"} and amount > 0:
            raise SpecialistFinancialReviewValidationError(
                "refund, chargeback, and write-off must reduce collection"
            )
        if not str(evidence_ref or "").strip():
            raise SpecialistFinancialReviewValidationError(
                "financial adjustment evidence reference is required"
            )
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            observation = self.current_observation(accounting_invoice_id)
            if not observation:
                raise LookupError("financial observation not found")
            key = str(idempotency_key or "").strip()
            existing = db.execute(
                """SELECT * FROM specialist_financial_adjustment_events
                   WHERE idempotency_key=?""",
                (key,),
            ).fetchone()
            if existing:
                if commit:
                    db.commit()
                return dict(existing)
            stream_id = str(adjustment_id or "adjustment_" + uuid.uuid4().hex)
            current = self.current_adjustment(stream_id)
            current_id = int(current["id"]) if current else None
            if expected_current_event_id is not None and current_id != int(
                expected_current_event_id
            ):
                raise SpecialistFinancialReviewConflict(
                    "STALE_FINANCIAL_ADJUSTMENT"
                )
            if current and current["status"] != "ACTIVE":
                raise SpecialistFinancialReviewConflict(
                    "financial adjustment stream is terminal"
                )
            if current and not str(note or "").strip():
                raise SpecialistFinancialReviewValidationError(
                    "adjustment correction requires a note"
                )
            active_total = sum(
                int(row["signed_amount"])
                for row in self.active_adjustments(accounting_invoice_id)
                if row["adjustment_id"] != stream_id
            )
            if int(observation["collected_amount"] or 0) + active_total + amount < 0:
                raise SpecialistFinancialReviewValidationError(
                    "adjustments cannot reduce collection below zero"
                )
            recorded = _time()
            occurred = _time(occurred_at or recorded)
            payload = {
                "adjustment_id": stream_id,
                "accounting_invoice_id": int(accounting_invoice_id),
                "financial_observation_id": int(observation["id"]),
                "journey_id": str(observation["journey_id"]),
                "encounter_id": str(observation["encounter_id"]),
                "patient_link_id": int(observation["patient_link_id"]),
                "event_type": "CORRECTED" if current else "RECORDED",
                "status": "ACTIVE",
                "adjustment_type": normalized_type,
                "signed_amount": amount,
                "evidence_type": normalized_evidence,
                "evidence_ref": str(evidence_ref).strip(),
                "occurred_at": occurred,
                "recorded_at": recorded,
                "actor_username": str(actor_username),
                "actor_user_id": actor_user_id,
                "note": str(note or "").strip() or None,
                "idempotency_key": key,
                "supersedes_event_id": current_id,
            }
            cursor = db.execute(
                """INSERT INTO specialist_financial_adjustment_events
                   (adjustment_id,accounting_invoice_id,
                    financial_observation_id,journey_id,encounter_id,
                    patient_link_id,event_type,status,adjustment_type,
                    signed_amount,evidence_type,evidence_ref,occurred_at,
                    recorded_at,actor_username,actor_user_id,note,
                    idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            # Any adjustment change reopens the review for the current observation.
            review = self.current_review(accounting_invoice_id)
            if review and review["status"] == "REVIEWED":
                review_payload = {
                    "accounting_invoice_id": int(accounting_invoice_id),
                    "financial_observation_id": int(observation["id"]),
                    "journey_id": str(observation["journey_id"]),
                    "encounter_id": str(observation["encounter_id"]),
                    "patient_link_id": int(observation["patient_link_id"]),
                    "event_type": "REOPENED",
                    "status": "REVIEW_REQUIRED",
                    "effective_at": recorded,
                    "recorded_at": recorded,
                    "actor_username": str(actor_username),
                    "actor_user_id": actor_user_id,
                    "note": "Adjustment changed after review.",
                    "idempotency_key": f"financial-review-reopen:adjustment:{cursor.lastrowid}",
                    "supersedes_event_id": int(review["id"]),
                }
                db.execute(
                    """INSERT INTO specialist_financial_review_events
                       (accounting_invoice_id,financial_observation_id,
                        journey_id,encounter_id,patient_link_id,event_type,
                        status,effective_at,recorded_at,actor_username,
                        actor_user_id,note,idempotency_key,
                        supersedes_event_id,content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*review_payload.values(), _hash(review_payload)),
                )
            row = db.execute(
                """SELECT * FROM specialist_financial_adjustment_events
                   WHERE id=?""",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def reverse_adjustment(
        self,
        *,
        adjustment_id: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
        expected_current_event_id: int,
        idempotency_key: str,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            current = self.current_adjustment(adjustment_id)
            if not current or current["status"] != "ACTIVE":
                raise SpecialistFinancialReviewConflict(
                    "financial adjustment is not active"
                )
            if int(current["id"]) != int(expected_current_event_id):
                raise SpecialistFinancialReviewConflict(
                    "STALE_FINANCIAL_ADJUSTMENT"
                )
            if not str(note or "").strip():
                raise SpecialistFinancialReviewValidationError(
                    "adjustment reversal note is required"
                )
            recorded = _time()
            payload = {
                "adjustment_id": str(adjustment_id),
                "accounting_invoice_id": int(
                    current["accounting_invoice_id"]
                ),
                "financial_observation_id": int(
                    current["financial_observation_id"]
                ),
                "journey_id": str(current["journey_id"]),
                "encounter_id": str(current["encounter_id"]),
                "patient_link_id": int(current["patient_link_id"]),
                "event_type": "REVERSED",
                "status": "REVERSED",
                "adjustment_type": str(current["adjustment_type"]),
                "signed_amount": int(current["signed_amount"]),
                "evidence_type": str(current["evidence_type"]),
                "evidence_ref": str(current["evidence_ref"]),
                "occurred_at": recorded,
                "recorded_at": recorded,
                "actor_username": str(actor_username),
                "actor_user_id": actor_user_id,
                "note": str(note).strip(),
                "idempotency_key": str(idempotency_key),
                "supersedes_event_id": int(current["id"]),
            }
            cursor = db.execute(
                """INSERT INTO specialist_financial_adjustment_events
                   (adjustment_id,accounting_invoice_id,
                    financial_observation_id,journey_id,encounter_id,
                    patient_link_id,event_type,status,adjustment_type,
                    signed_amount,evidence_type,evidence_ref,occurred_at,
                    recorded_at,actor_username,actor_user_id,note,
                    idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            observation = self.current_observation(
                int(current["accounting_invoice_id"])
            )
            review = self.current_review(
                int(current["accounting_invoice_id"])
            )
            if observation and review and review["status"] == "REVIEWED":
                self.ensure_review_required(
                    observation=observation,
                    actor_username=actor_username,
                    force=True,
                    commit=False,
                )
            row = db.execute(
                """SELECT * FROM specialist_financial_adjustment_events
                   WHERE id=?""",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    # ------------------------------------------------------------- projections
    def invoice_projection(self, accounting_invoice_id: int) -> dict:
        observation = self.current_observation(accounting_invoice_id)
        if not observation:
            return {
                "available": False,
                "error_code": "FINANCIAL_OBSERVATION_MISSING",
            }
        breakdown = self.payer_breakdown(int(observation["id"]))
        review = self.current_review(accounting_invoice_id)
        adjustments = self.active_adjustments(accounting_invoice_id)
        stale_adjustments = [
            row for row in adjustments
            if int(row["financial_observation_id"]) != int(observation["id"])
        ]
        adjustment_total = sum(
            int(row["signed_amount"])
            for row in adjustments
            if int(row["financial_observation_id"]) == int(observation["id"])
        )
        adjusted = int(observation["collected_amount"] or 0) + adjustment_total
        current_review = bool(
            review
            and int(review["financial_observation_id"])
            == int(observation["id"])
            and review["status"] == "REVIEWED"
        )
        if not breakdown:
            status = "PAYER_BREAKDOWN_MISSING"
        elif stale_adjustments:
            status = "ADJUSTMENT_OBSERVATION_STALE"
        elif not review or int(review["financial_observation_id"]) != int(
            observation["id"]
        ):
            status = "FINANCIAL_REVIEW_STALE"
        elif review["status"] != "REVIEWED":
            status = "FINANCIAL_REVIEW_REQUIRED"
        else:
            status = "READY"
        return {
            "available": bool(breakdown),
            "accounting_invoice_id": int(accounting_invoice_id),
            "observation": observation,
            "payer_breakdown": breakdown,
            "review": review,
            "adjustments": adjustments,
            "stale_adjustments": stale_adjustments,
            "adjustment_total": adjustment_total,
            "gross_collected": int(observation["collected_amount"] or 0),
            "adjusted_collected": adjusted,
            "safe_to_sum": status == "READY" and current_review,
            "measurement_status": status,
            "policy_version": "RECORDED_ADJUSTMENTS_REVIEWED_V1",
        }

    def reviewed_finance_totals(
        self,
        *,
        invoice_ids: list[int] | None = None,
    ) -> dict:
        if invoice_ids is None:
            rows = self._db().execute(
                """SELECT DISTINCT accounting_invoice_id
                   FROM specialist_financial_observations
                   ORDER BY accounting_invoice_id"""
            ).fetchall()
            ids = [int(row["accounting_invoice_id"]) for row in rows]
        else:
            ids = sorted({int(value) for value in invoice_ids})
        total = {
            "gross_collected": 0,
            "adjustment_total": 0,
            "adjusted_collected": 0,
            "cash_collected": 0,
            "card_collected": 0,
            "insurance_collected": 0,
            "unknown_collected": 0,
            "unpaid_amount": 0,
            "invoices": 0,
            "reviewed_invoices": 0,
            "pending_review": 0,
            "safe_to_sum": True,
        }
        for invoice_id in ids:
            projection = self.invoice_projection(invoice_id)
            total["invoices"] += 1
            if not projection.get("safe_to_sum"):
                total["pending_review"] += 1
                total["safe_to_sum"] = False
                continue
            breakdown = projection["payer_breakdown"]
            total["reviewed_invoices"] += 1
            total["gross_collected"] += projection["gross_collected"]
            total["adjustment_total"] += projection["adjustment_total"]
            total["adjusted_collected"] += projection["adjusted_collected"]
            total["cash_collected"] += int(
                breakdown["patient_cash_collected"] or 0
            )
            total["card_collected"] += int(
                breakdown["patient_card_collected"] or 0
            )
            total["insurance_collected"] += int(
                breakdown["insurance_collected"] or 0
            )
            total["unknown_collected"] += int(
                breakdown["unknown_collected"] or 0
            )
            total["unpaid_amount"] += int(
                breakdown["unpaid_amount"] or 0
            )
        if total["pending_review"]:
            total["adjusted_collected"] = 0
            total["adjustment_total"] = 0
        return total


__all__ = [
    "SpecialistFinancialReviewConflict",
    "SpecialistFinancialReviewValidationError",
    "SpecialistPayerAdjustmentRepository",
]
