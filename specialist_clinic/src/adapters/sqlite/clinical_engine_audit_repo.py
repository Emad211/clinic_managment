"""Public append-only audit repository for Clinical Engine v2.

The repository is composed from focused write and projection boundaries. Retired v1
suggestion-log and rule identifiers are not accepted, stored or projected.
"""
from __future__ import annotations

from .clinical_engine_audit_common import (
    json_text as _json_text,
    now_text as _now_text,
    optional_json as _optional_json,
)
from .clinical_engine_audit_projection_repo import (
    AuditProjectionRepositoryMixin,
)
from .clinical_engine_decision_audit_repo import (
    DecisionAuditRepositoryMixin,
)
from .clinical_engine_run_audit_repo import RunAuditRepositoryMixin


class ClinicalEngineAuditRepository(
    RunAuditRepositoryMixin,
    DecisionAuditRepositoryMixin,
    AuditProjectionRepositoryMixin,
):
    """Persist reproducible runs and append-only v2 audit events."""


__all__ = [
    "ClinicalEngineAuditRepository",
]
