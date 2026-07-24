"""Fail-closed canonical adapter for reconciled clinic source bundles.

The lower-level row mapper remains pure, but the runtime accepts only the complete
repository contract.  Hand-built legacy bundles without reconciliation metadata are no
longer silently interpreted as reviewed collections, in tests or production.
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


_REQUIRED_BUNDLE_KEYS = frozenset(
    {
        "patient",
        "conditions",
        "medications",
        "medication_events",
        "allergies",
        "reconciliations",
        "conflicts",
        "flags",
        "flag_catalog",
        "observations",
        "unavailable",
    }
)
_HISTORY_WARNING = "HISTORICAL_INTERVAL_APPROXIMATION"
_MEDICATION_IDENTITY_WARNING = "UNMAPPED_MEDICATION_CONCEPT"


class ReconciledFactBundleAdapter:
    """Apply the complete source contract before snapshot hashing and evaluation."""

    def __init__(self, delegate=None):
        self.delegate = delegate or LegacyFactBundleAdapter()

    @staticmethod
    def _requires_provisional(fact: ClinicalFact) -> bool:
        warnings = set(fact.warnings)
        if (
            fact.kind is FactKind.MEDICATION
            and _MEDICATION_IDENTITY_WARNING in warnings
        ):
            return True
        return bool(
            fact.kind
            in {
                FactKind.CONDITION,
                FactKind.MEDICATION,
                FactKind.ALLERGY,
            }
            and _HISTORY_WARNING in warnings
        )

    def adapt(
        self,
        bundle: dict[str, Any],
        *,
        as_of_at: datetime,
    ) -> tuple[ClinicalFact, ...]:
        missing = sorted(_REQUIRED_BUNDLE_KEYS - set(bundle))
        if missing:
            raise ValueError(
                "clinical fact bundle is incomplete: " + ", ".join(missing)
            )
        facts = self.delegate.adapt(bundle, as_of_at=as_of_at)
        return tuple(
            replace(
                fact,
                verification=VerificationStatus.PROVISIONAL,
            )
            if (
                fact.verification is VerificationStatus.CONFIRMED
                and self._requires_provisional(fact)
            )
            else fact
            for fact in facts
        )
