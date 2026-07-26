"""Immutable due/completion contracts for governed clinical follow-up tasks."""
from __future__ import annotations

import hashlib
import json
import sqlite3


OUTCOME_TYPES = (
    "OBSERVATION",
    "PATIENT_REPORTED",
    "ENCOUNTER_COMPLETED",
    "PROCEDURE_COMPLETED",
    "LAB_COMPLETED",
    "OTHER",
)


def _hash(payload: dict) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _legacy_contracts(db: sqlite3.Connection) -> None:
    """Fail-safe migration for pre-contract test data.

    Existing specialist data is disposable today, but a copied DB must still start
    safely. Legacy tasks receive a clearly marked, restrictive contract that requires a
    CONFIRMED encounter outcome and never writes a canonical observation automatically.
    """
    rows = db.execute(
        """SELECT task.id, task.source_recommendation_event_id,
                  COALESCE(event.due_at, task.due_date) AS due_at,
                  task.created_at
           FROM followup_tasks task
           LEFT JOIN clinical_task_events event ON event.task_id=task.id
             AND event.supersedes_event_id IS NULL
           WHERE task.source_engine='clinical_v2'
             AND NOT EXISTS (
                 SELECT 1 FROM clinical_task_contracts contract
                 WHERE contract.task_id=task.id
             )"""
    ).fetchall()
    for row in rows:
        due_at = str(row["due_at"] or row["created_at"] or "").strip()
        if len(due_at) == 10:
            due_at += " 00:00:00"
        if not due_at:
            due_at = str(
                db.execute(
                    "SELECT datetime('now','+3 hours','+30 minutes')"
                ).fetchone()[0]
            )
        created_at = str(row["created_at"] or due_at)
        payload = {
            "task_id": int(row["id"]),
            "contract_version": "1.0",
            "contract_origin": "LEGACY_BACKFILL_REVIEW_REQUIRED",
            "due_at": due_at,
            "urgency": "PRIORITY",
            "allowed_outcome_types": ["ENCOUNTER_COMPLETED"],
            "required_fact_keys": [],
            "minimum_verification": "CONFIRMED",
            "canonical_ingestion": "NONE",
            "requires_acknowledgement": True,
            "source_recommendation_event_id": row[
                "source_recommendation_event_id"
            ],
            "created_by": "legacy-task-contract-migration",
            "created_at": created_at,
        }
        db.execute(
            """INSERT INTO clinical_task_contracts
               (task_id, contract_version, contract_origin, due_at, urgency,
                allowed_outcome_types_json, required_fact_keys_json,
                minimum_verification, canonical_ingestion,
                requires_acknowledgement, source_recommendation_event_id,
                created_by, created_at, content_hash)
               VALUES (?, '1.0', 'LEGACY_BACKFILL_REVIEW_REQUIRED', ?,
                       'PRIORITY', ?, '[]', 'CONFIRMED', 'NONE', 1,
                       ?, 'legacy-task-contract-migration', ?, ?)""",
            (
                int(row["id"]),
                due_at,
                json.dumps(["ENCOUNTER_COMPLETED"], separators=(",", ":")),
                row["source_recommendation_event_id"],
                created_at,
                _hash(payload),
            ),
        )


def ensure_clinical_task_contract_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clinical_task_contracts (
            task_id INTEGER PRIMARY KEY,
            contract_version TEXT NOT NULL CHECK (contract_version='1.0'),
            contract_origin TEXT NOT NULL CHECK (contract_origin IN (
                'RULE_RECOMMENDATION','LEGACY_BACKFILL_REVIEW_REQUIRED'
            )),
            due_at TEXT NOT NULL CHECK (datetime(due_at) IS NOT NULL),
            urgency TEXT NOT NULL CHECK (urgency IN (
                'ROUTINE','PRIORITY','URGENT','CRITICAL'
            )),
            allowed_outcome_types_json TEXT NOT NULL
                CHECK (json_valid(allowed_outcome_types_json)
                       AND json_type(allowed_outcome_types_json)='array'
                       AND json_array_length(allowed_outcome_types_json)>0),
            required_fact_keys_json TEXT NOT NULL
                CHECK (json_valid(required_fact_keys_json)
                       AND json_type(required_fact_keys_json)='array'),
            minimum_verification TEXT NOT NULL CHECK (minimum_verification IN (
                'CONFIRMED','PROVISIONAL','UNVERIFIED'
            )),
            canonical_ingestion TEXT NOT NULL CHECK (canonical_ingestion IN (
                'NONE','OPTIONAL','REQUIRED'
            )),
            requires_acknowledgement INTEGER NOT NULL DEFAULT 0
                CHECK (requires_acknowledgement IN (0,1)),
            source_recommendation_event_id INTEGER NOT NULL,
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            FOREIGN KEY(task_id) REFERENCES followup_tasks(id),
            FOREIGN KEY(source_recommendation_event_id)
                REFERENCES clinical_recommendation_events(id)
        );

        CREATE TABLE IF NOT EXISTS clinical_outcome_canonical_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_event_id INTEGER NOT NULL UNIQUE,
            task_id INTEGER NOT NULL,
            record_type TEXT NOT NULL CHECK (record_type IN ('VITAL','LAB')),
            record_id INTEGER NOT NULL CHECK (record_id>0),
            fact_key TEXT NOT NULL CHECK (length(trim(fact_key))>=3),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            FOREIGN KEY(outcome_event_id) REFERENCES clinical_outcome_events(id),
            FOREIGN KEY(task_id) REFERENCES followup_tasks(id)
        );
        CREATE INDEX IF NOT EXISTS idx_outcome_canonical_task
        ON clinical_outcome_canonical_links(task_id, id DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_outcome_source_identity
        ON clinical_outcome_events(source_system, source_record_id)
        WHERE source_record_id IS NOT NULL;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_contract_no_update
        BEFORE UPDATE ON clinical_task_contracts
        BEGIN SELECT RAISE(ABORT, 'clinical task contracts are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_contract_no_delete
        BEFORE DELETE ON clinical_task_contracts
        BEGIN SELECT RAISE(ABORT, 'clinical task contracts cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_clinical_task_contract_scope
        BEFORE INSERT ON clinical_task_contracts
        WHEN NOT EXISTS (
            SELECT 1 FROM followup_tasks task
            JOIN clinical_recommendation_events recommendation
              ON recommendation.id=NEW.source_recommendation_event_id
            WHERE task.id=NEW.task_id
              AND task.source_engine='clinical_v2'
              AND task.source_recommendation_event_id=NEW.source_recommendation_event_id
              AND recommendation.run_id=task.source_run_id
        )
        BEGIN SELECT RAISE(ABORT, 'clinical task contract source mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_outcome_canonical_link_no_update
        BEFORE UPDATE ON clinical_outcome_canonical_links
        BEGIN SELECT RAISE(ABORT, 'canonical outcome links are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_outcome_canonical_link_no_delete
        BEFORE DELETE ON clinical_outcome_canonical_links
        BEGIN SELECT RAISE(ABORT, 'canonical outcome links cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_outcome_canonical_link_scope
        BEFORE INSERT ON clinical_outcome_canonical_links
        WHEN NOT EXISTS (
            SELECT 1 FROM clinical_outcome_events outcome
            WHERE outcome.id=NEW.outcome_event_id AND outcome.task_id=NEW.task_id
        )
        BEGIN SELECT RAISE(ABORT, 'canonical outcome link task mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_outcome_contract
        BEFORE INSERT ON clinical_outcome_events
        WHEN NOT EXISTS (
            SELECT 1 FROM clinical_task_contracts contract
            WHERE contract.task_id=NEW.task_id
              AND EXISTS (
                  SELECT 1 FROM json_each(contract.allowed_outcome_types_json)
                  WHERE value=NEW.outcome_type
              )
              AND (
                  CASE NEW.verification
                      WHEN 'CONFIRMED' THEN 3
                      WHEN 'PROVISIONAL' THEN 2
                      ELSE 1
                  END
              ) >= (
                  CASE contract.minimum_verification
                      WHEN 'CONFIRMED' THEN 3
                      WHEN 'PROVISIONAL' THEN 2
                      ELSE 1
                  END
              )
              AND (
                  json_array_length(contract.required_fact_keys_json)=0
                  OR EXISTS (
                      SELECT 1 FROM json_each(contract.required_fact_keys_json)
                      WHERE value=NEW.fact_key
                  )
              )
        )
        BEGIN SELECT RAISE(ABORT, 'outcome does not satisfy clinical task contract'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_completion_contract
        BEFORE INSERT ON clinical_task_events
        WHEN NEW.event_type='COMPLETED' AND NOT EXISTS (
            SELECT 1
            FROM clinical_task_contracts contract
            JOIN clinical_outcome_events outcome
              ON outcome.id=NEW.outcome_event_id
             AND outcome.task_id=NEW.task_id
            WHERE contract.task_id=NEW.task_id
              AND EXISTS (
                  SELECT 1 FROM json_each(contract.allowed_outcome_types_json)
                  WHERE value=outcome.outcome_type
              )
              AND (
                  CASE outcome.verification
                      WHEN 'CONFIRMED' THEN 3
                      WHEN 'PROVISIONAL' THEN 2
                      ELSE 1
                  END
              ) >= (
                  CASE contract.minimum_verification
                      WHEN 'CONFIRMED' THEN 3
                      WHEN 'PROVISIONAL' THEN 2
                      ELSE 1
                  END
              )
              AND (
                  json_array_length(contract.required_fact_keys_json)=0
                  OR EXISTS (
                      SELECT 1 FROM json_each(contract.required_fact_keys_json)
                      WHERE value=outcome.fact_key
                  )
              )
              AND (
                  contract.canonical_ingestion<>'REQUIRED'
                  OR EXISTS (
                      SELECT 1 FROM clinical_outcome_canonical_links link
                      WHERE link.outcome_event_id=outcome.id
                        AND link.task_id=NEW.task_id
                  )
              )
        )
        BEGIN SELECT RAISE(ABORT, 'completion evidence violates clinical task contract'); END;
        """
    )
    _legacy_contracts(db)
