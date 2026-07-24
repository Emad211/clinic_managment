"""Descriptive observation-catalog facade.

The pre-v2 threshold evaluator was retired.  This compatibility service exposes only
catalog metadata used to label and group recorded observations.  Clinical grading and
actionable interpretation belong exclusively to Clinical Engine v2.
"""
from __future__ import annotations

from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository


class ClinicalRulesService:
    def __init__(self, repo: ClinicalRulesRepository | None = None):
        self.repo = repo or ClinicalRulesRepository()

    def map(self) -> dict[str, dict]:
        return self.repo.as_map()

    def for_conditions(self, codes: list[str]) -> list[dict]:
        return self.repo.for_conditions(codes)
