"""Read-only legacy inputs and mode access for Clinical Engine v2 facts.

Every query used to assemble the legacy record lives here.  The service layer
receives plain dictionaries and never knows about SQLite.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db


_SOURCE_QUERIES = {
    "conditions": """SELECT pc.*, c.code AS condition_code, c.name AS condition_name
                       FROM patient_conditions pc
                       JOIN conditions c ON c.id=pc.condition_id
                       WHERE pc.patient_link_id=? AND pc.is_active=1
                       ORDER BY pc.id""",
    "medications": """SELECT * FROM patient_medications
                        WHERE patient_link_id=? AND is_active=1 ORDER BY id""",
    "allergies": "SELECT * FROM allergies WHERE patient_link_id=? ORDER BY id",
    "flags": """SELECT pf.*, fc.flag_type, fc.category
                  FROM patient_flags pf
                  LEFT JOIN flag_catalog fc ON fc.flag_key=pf.flag_key
                  WHERE pf.patient_link_id=? ORDER BY pf.flag_key""",
    "flag_catalog": """SELECT * FROM flag_catalog WHERE is_active=1
                         ORDER BY display_order, id""",
    "observations": """SELECT channel, record_id, key, value, unit, effective_at,
                                recorded_by, ref_low, ref_high
                         FROM (
                           SELECT 'vital' AS channel, id AS record_id, type AS key,
                                  value, unit, measured_at AS effective_at,
                                  recorded_by, NULL AS ref_low, NULL AS ref_high
                           FROM vital_readings WHERE patient_link_id=?
                           UNION ALL
                           SELECT 'lab' AS channel, id AS record_id, test_key AS key,
                                  value, unit, taken_at AS effective_at,
                                  recorded_by, ref_low, ref_high
                           FROM lab_results
                           WHERE patient_link_id=? AND test_key IS NOT NULL
                             AND trim(test_key)<>''
                         )
                         ORDER BY key, effective_at, channel, record_id""",
}


class ClinicalEngineFactRepository:
    """Fetch a deterministic raw bundle without interpreting clinical meaning."""

    def get_mode(self) -> str:
        row = get_db().execute(
            "SELECT value FROM settings WHERE key='clinical_engine_v2_mode'"
        ).fetchone()
        mode = str(row["value"] if row else "off").strip().lower()
        return mode if mode in {"off", "shadow"} else "off"

    def load_bundle(self, patient_link_id: int) -> dict[str, Any]:
        db = get_db()
        patient = db.execute(
            "SELECT * FROM patient_links WHERE id=?", (patient_link_id,)
        ).fetchone()
        if patient is None:
            raise LookupError(f"patient_link_id {patient_link_id} was not found")

        bundle: dict[str, Any] = {"patient": dict(patient), "unavailable": {}}
        for source, sql in _SOURCE_QUERIES.items():
            params = () if source == "flag_catalog" else (
                (patient_link_id, patient_link_id)
                if source == "observations"
                else (patient_link_id,)
            )
            try:
                bundle[source] = [dict(row) for row in db.execute(sql, params).fetchall()]
            except sqlite3.DatabaseError as exc:
                bundle[source] = []
                bundle["unavailable"][source] = type(exc).__name__
        return bundle
