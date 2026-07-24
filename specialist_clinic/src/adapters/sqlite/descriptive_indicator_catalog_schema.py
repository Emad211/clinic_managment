"""Canonical descriptive-only storage for measurement catalog metadata.

The historical ``clinical_indicators`` table once carried executable thresholds,
treatment targets and risk weights.  Those fields are unsafe as a parallel clinical
engine.  This migration rebuilds copied databases onto the same descriptive schema as
a fresh install while preserving labels, units, applicability and display ordering.
"""
from __future__ import annotations

import sqlite3


_COLUMNS = (
    "id",
    "key",
    "label",
    "unit",
    "category",
    "conditions",
    "is_vital",
    "display_order",
    "is_active",
    "notes",
)
_REQUIRED_SOURCE = {"id", "key", "label"}


def _columns(db: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _exists(db: sqlite3.Connection, table: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def ensure_descriptive_indicator_catalog(db: sqlite3.Connection) -> bool:
    """Rebuild legacy indicator storage and return whether the schema changed.

    The migration is fail-loud and atomic. A malformed legacy table is left untouched
    instead of silently dropping metadata or guessing clinical semantics.
    """
    if not _exists(db, "clinical_indicators"):
        return False
    current = _columns(db, "clinical_indicators")
    if current == _COLUMNS:
        return False
    missing = sorted(_REQUIRED_SOURCE - set(current))
    if missing:
        raise RuntimeError(
            "clinical indicator catalog cannot be migrated; missing columns: "
            + ", ".join(missing)
        )
    if db.in_transaction:
        raise RuntimeError(
            "clinical indicator catalog migration requires an idle connection"
        )

    def source(name: str, fallback: str) -> str:
        return name if name in current else fallback

    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("DROP TABLE IF EXISTS clinical_indicators_descriptive")
        db.execute(
            """CREATE TABLE clinical_indicators_descriptive (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   key TEXT UNIQUE NOT NULL,
                   label TEXT NOT NULL,
                   unit TEXT,
                   category TEXT NOT NULL DEFAULT 'other',
                   conditions TEXT NOT NULL DEFAULT 'all',
                   is_vital INTEGER NOT NULL DEFAULT 1,
                   display_order INTEGER NOT NULL DEFAULT 100,
                   is_active INTEGER NOT NULL DEFAULT 1,
                   notes TEXT
               )"""
        )
        db.execute(
            f"""INSERT INTO clinical_indicators_descriptive
                   (id, key, label, unit, category, conditions, is_vital,
                    display_order, is_active, notes)
               SELECT id, key, label,
                      {source('unit', 'NULL')},
                      COALESCE({source('category', "'other'")}, 'other'),
                      COALESCE({source('conditions', "'all'")}, 'all'),
                      COALESCE({source('is_vital', '1')}, 1),
                      COALESCE({source('display_order', '100')}, 100),
                      COALESCE({source('is_active', '1')}, 1),
                      {source('notes', 'NULL')}
               FROM clinical_indicators"""
        )
        source_count = int(
            db.execute(
                "SELECT COUNT(*) FROM clinical_indicators"
            ).fetchone()[0]
        )
        migrated_count = int(
            db.execute(
                "SELECT COUNT(*) FROM clinical_indicators_descriptive"
            ).fetchone()[0]
        )
        if source_count != migrated_count:
            raise RuntimeError(
                "clinical indicator catalog migration lost rows"
            )
        db.execute("DROP TABLE clinical_indicators")
        db.execute(
            "ALTER TABLE clinical_indicators_descriptive "
            "RENAME TO clinical_indicators"
        )
        if _columns(db, "clinical_indicators") != _COLUMNS:
            raise RuntimeError(
                "clinical indicator catalog migration produced the wrong schema"
            )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
