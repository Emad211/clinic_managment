"""Append-only item-level service lineage for completed specialist encounters."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any


SCHEMA_VERSION = "1.0"


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _backfill_legacy_manifests(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """SELECT observation.*
           FROM specialist_financial_observations observation
           WHERE observation.id=(
               SELECT latest.id FROM specialist_financial_observations latest
               WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
               ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
           ) AND NOT EXISTS (
               SELECT 1 FROM specialist_service_snapshot_manifests manifest
               WHERE manifest.accounting_invoice_id=observation.accounting_invoice_id
           )"""
    ).fetchall()
    for row in rows:
        snapshot_id = (
            f"service_legacy_{int(row['accounting_invoice_id'])}_"
            f"{int(row['id'])}_{uuid.uuid4().hex}"
        )
        payload = {
            "snapshot_id": snapshot_id,
            "financial_observation_id": int(row["id"]),
            "accounting_invoice_id": int(row["accounting_invoice_id"]),
            "journey_id": str(row["journey_id"]),
            "encounter_id": str(row["encounter_id"]),
            "patient_link_id": int(row["patient_link_id"]),
            "status": "LEGACY_UNAVAILABLE",
            "expected_line_count": 0,
            "expected_total_amount": 0,
            "evidence_code": "LEGACY_UNAVAILABLE",
            "source_fingerprint": hashlib.sha256(
                (
                    f"legacy-service:{row['accounting_invoice_id']}:"
                    f"{row['id']}:{row['source_fingerprint']}"
                ).encode("utf-8")
            ).hexdigest(),
            "observed_at": str(row["observed_at"]),
            "created_at": str(row["observed_at"]),
            "created_by": "system:a8-migration",
            "supersedes_snapshot_id": None,
        }
        db.execute(
            """INSERT INTO specialist_service_snapshot_manifests
               (snapshot_id,financial_observation_id,accounting_invoice_id,
                journey_id,encounter_id,patient_link_id,status,
                expected_line_count,expected_total_amount,evidence_code,
                source_fingerprint,observed_at,created_at,created_by,
                supersedes_snapshot_id,content_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
            (*payload.values(), _hash(payload)),
        )


def ensure_specialist_service_lineage_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS specialist_service_snapshot_manifests (
            snapshot_id TEXT PRIMARY KEY,
            financial_observation_id INTEGER NOT NULL,
            accounting_invoice_id INTEGER NOT NULL,
            journey_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'COMPLETE','LEGACY_UNAVAILABLE'
            )),
            expected_line_count INTEGER NOT NULL CHECK (expected_line_count>=0),
            expected_total_amount INTEGER NOT NULL CHECK (expected_total_amount>=0),
            evidence_code TEXT NOT NULL CHECK (evidence_code IN (
                'ACCOUNTING_SERVICE_LINES_V1','LEGACY_UNAVAILABLE'
            )),
            source_fingerprint TEXT NOT NULL CHECK (length(source_fingerprint)=64),
            observed_at TEXT NOT NULL CHECK (datetime(observed_at) IS NOT NULL),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            supersedes_snapshot_id TEXT UNIQUE,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            UNIQUE(accounting_invoice_id,financial_observation_id,source_fingerprint),
            CHECK (
                (status='COMPLETE' AND evidence_code='ACCOUNTING_SERVICE_LINES_V1')
                OR
                (status='LEGACY_UNAVAILABLE' AND evidence_code='LEGACY_UNAVAILABLE'
                 AND expected_line_count=0 AND expected_total_amount=0)
            ),
            FOREIGN KEY(financial_observation_id)
                REFERENCES specialist_financial_observations(id),
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(supersedes_snapshot_id)
                REFERENCES specialist_service_snapshot_manifests(snapshot_id)
        );
        CREATE INDEX IF NOT EXISTS idx_service_manifest_invoice
        ON specialist_service_snapshot_manifests(
            accounting_invoice_id,observed_at DESC,created_at DESC
        );
        CREATE INDEX IF NOT EXISTS idx_service_manifest_patient
        ON specialist_service_snapshot_manifests(
            patient_link_id,observed_at DESC
        );

        CREATE TABLE IF NOT EXISTS specialist_service_line_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL,
            accounting_invoice_id INTEGER NOT NULL,
            journey_id TEXT NOT NULL,
            encounter_id TEXT NOT NULL,
            patient_link_id INTEGER NOT NULL,
            item_type TEXT NOT NULL CHECK (item_type IN (
                'VISIT','INJECTION','PROCEDURE'
            )),
            accounting_item_id INTEGER NOT NULL CHECK (accounting_item_id>0),
            line_sequence INTEGER NOT NULL CHECK (line_sequence>0),
            description TEXT NOT NULL CHECK (length(trim(description))>0),
            performed_at TEXT CHECK (
                performed_at IS NULL OR datetime(performed_at) IS NOT NULL
            ),
            work_date TEXT CHECK (work_date IS NULL OR date(work_date) IS NOT NULL),
            quantity REAL CHECK (quantity IS NULL OR quantity>0),
            unit_amount INTEGER CHECK (unit_amount IS NULL OR unit_amount>=0),
            total_amount INTEGER NOT NULL CHECK (total_amount>=0),
            performer_type TEXT,
            performer_accounting_id INTEGER,
            performer_name TEXT,
            source_status TEXT,
            source_fingerprint TEXT NOT NULL CHECK (length(source_fingerprint)=64),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            UNIQUE(snapshot_id,line_sequence),
            UNIQUE(snapshot_id,item_type,accounting_item_id),
            FOREIGN KEY(snapshot_id)
                REFERENCES specialist_service_snapshot_manifests(snapshot_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY(journey_id) REFERENCES care_journeys(journey_id),
            FOREIGN KEY(encounter_id) REFERENCES care_encounters(encounter_id),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id)
        );
        CREATE INDEX IF NOT EXISTS idx_service_line_patient
        ON specialist_service_line_observations(
            patient_link_id,performed_at DESC,id DESC
        );

        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_no_update
        BEFORE UPDATE ON specialist_service_snapshot_manifests
        BEGIN SELECT RAISE(ABORT,'service manifests are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_no_delete
        BEFORE DELETE ON specialist_service_snapshot_manifests
        BEGIN SELECT RAISE(ABORT,'service manifests cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_service_line_no_update
        BEFORE UPDATE ON specialist_service_line_observations
        BEGIN SELECT RAISE(ABORT,'service lines are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_service_line_no_delete
        BEFORE DELETE ON specialist_service_line_observations
        BEGIN SELECT RAISE(ABORT,'service lines cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_first
        BEFORE INSERT ON specialist_service_snapshot_manifests
        WHEN NOT EXISTS (
            SELECT 1 FROM specialist_service_snapshot_manifests prior
            WHERE prior.accounting_invoice_id=NEW.accounting_invoice_id
        ) AND NEW.supersedes_snapshot_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT,'first service manifest cannot supersede'); END;

        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_linear
        BEFORE INSERT ON specialist_service_snapshot_manifests
        WHEN EXISTS (
            SELECT 1 FROM specialist_service_snapshot_manifests prior
            WHERE prior.accounting_invoice_id=NEW.accounting_invoice_id
        ) AND NEW.supersedes_snapshot_id IS NOT (
            SELECT head.snapshot_id
            FROM specialist_service_snapshot_manifests head
            WHERE head.accounting_invoice_id=NEW.accounting_invoice_id
            ORDER BY head.observed_at DESC,head.created_at DESC,head.rowid DESC
            LIMIT 1
        )
        BEGIN SELECT RAISE(ABORT,'service manifest must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_scope
        BEFORE INSERT ON specialist_service_snapshot_manifests
        WHEN NOT EXISTS (
            SELECT 1 FROM specialist_financial_observations observation
            WHERE observation.id=NEW.financial_observation_id
              AND observation.accounting_invoice_id=NEW.accounting_invoice_id
              AND observation.journey_id=NEW.journey_id
              AND observation.encounter_id=NEW.encounter_id
              AND observation.patient_link_id=NEW.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT,'service manifest financial scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_complete_count
        BEFORE INSERT ON specialist_service_snapshot_manifests
        WHEN NEW.status='COMPLETE' AND (
            NEW.expected_line_count<>(
                SELECT observation.billable_item_count
                FROM specialist_financial_observations observation
                WHERE observation.id=NEW.financial_observation_id
            ) OR
            NEW.expected_line_count<>(
                SELECT COUNT(*) FROM specialist_service_line_observations line
                WHERE line.snapshot_id=NEW.snapshot_id
            )
        )
        BEGIN SELECT RAISE(ABORT,'complete service line count mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_complete_total
        BEFORE INSERT ON specialist_service_snapshot_manifests
        WHEN NEW.status='COMPLETE' AND (
            NEW.expected_total_amount<>(
                SELECT observation.billed_amount
                FROM specialist_financial_observations observation
                WHERE observation.id=NEW.financial_observation_id
            ) OR
            NEW.expected_total_amount<>COALESCE((
                SELECT SUM(line.total_amount)
                FROM specialist_service_line_observations line
                WHERE line.snapshot_id=NEW.snapshot_id
            ),0)
        )
        BEGIN SELECT RAISE(ABORT,'complete service line total mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_line_scope
        BEFORE INSERT ON specialist_service_snapshot_manifests
        WHEN NEW.status='COMPLETE' AND EXISTS (
            SELECT 1 FROM specialist_service_line_observations line
            WHERE line.snapshot_id=NEW.snapshot_id
              AND (
                  line.accounting_invoice_id<>NEW.accounting_invoice_id OR
                  line.journey_id<>NEW.journey_id OR
                  line.encounter_id<>NEW.encounter_id OR
                  line.patient_link_id<>NEW.patient_link_id
              )
        )
        BEGIN SELECT RAISE(ABORT,'service line identity mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_service_manifest_legacy_empty
        BEFORE INSERT ON specialist_service_snapshot_manifests
        WHEN NEW.status='LEGACY_UNAVAILABLE' AND EXISTS (
            SELECT 1 FROM specialist_service_line_observations line
            WHERE line.snapshot_id=NEW.snapshot_id
        )
        BEGIN SELECT RAISE(ABORT,'legacy service manifest cannot contain lines'); END;
        """
    )
    _backfill_legacy_manifests(db)
    db.commit()


__all__ = ["SCHEMA_VERSION", "ensure_specialist_service_lineage_storage"]
