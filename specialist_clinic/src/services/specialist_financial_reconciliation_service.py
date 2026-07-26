"""Reconcile completed specialist encounters with read-only accounting evidence.

A7 writes the A4 financial observation, payer breakdown, and adjustment-review obligation
in one local transaction. The accounting database remains read-only.
"""
from __future__ import annotations

from datetime import datetime

from src.adapters import specialist_accounting_invoice_reader as accounting
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelConflict,
    SpecialistFinancialFunnelRepository,
)
from src.adapters.sqlite.specialist_payer_adjustment_repo import (
    SpecialistFinancialReviewConflict,
    SpecialistFinancialReviewValidationError,
    SpecialistPayerAdjustmentRepository,
)
from src.common.utils import iran_now
from src.services.specialist_payer_adjustment_service import (
    SpecialistPayerAdjustmentService,
)


class SpecialistFinancialReconciliationService:
    def __init__(self, *, repository=None, reader=None, clock=None):
        self.repository = repository or SpecialistFinancialFunnelRepository()
        self.reader = reader or accounting
        self.clock = clock or iran_now

    def _context(self, accounting_invoice_id: int) -> dict:
        contexts = {
            int(row["accounting_invoice_id"]): row
            for row in self.repository.eligible_invoice_contexts()
        }
        context = contexts.get(int(accounting_invoice_id))
        if not context:
            raise SpecialistFinancialFunnelConflict(
                "COMPLETED_ATTRIBUTED_ENCOUNTER_REQUIRED"
            )
        return context

    def _store(
        self,
        *,
        context: dict,
        snapshot: dict,
        observed_at,
    ) -> dict:
        db = get_db()
        if db.in_transaction:
            raise SpecialistFinancialFunnelConflict(
                "CALLER_TRANSACTION_ACTIVE"
            )
        db.execute("BEGIN IMMEDIATE")
        try:
            funnel = SpecialistFinancialFunnelRepository(db)
            observation, observation_created = funnel.record_observation_once(
                context=context,
                snapshot=snapshot,
                observed_at=observed_at,
                commit=False,
            )
            a7_repository = SpecialistPayerAdjustmentRepository(db)
            evidence = SpecialistPayerAdjustmentService(
                repository=a7_repository,
                db=db,
            ).attach_reconciliation_evidence(
                observation=observation,
                snapshot=snapshot,
                observed_at=observed_at,
                commit=False,
            )
            if int(observation["accounting_patient_id"]) != int(
                context["accounting_patient_id"]
            ):
                raise SpecialistFinancialFunnelConflict(
                    "STORED_FINANCIAL_PATIENT_SCOPE_MISMATCH"
                )
            db.commit()
            return {
                "observation": observation,
                "observation_created": bool(observation_created),
                **evidence,
            }
        except Exception:
            db.rollback()
            raise

    def reconcile_invoice(self, accounting_invoice_id: int) -> dict:
        context = self._context(accounting_invoice_id)
        snapshot = self.reader.invoice_financial_snapshot(
            int(accounting_invoice_id)
        )
        stored = self._store(
            context=context,
            snapshot=snapshot,
            observed_at=self.clock(),
        )
        observation = stored["observation"]
        return {
            "accounting_invoice_id": int(accounting_invoice_id),
            "observation_id": int(observation["id"]),
            "created": stored["observation_created"],
            "payer_breakdown_created": stored["breakdown_created"],
            "review_created": stored["review_created"],
            "review_status": stored["review"]["status"],
            "collection_state": observation["collection_state"],
        }

    def reconcile_all(self) -> dict:
        contexts = self.repository.eligible_invoice_contexts()
        observed = 0
        changed = 0
        payer_changed = 0
        reviews_opened = 0
        issues: list[dict] = []
        observed_at = self.clock()
        for context in contexts:
            invoice_id = int(context["accounting_invoice_id"])
            try:
                snapshot = self.reader.invoice_financial_snapshot(invoice_id)
                stored = self._store(
                    context=context,
                    snapshot=snapshot,
                    observed_at=observed_at,
                )
            except (
                accounting.AccountingInvoiceUnavailable,
                accounting.AccountingInvoiceSchemaError,
                LookupError,
                ValueError,
                SpecialistFinancialFunnelConflict,
                SpecialistFinancialReviewConflict,
                SpecialistFinancialReviewValidationError,
            ) as exc:
                issues.append(
                    {
                        "accounting_invoice_id": invoice_id,
                        "code": type(exc).__name__.upper(),
                        "error": str(exc),
                    }
                )
                continue
            observed += 1
            changed += int(stored["observation_created"])
            payer_changed += int(stored["breakdown_created"])
            reviews_opened += int(stored["review_created"])
        return {
            "eligible": len(contexts),
            "observed": observed,
            "changed": changed,
            "payer_changed": payer_changed,
            "reviews_opened": reviews_opened,
            "issues": issues,
            "observed_at": (
                observed_at.isoformat(sep=" ", timespec="seconds")
                if isinstance(observed_at, datetime)
                else str(observed_at)
            ),
        }
