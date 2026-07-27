"""Public repository facade for immutable Clinical Engine v2 rules.

The implementation is split by responsibility. No component reads the retired mutable
v1 catalog or persists a legacy lineage identifier.
"""
from __future__ import annotations

from .clinical_engine_rule_projection_repo import RuleProjectionRepositoryMixin
from .clinical_engine_rule_review_repo import RuleReviewRepositoryMixin
from .clinical_engine_rule_version_repo import RuleVersionRepositoryMixin
from .clinical_engine_rules_common import ClinicalEngineStorageConflict
from .clinical_engine_ruleset_repo import RulesetRepositoryMixin


class ClinicalEngineRulesRepository(
    RuleVersionRepositoryMixin,
    RulesetRepositoryMixin,
    RuleReviewRepositoryMixin,
    RuleProjectionRepositoryMixin,
):
    """SQLite boundary for compiled rule versions and frozen rulesets."""


__all__ = [
    "ClinicalEngineRulesRepository",
    "ClinicalEngineStorageConflict",
]
