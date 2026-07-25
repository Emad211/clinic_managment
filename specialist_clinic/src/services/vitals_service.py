"""Descriptive vital-series helpers.

Clinical threshold evaluation, control labels and red-flag classification were retired
from this service.  Actionable interpretation belongs exclusively to the governed
Clinical Engine v2.  This module now returns only recorded values, units and dates.
"""
from __future__ import annotations

from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES


class VitalsService:
    def __init__(self, repo: VitalsRepository | None = None):
        self.repo = repo or VitalsRepository()

    def latest(self, pid: int) -> dict:
        """Return the latest recorded observation per key without grading it."""
        return self.repo.latest_by_type(pid)

    def chart_series(self, pid: int, vtype: str) -> dict:
        """Return a descriptive, chronological series for one observation key."""
        from src.common.utils import format_jalali_date

        readings = self.repo.get_readings_canonical(pid, vtype, limit=200)
        return {
            "label": VITAL_TYPES.get(vtype, {}).get("label", vtype),
            "unit": VITAL_TYPES.get(vtype, {}).get("unit", ""),
            "labels": [
                format_jalali_date(reading["measured_at"])
                for reading in readings
            ],
            "values": [reading["value"] for reading in readings],
            "projection_policy": "DESCRIPTIVE_ONLY",
        }
