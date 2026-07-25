"""Copied-existing-database migration contract for reconciliation storage."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import sys


SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

from src.adapters.sqlite.clinical_engine_runtime_schema import ensure_runtime_schema


def _legacy_connection(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE patient_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            national_id TEXT UNIQUE,
            full_name TEXT,
            birthdate TEXT,
            gender TEXT
        );
        CREATE TABLE conditions (
            id INTEGER PRIMARY KEY,
            code TEXT,
            name TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE patient_conditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            condition_id INTEGER NOT NULL,
            onset_date TEXT,
            diagnosed_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE patient_medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            drug_name TEXT NOT NULL,
            dose TEXT,
            schedule TEXT,
            start_date TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE medication_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            medication_id INTEGER,
            drug_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            dose TEXT,
            event_date TEXT,
            created_at TEXT
        );
        CREATE TABLE allergies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            substance TEXT NOT NULL,
            reaction TEXT,
            severity TEXT,
            created_at TEXT
        );
        CREATE TABLE patient_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            flag_key TEXT,
            value TEXT
        );
        CREATE TABLE vital_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            type TEXT,
            value REAL
        );
        CREATE TABLE lab_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            test_key TEXT,
            value REAL
        );
        CREATE TABLE flag_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flag_key TEXT,
            flag_type TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE drug_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generic_fa TEXT NOT NULL,
            drug_class_key TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT
        );
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT
        );

        INSERT INTO patient_links
            (national_id, full_name, birthdate, gender)
        VALUES ('LEGACY001', 'Legacy Patient', '1980-01-01', 'female');
        INSERT INTO conditions(id, code, name) VALUES (1, 'diabetes', 'دیابت');
        INSERT INTO patient_conditions
            (patient_link_id, condition_id, onset_date, diagnosed_at)
        VALUES (1, 1, '2020-01-01', '2020-01-01');
        INSERT INTO drug_catalog
            (id, generic_fa, drug_class_key, is_active)
        VALUES (10, 'متفورمین', 'metformin', 1);
        INSERT INTO patient_medications
            (patient_link_id, drug_name, dose, start_date)
        VALUES (1, 'متفورمین', '500 mg', '2020-01-01');
        INSERT INTO allergies
            (patient_link_id, substance, reaction, created_at)
        VALUES (1, 'Penicillin', 'rash', '2021-01-01 09:00:00');
        """
    )
    db.commit()
    return db


def _columns(db, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }


def test_existing_rows_survive_additive_idempotent_migration(tmp_path):
    db = _legacy_connection(tmp_path / "legacy.db")
    try:
        ensure_runtime_schema(db)
        ensure_runtime_schema(db)

        assert "clinical_data_revision" in _columns(db, "patient_links")
        assert "resolved_at" in _columns(db, "patient_conditions")
        assert {
            "end_date",
            "drug_class",
            "drug_catalog_id",
        } <= _columns(db, "patient_medications")
        assert {
            "is_active",
            "resolved_at",
            "allergy_concept_id",
            "source_system",
            "source_record_id",
            "source_assertion",
            "verification",
        } <= _columns(db, "allergies")
        assert {
            "source_system",
            "source_record_id",
            "source_assertion",
            "verification",
        } <= _columns(db, "patient_conditions")
        assert {
            "source_system",
            "source_record_id",
            "source_assertion",
            "verification",
        } <= _columns(db, "patient_medications")
        assert db.execute(
            """SELECT COUNT(*) AS count FROM sqlite_master
               WHERE type='table' AND name='clinical_reconciliation_events'"""
        ).fetchone()["count"] == 1
        assert db.execute(
            """SELECT COUNT(*) AS count FROM sqlite_master
               WHERE type='table' AND name='clinical_data_conflict_events'"""
        ).fetchone()["count"] == 1
        assert db.execute(
            """SELECT COUNT(*) AS count FROM sqlite_master
               WHERE type='table' AND name='allergy_catalog'"""
        ).fetchone()["count"] == 1

        patient = db.execute(
            "SELECT * FROM patient_links WHERE national_id='LEGACY001'"
        ).fetchone()
        condition = db.execute(
            "SELECT * FROM patient_conditions WHERE patient_link_id=1"
        ).fetchone()
        medication = db.execute(
            "SELECT * FROM patient_medications WHERE patient_link_id=1"
        ).fetchone()
        allergy = db.execute(
            "SELECT * FROM allergies WHERE patient_link_id=1"
        ).fetchone()
        assert patient["full_name"] == "Legacy Patient"
        assert condition["condition_id"] == 1
        assert medication["drug_name"] == "متفورمین"
        assert allergy["substance"] == "Penicillin"
        assert allergy["is_active"] == 1
        assert allergy["source_system"] == "clinic"
        assert allergy["source_assertion"] == "PRESENT"
        assert allergy["verification"] == "CONFIRMED"
        allergy_concept = db.execute(
            """SELECT catalog.concept_key
               FROM allergy_catalog catalog
               WHERE catalog.id=?""",
            (allergy["allergy_concept_id"],),
        ).fetchone()
        assert allergy_concept["concept_key"] == "penicillin"

        # A later class assignment resolves the legacy medication to the single
        # matching catalog concept and advances the patient's clinical revision.
        before = int(patient["clinical_data_revision"] or 0)
        db.execute(
            "UPDATE patient_medications SET drug_class='metformin' WHERE id=?",
            (medication["id"],),
        )
        db.commit()
        resolved = db.execute(
            "SELECT drug_catalog_id FROM patient_medications WHERE id=?",
            (medication["id"],),
        ).fetchone()
        after = int(db.execute(
            "SELECT clinical_data_revision FROM patient_links WHERE id=1"
        ).fetchone()["clinical_data_revision"])
        assert resolved["drug_catalog_id"] == 10
        assert after > before

        triggers = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert {
            "trg_clinical_revision_patient_conditions_insert",
            "trg_clinical_revision_reconciliation_insert",
            "trg_reconciliation_no_update",
            "trg_medication_catalog_validate_insert",
            "trg_data_conflict_no_update",
            "trg_data_conflict_no_delete",
            "trg_allergy_concept_validate_insert",
        } <= triggers
    finally:
        db.close()
