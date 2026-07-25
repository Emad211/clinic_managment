"""Canonical SQLite source bundle and effective Clinical Engine mode.

Every visible rollout uses the same activation contract in tests and production.  A raw
setting write can enable shadow capture, but it can never expose recommendations without
an exact report, approvals and seal for the current engine and ruleset.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.clinical_engine_runtime_schema import (
    ensure_runtime_schema,
)
from src.adapters.sqlite.core import get_db


_SOURCE_QUERIES = {
    "conditions": """SELECT pc.*, c.code AS condition_code,
                                c.name AS condition_name
                       FROM patient_conditions pc
                       JOIN conditions c ON c.id=pc.condition_id
                       WHERE pc.patient_link_id=? ORDER BY pc.id""",
    "medications": """SELECT * FROM patient_medications
                       WHERE patient_link_id=? ORDER BY id""",
    "medication_events": """SELECT * FROM medication_events
                             WHERE patient_link_id=? ORDER BY event_date, id""",
    "allergies": """SELECT allergy.*, catalog.concept_key AS allergy_concept_key,
                             catalog.display_name AS allergy_concept_name
                      FROM allergies allergy
                      LEFT JOIN allergy_catalog catalog
                        ON catalog.id=allergy.allergy_concept_id
                      WHERE allergy.patient_link_id=? ORDER BY allergy.id""",
    "reconciliations": """SELECT * FROM clinical_reconciliation_events
                           WHERE patient_link_id=? ORDER BY reconciled_at, id""",
    "conflicts": """SELECT * FROM clinical_data_conflict_events
                       WHERE patient_link_id=? ORDER BY recorded_at, id""",
    "flags": """SELECT * FROM clinical_flag_events
                 WHERE patient_link_id=? ORDER BY recorded_at, id""",
    "flag_catalog": """SELECT * FROM flag_catalog WHERE is_active=1
                        ORDER BY display_order, id""",
    "observations": """SELECT channel, record_id, key, value, unit,
                               effective_at, recorded_by, ref_low, ref_high,
                               source_detail
                        FROM (
                          SELECT 'vital' AS channel, id AS record_id,
                                 type AS key, value, unit,
                                 measured_at AS effective_at, recorded_by,
                                 NULL AS ref_low, NULL AS ref_high,
                                 COALESCE(source, 'clinic') AS source_detail
                          FROM vital_readings WHERE patient_link_id=?
                          UNION ALL
                          SELECT 'lab' AS channel, id AS record_id,
                                 test_key AS key, value, unit,
                                 taken_at AS effective_at, recorded_by,
                                 ref_low, ref_high,
                                 'laboratory' AS source_detail
                          FROM lab_results
                          WHERE patient_link_id=?
                            AND test_key IS NOT NULL
                            AND trim(test_key)<>''
                        )
                        ORDER BY key, effective_at, channel, record_id""",
}


class ClinicalEngineFactRepository:
    """Fetch one deterministic source bundle without clinical interpretation."""

    @staticmethod
    def _db():
        db = get_db()
        ensure_runtime_schema(db)
        return db

    def get_mode(self) -> str:
        row = self._db().execute(
            "SELECT value FROM settings "
            "WHERE key='clinical_engine_v2_mode'"
        ).fetchone()
        mode = str(row["value"] if row else "off").strip().lower()
        if mode not in {"off", "shadow", "on_selected", "on"}:
            return "off"
        if mode in {"on_selected", "on"} and not (
            ClinicalEngineActivationRepository().valid_seal(mode)
        ):
            return "off"
        return mode

    def clinical_data_revision(self, patient_link_id: int) -> int:
        row = self._db().execute(
            "SELECT clinical_data_revision FROM patient_links WHERE id=?",
            (patient_link_id,),
        ).fetchone()
        if not row:
            raise LookupError(
                f"patient_link_id {patient_link_id} was not found"
            )
        return int(row["clinical_data_revision"] or 0)

    def is_selected_patient(self, patient_link_id: int) -> bool:
        """Limit the first visible rollout to its explicit seeded cohort."""
        row = self._db().execute(
            "SELECT national_id FROM patient_links WHERE id=?",
            (patient_link_id,),
        ).fetchone()
        if not row:
            return False
        national_id = str(row["national_id"] or "").strip().upper()
        return national_id in {
            f"TEST{index:04d}" for index in range(1, 11)
        }

    def load_bundle(self, patient_link_id: int) -> dict[str, Any]:
        """Read patient revision, reconciliations and all sources in one snapshot."""
        db = self._db()
        db.execute("SAVEPOINT clinical_fact_bundle")
        try:
            patient = db.execute(
                "SELECT * FROM patient_links WHERE id=?",
                (patient_link_id,),
            ).fetchone()
            if patient is None:
                raise LookupError(
                    f"patient_link_id {patient_link_id} was not found"
                )

            bundle: dict[str, Any] = {
                "patient": dict(patient),
                "unavailable": {},
            }
            for source, sql in _SOURCE_QUERIES.items():
                if source == "flag_catalog":
                    params = ()
                elif source == "observations":
                    params = (patient_link_id, patient_link_id)
                else:
                    params = (patient_link_id,)
                try:
                    bundle[source] = [
                        dict(row)
                        for row in db.execute(sql, params).fetchall()
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
