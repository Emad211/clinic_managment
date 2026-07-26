"""A7 orchestration for payer evidence and reviewed financial adjustments."""
from __future__ import annotations

import sqlite3
import uuid

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_payer_adjustment_repo import (
    SpecialistFinancialReviewConflict,
    SpecialistFinancialReviewValidationError,
    SpecialistPayerAdjustmentRepository,
)


class SpecialistPayerAdjustmentService:
    def __init__(
        self,
        *,
        repository: SpecialistPayerAdjustmentRepository | None = None,
        db: sqlite3.Connection | None = None,
    ):
        self._connection = db
        self.repository = repository or SpecialistPayerAdjustmentRepository(db)

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def attach_reconciliation_evidence(
        self,
        *,
        observation: dict,
        snapshot: dict,
        observed_at,
        actor_username: str = "system:financial-reconciliation",
        commit: bool = True,
    ) -> dict:
        """Persist payer evidence and review obligation for one A4 observation."""
        db = self._db()
        owns_transaction = bool(commit and not db.in_transaction)
        if owns_transaction:
            db.execute("BEGIN IMMEDIATE")
        try:
            breakdown, breakdown_created = self.repository.record_payer_breakdown_once(
                observation=observation,
                snapshot=snapshot,
                observed_at=observed_at,
                created_by=actor_username,
                commit=False,
            )
            review, review_created = self.repository.ensure_review_required(
                observation=observation,
                actor_username=actor_username,
                commit=False,
            )
            if owns_transaction:
                db.commit()
            return {
                "breakdown": breakdown,
                "breakdown_created": bool(breakdown_created),
                "review": review,
                "review_created": bool(review_created),
            }
        except Exception:
            if owns_transaction:
                db.rollback()
            raise

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
        note: str | None = None,
        occurred_at=None,
        adjustment_id: str | None = None,
        expected_current_event_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        return self.repository.record_adjustment(
            accounting_invoice_id=accounting_invoice_id,
            adjustment_type=adjustment_type,
            signed_amount=signed_amount,
            evidence_type=evidence_type,
            evidence_ref=evidence_ref,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            idempotency_key=(
                idempotency_key
                or f"financial-adjustment:{accounting_invoice_id}:{uuid.uuid4().hex}"
            ),
            occurred_at=occurred_at,
            note=note,
            adjustment_id=adjustment_id,
            expected_current_event_id=expected_current_event_id,
        )

    def reverse_adjustment(
        self,
        *,
        adjustment_id: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
        expected_current_event_id: int,
        idempotency_key: str | None = None,
    ) -> dict:
        return self.repository.reverse_adjustment(
            adjustment_id=adjustment_id,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            note=note,
            expected_current_event_id=expected_current_event_id,
            idempotency_key=(
                idempotency_key
                or f"financial-adjustment-reverse:{adjustment_id}:{uuid.uuid4().hex}"
            ),
        )

    def mark_reviewed(
        self,
        *,
        accounting_invoice_id: int,
        actor_username: str,
        actor_user_id: int | None,
        with_adjustment: bool,
        note: str,
        expected_current_event_id: int,
        idempotency_key: str | None = None,
    ) -> dict:
        return self.repository.mark_reviewed(
            accounting_invoice_id=accounting_invoice_id,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            with_adjustment=with_adjustment,
            note=note,
            expected_current_event_id=expected_current_event_id,
            idempotency_key=(
                idempotency_key
                or f"financial-review:{accounting_invoice_id}:{uuid.uuid4().hex}"
            ),
        )

    def invoice_projection(self, accounting_invoice_id: int) -> dict:
        return self.repository.invoice_projection(accounting_invoice_id)

    def totals(self, invoice_ids: list[int] | None = None) -> dict:
        return self.repository.reviewed_finance_totals(invoice_ids=invoice_ids)


__all__ = [
    "SpecialistFinancialReviewConflict",
    "SpecialistFinancialReviewValidationError",
    "SpecialistPayerAdjustmentService",
]
