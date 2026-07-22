"""Read-only legacy inputs and mode access for Clinical Engine v2 facts.

Every query used to assemble the legacy record lives here. The service layer receives
plain dictionaries and never knows about SQLite. Collection rows are deliberately read
with their inactive history; the pure adapter applies the requested ``as_of_at`` and the
append-only reconciliation contract.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from flask import current_app, has_app_context

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.clinical_engine_runtime_schema import ensure_runtime_schema


_SOURCE_QUERIES = {
    "conditions": """SELECT pc.*, c.code AS condition_code, c.name AS condition_name
                       FROM patient_conditions pc
                       JOIN conditions c ON c.id=pc.condition_id
                       WHERE pc.patient_link_id=? ORDER BY pc.id""",
    "medications": """SELECT * FROM patient_medications
                         WHERE patient_link_id=? ORDER BY id""",
    "medication_events": """SELECT * FROM medication_events
                              WHERE patient_link_id=? ORDER BY event_date, id""",
    "allergies": """SELECT * FROM allergies
                      WHERE patient_link_id=? ORDER BY id""",
    "reconciliations": """SELECT * FROM clinical_reconciliation_events
                            WHERE patient_link_id=? ORDER BY reconciled_at, id""",
    "flags": """SELECT pf.*, fc.flag_type, fc.category
                  FROM patient_flags pf
                  LEFT JOIN flag_catalog fc ON fc.flag_key=pf.flag_key
                  WHERE pf.patient_link_id=? ORDER BY pf.flag_key""",
    "flag_catalog": """SELECT * FROM flag_catalog WHERE is_active=1
                         ORDER BY display_order, id""",
    "observations": """SELECT channel, record_id, key, value, unit, effective_at,
                                recorded_by, ref_low, ref_high, source_detail
                         FROM (
                           SELECT 'vital' AS channel, id AS record_id, type AS key,
                                  value, unit, measured_at AS effective_at,
                                  recorded_by, NULL AS ref_low, NULL AS ref_high,
                                  COALESCE(source, 'clinic') AS source_detail
                           FROM vital_readings WHERE patient_link_id=?
                           UNION ALL
                           SELECT 'lab' AS channel, id AS record_id, test_key AS key,
                                  value, unit, taken_at AS effective_at,
                                  recorded_by, ref_low, ref_high,
                                  'laboratory' AS source_detail
                           FROM lab_results
                           WHERE patient_link_id=? AND test_key IS NOT NULL
                             AND trim(test_key)<>''
                         )
                         ORDER BY key, effective_at, channel, record_id""",
}


class ClinicalEngineFactRepository:
    """Fetch a deterministic raw bundle without interpreting clinical meaning."""

    @staticmethod
    def _db():
        db = get_db()
        ensure_runtime_schema(db)
        return db

    def get_mode(self) -> str:
        row = self._db().execute(
            "SELECT value FROM settings WHERE key='clinical_engine_v2_mode'"
        ).fetchone()
        mode = str(row["value"] if row else "off").strip().lower()
        if mode not in {"off", "shadow", "on_selected", "on"}:
            return "off"
        if mode in {"on_selected", "on"}:
            # Global rollout is never available through a raw setting write,
            # including in tests. The test-only compatibility bypass applies
            # solely to the historical selected-demo mode.
            require_gate = mode == "on"
            if mode == "on_selected" and has_app_context():
                require_gate = current_app.config.get(
                    "CLINICAL_ENGINE_REQUIRE_ACTIVATION_GATE",
                    not current_app.config.get("TESTING", False),
                )
            if require_gate:
                from src.adapters.sqlite.clinical_engine_activation_repo import (
                    ClinicalEngineActivationRepository,
                )
                if not ClinicalEngineActivationRepository().valid_seal(mode):
                    return "off"
        return mode

    def clinical_data_revision(self, patient_link_id: int) -> int:
        row = self._db().execute(
            "SELECT clinical_data_revision FROM patient_links WHERE id=?",
            (patient_link_id,),
        ).fetchone()
        if not row:
            raise LookupError(f"patient_link_id {patient_link_id} was not found")
        return int(row["clinical_data_revision"] or 0)

    def is_selected_patient(self, patient_link_id: int) -> bool:
        """Limit the first visible rollout to the ten seeded demo patients."""
        row = self._db().execute(
            "SELECT national_id FROM patient_links WHERE id=?", (patient_link_id,)
        ).fetchone()
        if not row:
            return False
        national_id = str(row["national_id"] or "").strip().upper()
        return national_id in {f"TEST{index:04d}" for index in range(1, 11)}

    def load_bundle(self, patient_link_id: int) -> dict[str, Any]:
        """Read every fact source from one SQLite snapshot.

        A SAVEPOINT keeps the patient revision, collection review events and all
        source rows consistent even if another request changes the record.
        """
        db = self._db()
        db.execute("SAVEPOINT clinical_fact_bundle")
        try:
            patient = db.execute(
                "SELECT * FROM patient_links WHERE id=?", (patient_link_id,)
            ).fetchone()
            if patient is None:
                raise LookupError(f"patient_link_id {patient_link_id} was not found")

            bundle: dict[str, Any] = {"patient": dict(patient), "unavailable": {}}
            for source, sql in _SOURCE_QUERIES.items():
                if source == "flag_catalog":
                    params = ()
                elif source == "observations":
                    params = (patient_link_id, patient_link_id)
                else:
                    params = (patient_link_id,)
                try:
                    bundle[source] = [
                        dict(row) for row in db.execute(sql, params).fetchall()
                    ]
                except sqlite3.DatabaseError as exc:
                    bundle[source] = []
                    bundle["unavailable"][source] = type(exc).__name__
            db.execute("RELEASE SAVEPOINT clinical_fact_bundle")
            return bundle
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT clinical_fact_bundle")
            db.execute("RELEASE SAVEPOINT clinical_fact_bundle")
            raise
