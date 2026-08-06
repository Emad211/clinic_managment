"""Current acquisition attribution for patients enrolled outside Lead Pipeline."""
from __future__ import annotations

import sqlite3


def ensure_patient_acquisition_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS growth_patient_acquisition (
            patient_link_id INTEGER PRIMARY KEY,
            source_code TEXT NOT NULL,
            source_detail TEXT,
            referrer_patient_link_id INTEGER,
            referrer_name TEXT,
            recorded_at TEXT NOT NULL,
            recorded_by TEXT NOT NULL,
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(referrer_patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_growth_patient_acquisition_source
            ON growth_patient_acquisition(source_code,referrer_patient_link_id);
        """
    )
    db.commit()


__all__ = ["ensure_patient_acquisition_storage"]
