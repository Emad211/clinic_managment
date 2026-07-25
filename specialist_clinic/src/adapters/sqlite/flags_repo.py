"""Clinical flag catalog/history plus the pharmacologic class catalog."""
from __future__ import annotations

from src.adapters.sqlite.core import get_db

from .clinical_flag_catalog_repo import ClinicalFlagCatalogRepositoryMixin
from .clinical_flag_common import (
    CATEGORY_LABELS,
    ClinicalFlagConflict,
    ClinicalFlagValidationError,
)
from .clinical_flag_event_repo import ClinicalFlagEventRepositoryMixin
from .clinical_flag_projection_repo import ClinicalFlagProjectionRepositoryMixin


class ClinicalFlagsRepository(
    ClinicalFlagCatalogRepositoryMixin,
    ClinicalFlagEventRepositoryMixin,
    ClinicalFlagProjectionRepositoryMixin,
):
    """Public boundary for typed append-only clinical decision inputs."""

    def drug_classes(self, active_only: bool = True) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM drug_classes"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY display_order, id"
        return [dict(row) for row in db.execute(sql).fetchall()]

    def drug_class_map(self) -> dict:
        return {
            item["class_key"]: item["label"]
            for item in self.drug_classes(active_only=False)
        }


__all__ = [
    "CATEGORY_LABELS",
    "ClinicalFlagConflict",
    "ClinicalFlagValidationError",
    "ClinicalFlagsRepository",
]
