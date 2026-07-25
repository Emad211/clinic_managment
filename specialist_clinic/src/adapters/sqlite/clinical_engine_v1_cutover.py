"""Startup cutover from retired Clinical Engine v1 storage.

The canonical cleanup primitive is destructive but preserving. It is retained only for
copied pre-cutover databases. Fresh databases are created directly from the canonical v2
schema and no request-time compatibility object is installed.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from src.adapters.sqlite.clinical_engine_legacy_cleanup_schema import (
    cleanup_legacy_clinical_schema,
)



def _cleanup_needed(db: sqlite3.Connection) -> bool:
    """Detect both retired tables and either transitional lineage column."""
    row = db.execute(
        """SELECT 1
             FROM sqlite_master
            WHERE type='table'
              AND name IN ('clinical_rules', 'suggestion_log')
            UNION ALL
           SELECT 1
             FROM pragma_table_info('clinical_rule_versions')
            WHERE name='source_legacy_rule_id'
            UNION ALL
           SELECT 1
             FROM pragma_table_info('clinical_decision_events')
            WHERE name='legacy_source_suggestion_log_id'
            LIMIT 1"""
    ).fetchone()
    return row is not None


def ensure_v1_schema_cutover(
    db: sqlite3.Connection,
) -> dict[str, Any]:
    """Remove retired storage and verify the persistent schema is actually clean."""
    if not _cleanup_needed(db):
        return {"changed": False, "removed": []}
    result = cleanup_legacy_clinical_schema(db)
    if _cleanup_needed(db):
        raise RuntimeError(
            "retired Clinical Engine v1 storage remained after schema cutover"
        )
    return result
