"""Safety post-processing for facts emitted from reconciled legacy collections.

The legacy adapter correctly preserves concrete rows independently from collection
completeness.  A concrete row, however, must not become *confirmed clinical identity*
when its medication concept or historical interval is still approximate.  This wrapper
keeps the pure legacy mapping reusable while applying the stricter v2 verification
contract before snapshot hashing and rule evaluation.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from src.domain.clinical_engine import (
    ClinicalFact,
    FactKind,
    VerificationStatus,
)
from src.services.clinical_engine.legacy_adapter import (
    LegacyFactBundleAdapter,
)


_HISTORY_WARNING = "HISTORICAL_INTERVAL_APPROXIMATION"
_MEDICATION_IDENTITY_WARNING = "UNMAPPED_MEDICATION_CONCEPT"


class ReconciledFactBundleAdapter:
    """Wrap legacy row mapping with fail-closed item verification semantics."""

    def __init__(self, delegate=None):
        self.delegate = delegate or LegacyFactBundleAdapter()

    @staticmethod
    def _requires_provisional(fact: ClinicalFact) -> bool:
        warnings = set(fact.warnings)
        if fact.kind is FactKind.MEDICATION and (
            _MEDICATION_IDENTITY_WARNING in warnings
        ):
            return True
        return bool(
            fact.kind
            in {FactKind.CONDITION, FactKind.MEDICATION, FactKind.ALLERGY}
            and _HISTORY_WARNING in warnings
        )

    def adapt(
        self,
        bundle: dict[str, Any],
        *,
        as_of_at: datetime,
    ) -> tuple[ClinicalFact, ...]:
        facts = self.delegate.adapt(bundle, as_of_at=as_of_at)
        return tuple(
            replace(fact, verification=VerificationStatus.PROVISIONAL)
            if (
                fact.verification is VerificationStatus.CONFIRMED
                and self._requires_provisional(fact)
            )
            else fact
            for fact in facts
        )
