"""Reconcile completed specialist encounters with read-only accounting observations."""
from __future__ import annotations

from datetime import datetime

from src.adapters import specialist_accounting_invoice_reader as accounting
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelConflict,
    SpecialistFinancialFunnelRepository,
)
from src.common.utils import iran_now


class SpecialistFinancialReconciliationService:
    def __init__(self, *, repository=None, reader=None, clock=None):
        self.repository = repository or SpecialistFinancialFunnelRepository()
        self.reader = reader or accounting
        self.clock = clock or iran_now

    def reconcile_invoice(self, accounting_invoice_id: int) -> dict:
        contexts = {
            int(row["accounting_invoice_id"]): row
            for row in self.repository.eligible_invoice_contexts()
        }
        context = contexts.get(int(accounting_invoice_id))
        if not context:
            raise SpecialistFinancialFunnelConflict(
                "COMPLETED_ATTRIBUTED_ENCOUNTER_REQUIRED"
            )
        snapshot = self.reader.invoice_financial_snapshot(
            int(accounting_invoice_id)
        )
        observation, created = self.repository.record_observation_once(
            context=context,
            snapshot=snapshot,
            observed_at=self.clock(),
        )
        return {
            "accounting_invoice_id": int(accounting_invoice_id),
            "observation_id": int(observation["id"]),
            "created": bool(created),
            "collection_state": observation["collection_state"],
        }

    def reconcile_all(self) -> dict:
        contexts = self.repository.eligible_invoice_contexts()
        observed = 0
        changed = 0
        issues: list[dict] = []
        observed_at = self.clock()
        for context in contexts:
            invoice_id = int(context["accounting_invoice_id"])
            try:
                snapshot = self.reader.invoice_financial_snapshot(invoice_id)
                observation, created = self.repository.record_observation_once(
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
            changed += int(created)
            if int(observation["accounting_patient_id"]) != int(
                context["accounting_patient_id"]
            ):
                raise SpecialistFinancialFunnelConflict(
                    "STORED_FINANCIAL_PATIENT_SCOPE_MISMATCH"
                )
        return {
            "eligible": len(contexts),
            "observed": observed,
            "changed": changed,
            "issues": issues,
            "observed_at": (
                observed_at.isoformat(sep=" ", timespec="seconds")
                if isinstance(observed_at, datetime)
                else str(observed_at)
            ),
        }
