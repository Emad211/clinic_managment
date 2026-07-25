"""Retired Clinical Engine v1 compatibility shell.

The executable v1 DSL and ``clinical_rules`` database reader were removed. Production
code has no consumer of this module; the class remains temporarily so older imports and
one shadow-capture regression test fail safely without restoring parallel clinical
logic. It never interprets patient data and never emits a recommendation.
"""
from __future__ import annotations

from datetime import datetime
import logging

from src.common.utils import iran_now
from src.services.clinical_engine.fact_builder import ShadowFactCapture


logger = logging.getLogger(__name__)


class RuleEngine:
    """Non-clinical tombstone for the retired v1 API.

    ``evaluate`` may preserve the historical shadow-audit seam while the stacked
    migration tests are being simplified, but its observable recommendation output is
    permanently empty and it never reads ``clinical_rules`` or patient facts.
    """

    def __init__(self, *, capture_shadow: bool = True):
        self.capture_shadow = bool(capture_shadow)

    @staticmethod
    def build_facts(
        _patient_link_id: int,
        *,
        as_of_at: datetime | None = None,
    ) -> dict:
        del as_of_at
        return {"engine": "v1-retired", "facts": ()}

    def evaluate(
        self,
        patient_link_id: int,
        *,
        as_of_at: datetime | None = None,
    ) -> list[dict]:
        if self.capture_shadow:
            try:
                ShadowFactCapture().capture(
                    patient_link_id,
                    as_of_at=as_of_at or iran_now(),
                    created_by="retired-v1-shadow-seam",
                )
            except Exception:
                logger.exception(
                    "Clinical Engine v2 shadow capture failed for patient %s",
                    patient_link_id,
                )
        return []

    def grouped(self, patient_link_id: int) -> dict:
        self.evaluate(patient_link_id)
        return {
            "sections": [],
            "count": 0,
            "has_redflag": False,
            "retired": True,
        }
