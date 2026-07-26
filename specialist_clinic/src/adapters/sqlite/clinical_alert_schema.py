"""Append-only operational lifecycle for audited red-flag and safety alerts."""
from __future__ import annotations

import sqlite3


def ensure_clinical_alert_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clinical_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            source_run_id TEXT NOT NULL,
            source_recommendation_event_id INTEGER NOT NULL UNIQUE,
            rule_code TEXT NOT NULL CHECK (length(trim(rule_code))>0),
            action_type TEXT NOT NULL CHECK (action_type IN ('redflag','safety_alert')),
            severity TEXT NOT NULL CHECK (severity IN ('WARN','URGENT','CRITICAL')),
            title_fa TEXT NOT NULL CHECK (length(trim(title_fa))>0),
            message_fa TEXT NOT NULL CHECK (length(trim(message_fa))>0),
            acknowledgement_due_at TEXT NOT NULL
                CHECK (datetime(acknowledgement_due_at) IS NOT NULL),
            created_at TEXT NOT NULL CHECK (datetime(created_at) IS NOT NULL),
            created_by TEXT NOT NULL CHECK (length(trim(created_by))>0),
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(source_run_id) REFERENCES clinical_engine_runs(run_id),
            FOREIGN KEY(source_recommendation_event_id)
                REFERENCES clinical_recommendation_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_clinical_alert_patient
        ON clinical_alerts(patient_link_id, acknowledgement_due_at, id DESC);

        CREATE TABLE IF NOT EXISTS clinical_alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'CREATED','ACKNOWLEDGED','ESCALATED','RESOLVED','ENTERED_IN_ERROR'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'OPEN','ACKNOWLEDGED','ESCALATED','RESOLVED','ENTERED_IN_ERROR'
            )),
            assigned_to TEXT,
            note TEXT,
            decision_event_id INTEGER,
            effective_at TEXT NOT NULL CHECK (datetime(effective_at) IS NOT NULL),
            recorded_at TEXT NOT NULL CHECK (datetime(recorded_at) IS NOT NULL),
            actor_user_id INTEGER,
            actor_username TEXT NOT NULL CHECK (length(trim(actor_username))>0),
            supersedes_event_id INTEGER,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            CHECK (datetime(effective_at) <= datetime(recorded_at)),
            CHECK (note IS NULL OR length(note)<=2000),
            FOREIGN KEY(alert_id) REFERENCES clinical_alerts(id),
            FOREIGN KEY(decision_event_id) REFERENCES clinical_decision_events(id),
            FOREIGN KEY(actor_user_id) REFERENCES users(id),
            FOREIGN KEY(supersedes_event_id) REFERENCES clinical_alert_events(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_alert_one_root
        ON clinical_alert_events(alert_id) WHERE supersedes_event_id IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_alert_one_child
        ON clinical_alert_events(supersedes_event_id)
        WHERE supersedes_event_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_clinical_alert_head
        ON clinical_alert_events(alert_id, recorded_at DESC, id DESC);

        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_no_update
        BEFORE UPDATE ON clinical_alerts
        BEGIN SELECT RAISE(ABORT, 'clinical alerts are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_no_delete
        BEFORE DELETE ON clinical_alerts
        BEGIN SELECT RAISE(ABORT, 'clinical alerts cannot be deleted'); END;
        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_event_no_update
        BEFORE UPDATE ON clinical_alert_events
        BEGIN SELECT RAISE(ABORT, 'clinical alert events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_event_no_delete
        BEFORE DELETE ON clinical_alert_events
        BEGIN SELECT RAISE(ABORT, 'clinical alert events cannot be deleted'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_source_scope
        BEFORE INSERT ON clinical_alerts
        WHEN NOT EXISTS (
            SELECT 1
            FROM clinical_recommendation_events recommendation
            JOIN clinical_engine_runs run ON run.run_id=recommendation.run_id
            WHERE recommendation.id=NEW.source_recommendation_event_id
              AND recommendation.event_type='CREATED'
              AND recommendation.run_id=NEW.source_run_id
              AND recommendation.action_type=NEW.action_type
              AND run.patient_link_id=NEW.patient_link_id
              AND run.run_status IN ('COMPLETED','COMPLETED_WITH_ERRORS')
        )
        BEGIN SELECT RAISE(ABORT, 'clinical alert source mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_first_event
        BEFORE INSERT ON clinical_alert_events
        WHEN NOT EXISTS (
            SELECT 1 FROM clinical_alert_events prior
            WHERE prior.alert_id=NEW.alert_id
        ) AND (
            NEW.supersedes_event_id IS NOT NULL
            OR NEW.event_type<>'CREATED' OR NEW.status<>'OPEN'
        )
        BEGIN SELECT RAISE(ABORT, 'first alert event must be CREATED/OPEN'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_next_event
        BEFORE INSERT ON clinical_alert_events
        WHEN EXISTS (
            SELECT 1 FROM clinical_alert_events prior
            WHERE prior.alert_id=NEW.alert_id
        ) AND (
            NEW.supersedes_event_id IS NULL
            OR NEW.supersedes_event_id<>(
                SELECT head.id FROM clinical_alert_events head
                WHERE head.alert_id=NEW.alert_id
                  AND NOT EXISTS (
                      SELECT 1 FROM clinical_alert_events child
                      WHERE child.supersedes_event_id=head.id
                  )
                ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
            )
        )
        BEGIN SELECT RAISE(ABORT, 'alert event must supersede current head'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_recorded_order
        BEFORE INSERT ON clinical_alert_events
        WHEN NEW.supersedes_event_id IS NOT NULL AND datetime(NEW.recorded_at) < datetime((
            SELECT prior.recorded_at FROM clinical_alert_events prior
            WHERE prior.id=NEW.supersedes_event_id
        ))
        BEGIN SELECT RAISE(ABORT, 'alert recorded_at cannot move backwards'); END;

        CREATE TRIGGER IF NOT EXISTS trg_clinical_alert_transition
        BEFORE INSERT ON clinical_alert_events
        WHEN (
            (NEW.event_type='CREATED' AND NEW.status<>'OPEN')
            OR (NEW.event_type='ACKNOWLEDGED' AND (
                NEW.status<>'ACKNOWLEDGED'
                OR length(trim(COALESCE(NEW.assigned_to,'')))=0
                OR (SELECT status FROM clinical_alert_events
                    WHERE id=NEW.supersedes_event_id) NOT IN ('OPEN','ESCALATED')
            ))
            OR (NEW.event_type='ESCALATED' AND (
                NEW.status<>'ESCALATED'
                OR (SELECT status FROM clinical_alert_events
                    WHERE id=NEW.supersedes_event_id) NOT IN ('OPEN','ACKNOWLEDGED')
            ))
            OR (NEW.event_type='RESOLVED' AND (
                NEW.status<>'RESOLVED'
                OR NEW.decision_event_id IS NULL
                OR length(trim(COALESCE(NEW.note,'')))=0
                OR (SELECT status FROM clinical_alert_events
                    WHERE id=NEW.supersedes_event_id) NOT IN ('ACKNOWLEDGED','ESCALATED')
                OR NOT EXISTS (
                    SELECT 1
                    FROM clinical_decision_events decision
                    JOIN clinical_alerts alert
                      ON alert.source_recommendation_event_id=decision.recommendation_event_id
                    WHERE alert.id=NEW.alert_id
                      AND decision.id=NEW.decision_event_id
                )
            ))
            OR (NEW.event_type='ENTERED_IN_ERROR' AND (
                NEW.status<>'ENTERED_IN_ERROR'
                OR (SELECT status FROM clinical_alert_events
                    WHERE id=NEW.supersedes_event_id) IN ('RESOLVED','ENTERED_IN_ERROR')
            ))
            OR (NEW.supersedes_event_id IS NOT NULL AND
                (SELECT status FROM clinical_alert_events
                 WHERE id=NEW.supersedes_event_id) IN ('RESOLVED','ENTERED_IN_ERROR'))
        )
        BEGIN SELECT RAISE(ABORT, 'invalid clinical alert lifecycle'); END;
        """
    )
    db.commit()
