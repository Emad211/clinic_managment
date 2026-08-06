"""Additive storage for prospect/lead lifecycle tracking.

Leads are deliberately separate from enrolled patients. A patient_link_id is populated
only after an explicit conversion action.
"""
from __future__ import annotations

import sqlite3


LEAD_STATUSES = (
    "NEW",
    "CONTACTED",
    "APPOINTMENT_BOOKED",
    "ATTENDED",
    "CONVERTED",
    "LOST",
)


def ensure_lead_pipeline_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS growth_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            national_id TEXT,
            source_code TEXT NOT NULL,
            source_detail TEXT,
            referrer_name TEXT,
            interest_code TEXT,
            owner_username TEXT,
            status TEXT NOT NULL DEFAULT 'NEW'
                CHECK(status IN (
                    'NEW','CONTACTED','APPOINTMENT_BOOKED',
                    'ATTENDED','CONVERTED','LOST'
                )),
            next_action_at TEXT,
            appointment_at TEXT,
            lost_reason TEXT,
            notes TEXT,
            patient_link_id INTEGER,
            appointment_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            converted_at TEXT,
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(appointment_id) REFERENCES appointments(id)
        );

        CREATE INDEX IF NOT EXISTS idx_growth_leads_status_due
            ON growth_leads(status, next_action_at, id);
        CREATE INDEX IF NOT EXISTS idx_growth_leads_phone
            ON growth_leads(phone_number, status);
        CREATE INDEX IF NOT EXISTS idx_growth_leads_owner
            ON growth_leads(owner_username, status, next_action_at);
        CREATE INDEX IF NOT EXISTS idx_growth_leads_source
            ON growth_leads(source_code, status);

        CREATE TABLE IF NOT EXISTS growth_lead_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            occurred_at TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            note TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(lead_id) REFERENCES growth_leads(id)
        );

        CREATE INDEX IF NOT EXISTS idx_growth_lead_events_lead
            ON growth_lead_events(lead_id, occurred_at DESC, id DESC);
        """
    )
    db.commit()


__all__ = ["LEAD_STATUSES", "ensure_lead_pipeline_storage"]
