"""Additive appointment waitlist and slot-fill storage."""
from __future__ import annotations

import sqlite3


def ensure_growth_waitlist_storage(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS growth_waitlist_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_link_id INTEGER NOT NULL,
            appt_type TEXT NOT NULL DEFAULT 'visit',
            date_from TEXT,
            date_to TEXT,
            time_window TEXT NOT NULL DEFAULT 'ANY'
                CHECK(time_window IN ('ANY','MORNING','AFTERNOON','EVENING')),
            auto_fill INTEGER NOT NULL DEFAULT 0 CHECK(auto_fill IN (0,1)),
            priority INTEGER NOT NULL DEFAULT 100,
            source_code TEXT NOT NULL DEFAULT 'STAFF_REQUEST',
            status TEXT NOT NULL DEFAULT 'WAITING'
                CHECK(status IN ('WAITING','OFFERED','BOOKED','CANCELLED')),
            notes TEXT,
            offered_slot_at TEXT,
            booked_appointment_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            FOREIGN KEY(patient_link_id) REFERENCES patient_links(id),
            FOREIGN KEY(booked_appointment_id) REFERENCES appointments(id)
        );

        CREATE INDEX IF NOT EXISTS idx_growth_waitlist_match
            ON growth_waitlist_entries(status,appt_type,date_from,date_to,
                                       time_window,priority,id);
        CREATE INDEX IF NOT EXISTS idx_growth_waitlist_patient
            ON growth_waitlist_entries(patient_link_id,status,id);

        CREATE TABLE IF NOT EXISTS growth_slot_fill_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cancelled_appointment_id INTEGER NOT NULL UNIQUE,
            waitlist_entry_id INTEGER NOT NULL,
            replacement_appointment_id INTEGER,
            mode TEXT NOT NULL CHECK(mode IN ('AUTO_BOOKED','OFFER_CREATED')),
            slot_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            FOREIGN KEY(cancelled_appointment_id) REFERENCES appointments(id),
            FOREIGN KEY(waitlist_entry_id) REFERENCES growth_waitlist_entries(id),
            FOREIGN KEY(replacement_appointment_id) REFERENCES appointments(id)
        );

        CREATE INDEX IF NOT EXISTS idx_growth_slot_fill_waitlist
            ON growth_slot_fill_events(waitlist_entry_id,created_at DESC,id DESC);
        """
    )
    db.commit()


__all__ = ["ensure_growth_waitlist_storage"]
