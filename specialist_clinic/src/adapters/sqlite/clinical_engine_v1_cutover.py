"""Request-bound cutover from retired Clinical Engine v1 storage.

The canonical cleanup primitive is destructive but preserving. This coordinator runs it
before any HTTP endpoint can use the database and installs one narrowly-scoped TEMP view
for the still-unmigrated manager disease counter. No v1 table or writable compatibility
surface remains in the main database after the first request.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from src.adapters.sqlite.clinical_engine_legacy_cleanup_schema import (
    cleanup_legacy_clinical_schema,
)


_MANAGER_DISEASE_ENDPOINT = "manager.diseases"


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


def _install_manager_rule_count_projection(
    db: sqlite3.Connection,
) -> None:
    """Expose a request-local, read-only count projection over governed v2 rules.

    The old manager route only selects ``condition_code`` and counts rows. A TEMP view
    is used instead of a permanent compatibility object, so the main schema remains
    clean and the projection disappears with the request connection.
    """
    db.execute("DROP VIEW IF EXISTS temp.clinical_rules")
    db.execute(
        """CREATE TEMP VIEW clinical_rules AS
           SELECT DISTINCT
                  version.id AS id,
                  CAST(condition_code.value AS TEXT) AS condition_code
             FROM main.clinical_rule_versions AS version
             JOIN json_each(
                    version.rule_json,
                    '$.scope.condition_codes'
                  ) AS condition_code
            WHERE version.lifecycle_status <> 'RETIRED'
           UNION ALL
           SELECT version.id AS id, 'all' AS condition_code
             FROM main.clinical_rule_versions AS version
            WHERE version.lifecycle_status <> 'RETIRED'
              AND COALESCE(
                    json_array_length(
                      json_extract(
                        version.rule_json,
                        '$.scope.condition_codes'
                      )
                    ),
                    0
                  ) = 0"""
    )


def ensure_v1_schema_cutover(
    db: sqlite3.Connection,
    *,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Remove retired storage before request handling and return a change report."""
    result: dict[str, Any] = {"changed": False, "removed": []}
    if _cleanup_needed(db):
        result = cleanup_legacy_clinical_schema(db)

    if endpoint == _MANAGER_DISEASE_ENDPOINT:
        _install_manager_rule_count_projection(db)
    return result
