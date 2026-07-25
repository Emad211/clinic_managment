"""Immutable validation reports and release attestations for Clinical Engine v2."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


_REQUIRED_TRIGGERS = {
    "trg_clinical_validation_reports_no_update",
    "trg_clinical_validation_reports_no_delete",
    "trg_clinical_validation_attestations_no_update",
    "trg_clinical_validation_attestations_no_delete",
    "trg_clinical_validation_attestation_report",
    "trg_clinical_validation_attestation_independent",
}


def ensure_clinical_validation_storage(
    db: sqlite3.Connection | None = None,
) -> None:
    db = db or get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clinical_validation_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            engine_version TEXT NOT NULL CHECK (length(trim(engine_version)) > 0),
            ruleset_code TEXT NOT NULL CHECK (length(trim(ruleset_code)) > 0),
            package_version TEXT NOT NULL CHECK (length(trim(package_version)) > 0),
            package_hash TEXT NOT NULL CHECK (length(package_hash)=64),
            case_bundle_hash TEXT NOT NULL CHECK (length(case_bundle_hash)=64),
            status TEXT NOT NULL CHECK (status IN ('PASS','BLOCKED')),
            case_count INTEGER NOT NULL CHECK (case_count > 0),
            report_json TEXT NOT NULL
                CHECK (json_valid(report_json) AND json_type(report_json)='object'),
            report_hash TEXT NOT NULL UNIQUE CHECK (length(report_hash)=64),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0)
        );

        CREATE INDEX IF NOT EXISTS idx_validation_report_release
        ON clinical_validation_reports(
            engine_version, ruleset_code, package_version, package_hash, id DESC
        );

        CREATE TABLE IF NOT EXISTS clinical_validation_attestations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            validation_report_id INTEGER NOT NULL,
            activation_report_hash TEXT NOT NULL CHECK (length(activation_report_hash)=64),
            role TEXT NOT NULL CHECK (role IN ('CLINICAL','TECHNICAL')),
            reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
            note TEXT NOT NULL CHECK (length(trim(note)) BETWEEN 3 AND 2000),
            report_hash TEXT NOT NULL CHECK (length(report_hash)=64),
            package_hash TEXT NOT NULL CHECK (length(package_hash)=64),
            case_bundle_hash TEXT NOT NULL CHECK (length(case_bundle_hash)=64),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            FOREIGN KEY(validation_report_id) REFERENCES clinical_validation_reports(id)
        );

        CREATE INDEX IF NOT EXISTS idx_validation_attestation_release
        ON clinical_validation_attestations(
            validation_report_id, activation_report_hash, role, id DESC
        );

        CREATE TRIGGER IF NOT EXISTS trg_clinical_validation_reports_no_update
        BEFORE UPDATE ON clinical_validation_reports
        BEGIN
            SELECT RAISE(ABORT, 'clinical validation reports are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_validation_reports_no_delete
        BEFORE DELETE ON clinical_validation_reports
        BEGIN
            SELECT RAISE(ABORT, 'clinical validation reports cannot be deleted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_validation_attestations_no_update
        BEFORE UPDATE ON clinical_validation_attestations
        BEGIN
            SELECT RAISE(ABORT, 'clinical validation attestations are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_validation_attestations_no_delete
        BEFORE DELETE ON clinical_validation_attestations
        BEGIN
            SELECT RAISE(ABORT, 'clinical validation attestations cannot be deleted');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_validation_attestation_report
        BEFORE INSERT ON clinical_validation_attestations
        WHEN NOT EXISTS (
            SELECT 1 FROM clinical_validation_reports report
            WHERE report.id=NEW.validation_report_id
              AND report.status='PASS'
              AND report.report_hash=NEW.report_hash
              AND report.package_hash=NEW.package_hash
              AND report.case_bundle_hash=NEW.case_bundle_hash
        )
        BEGIN
            SELECT RAISE(ABORT, 'attestation requires the exact passing validation report');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_validation_attestation_independent
        BEFORE INSERT ON clinical_validation_attestations
        WHEN EXISTS (
            SELECT 1 FROM clinical_validation_attestations prior
            WHERE prior.validation_report_id=NEW.validation_report_id
              AND prior.activation_report_hash=NEW.activation_report_hash
              AND prior.reviewer=NEW.reviewer
              AND prior.role<>NEW.role
        )
        BEGIN
            SELECT RAISE(ABORT, 'clinical and technical validation reviewers must differ');
        END;
        """
    )
    triggers = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    missing = sorted(_REQUIRED_TRIGGERS - triggers)
    if missing:
        raise RuntimeError(
            "clinical validation guards are incomplete: " + ", ".join(missing)
        )
    db.commit()
