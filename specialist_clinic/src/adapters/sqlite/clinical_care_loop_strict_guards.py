"""Upgrade null-sensitive care-loop guards on existing and fresh databases."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.clinical_care_loop_schema import (
    ensure_clinical_care_loop_storage,
)
from src.adapters.sqlite.core import get_db


def ensure_strict_clinical_care_loop_guards(
    db: sqlite3.Connection | None = None,
) -> None:
    db = db or get_db()
    ensure_clinical_care_loop_storage(db)
    db.executescript(
        """
        DROP TRIGGER IF EXISTS trg_clinical_task_events_transition;
        CREATE TRIGGER trg_clinical_task_events_transition
        BEFORE INSERT ON clinical_task_events
        WHEN (
            (NEW.event_type='CREATED' AND NEW.status<>'OPEN')
            OR (NEW.event_type='ASSIGNED' AND (
                NEW.status<>'ASSIGNED'
                OR NEW.assigned_to IS NULL
                OR length(trim(NEW.assigned_to))=0
            ))
            OR (NEW.event_type='SCHEDULED' AND (
                NEW.status<>'SCHEDULED' OR NEW.appointment_id IS NULL
            ))
            OR (NEW.event_type='STARTED' AND NEW.status<>'IN_PROGRESS')
            OR (NEW.event_type='DEFERRED' AND (
                NEW.status<>'DEFERRED' OR NEW.due_at IS NULL
            ))
            OR (NEW.event_type='COMPLETED' AND (
                NEW.status<>'COMPLETED'
                OR NEW.outcome_event_id IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM clinical_outcome_events outcome
                    WHERE outcome.id=NEW.outcome_event_id
                      AND outcome.task_id=NEW.task_id
                )
            ))
            OR (NEW.event_type='NOT_DONE' AND (
                NEW.status<>'NOT_DONE'
                OR NEW.disposition_code IS NULL
                OR NEW.disposition_code NOT IN (
                    'PATIENT_DECLINED','UNREACHABLE','CLINICIAN_CANCELLED',
                    'DUPLICATE','NO_LONGER_NEEDED','OTHER'
                )
            ))
            OR (NEW.event_type='ENTERED_IN_ERROR'
                AND NEW.status<>'ENTERED_IN_ERROR')
            OR (
                NEW.supersedes_event_id IS NOT NULL
                AND (SELECT prior.status FROM clinical_task_events prior
                     WHERE prior.id=NEW.supersedes_event_id)
                    IN ('COMPLETED','NOT_DONE','ENTERED_IN_ERROR')
                AND NEW.event_type<>'ENTERED_IN_ERROR'
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid clinical task lifecycle transition');
        END;
        """
    )
    db.commit()
