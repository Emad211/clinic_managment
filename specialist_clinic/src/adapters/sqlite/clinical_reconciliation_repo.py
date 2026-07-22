"""Persistence boundary for reviewed clinical collections."""
from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now, parse_datetime
from src.domain.clinical_engine.reconciliation import (
    COLLECTION_KEYS,
    canonical_collection_items,
    collection_content_hash,
    project_collection,
)


_SOURCE_SQL = {
    "conditions": """SELECT pc.*, c.code AS condition_code, c.name AS condition_name
                       FROM patient_conditions pc
                       JOIN conditions c ON c.id=pc.condition_id
                       WHERE pc.patient_link_id=? ORDER BY pc.id""",
    "medications": """SELECT * FROM patient_medications
                         WHERE patient_link_id=? ORDER BY id""",
    "allergies": """SELECT * FROM allergies
                      WHERE patient_link_id=? ORDER BY id""",
}


class ClinicalReconciliationRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def _as_of(value: datetime | str | None) -> datetime:
        parsed = parse_datetime(value)
        if parsed is None:
            return iran_now()
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed

    @staticmethod
    def _source_rows_db(
        db: sqlite3.Connection, patient_link_id: int, collection_key: str
    ) -> list[dict[str, Any]]:
        if collection_key not in COLLECTION_KEYS:
            raise ValueError(f"unsupported reconciliation collection: {collection_key}")
        return [
            dict(row)
            for row in db.execute(
                _SOURCE_SQL[collection_key], (patient_link_id,)
            ).fetchall()
        ]

    @staticmethod
    def _medication_events_db(
        db: sqlite3.Connection, patient_link_id: int
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in db.execute(
                """SELECT * FROM medication_events
                   WHERE patient_link_id=? ORDER BY event_date, id""",
                (patient_link_id,),
            ).fetchall()
        ]

    @staticmethod
    def _reconciliation_events_db(
        db: sqlite3.Connection,
        patient_link_id: int,
        collection_key: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """SELECT * FROM clinical_reconciliation_events
                 WHERE patient_link_id=?"""
        params: list[Any] = [patient_link_id]
        if collection_key is not None:
            sql += " AND collection_key=?"
            params.append(collection_key)
        sql += " ORDER BY reconciled_at, id"
        return [dict(row) for row in db.execute(sql, params).fetchall()]

    def source_bundle(self, patient_link_id: int) -> dict[str, Any]:
        db = self._db()
        return {
            key: self._source_rows_db(db, patient_link_id, key)
            for key in COLLECTION_KEYS
        } | {
            "medication_events": self._medication_events_db(db, patient_link_id),
            "reconciliations": self._reconciliation_events_db(db, patient_link_id),
        }

    def projection(
        self,
        patient_link_id: int,
        collection_key: str,
        *,
        as_of_at: datetime | str | None = None,
    ):
        db = self._db()
        as_of = self._as_of(as_of_at)
        rows = self._source_rows_db(db, patient_link_id, collection_key)
        medication_events = (
            self._medication_events_db(db, patient_link_id)
            if collection_key == "medications"
            else []
        )
        events = self._reconciliation_events_db(
            db, patient_link_id, collection_key
        )
        return project_collection(
            collection_key,
            rows,
            events,
            as_of_at=as_of,
            medication_events=medication_events,
        )

    def patient_projections(
        self,
        patient_link_id: int,
        *,
        as_of_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        return {
            key: self.projection(
                patient_link_id, key, as_of_at=as_of_at
            )
            for key in COLLECTION_KEYS
        }

    @classmethod
    def record_in_transaction(
        cls,
        db: sqlite3.Connection,
        *,
        patient_link_id: int,
        collection_key: str,
        completeness: str,
        actor_username: str,
        actor_user_id: int | None = None,
        source: str = "clinician",
        patient_confirmed: bool = False,
        reconciled_at: datetime | str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if collection_key not in COLLECTION_KEYS:
            raise ValueError("collection_key is not reconcilable")
        if completeness not in {"complete", "partial"}:
            raise ValueError("completeness must be complete or partial")
        if source not in {"clinician", "patient", "caregiver", "imported", "system"}:
            raise ValueError("invalid reconciliation source")
        actor = (actor_username or "").strip()
        if not actor:
            raise ValueError("actor_username is required")
        if completeness == "partial" and not (note or "").strip():
            raise ValueError("partial reconciliation requires a note")

        patient = db.execute(
            "SELECT id FROM patient_links WHERE id=?", (patient_link_id,)
        ).fetchone()
        if not patient:
            raise LookupError(f"patient_link_id {patient_link_id} was not found")

        as_of = cls._as_of(reconciled_at)
        rows = cls._source_rows_db(db, patient_link_id, collection_key)
        medication_events = (
            cls._medication_events_db(db, patient_link_id)
            if collection_key == "medications"
            else []
        )
        items = canonical_collection_items(
            collection_key,
            rows,
            as_of_at=as_of,
            medication_events=medication_events,
        )
        content_hash = collection_content_hash(
            collection_key,
            rows,
            as_of_at=as_of,
            medication_events=medication_events,
        )
        prior = db.execute(
            """SELECT id FROM clinical_reconciliation_events
               WHERE patient_link_id=? AND collection_key=?
                 AND reconciled_at<=?
               ORDER BY reconciled_at DESC, id DESC LIMIT 1""",
            (
                patient_link_id,
                collection_key,
                as_of.isoformat(sep=" ", timespec="seconds"),
            ),
        ).fetchone()
        cursor = db.execute(
            """INSERT INTO clinical_reconciliation_events
               (patient_link_id, collection_key, completeness, item_count,
                content_hash, source, patient_confirmed, actor_user_id,
                actor_username, reconciled_at, note, supersedes_event_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                patient_link_id,
                collection_key,
                completeness,
                len(items),
                content_hash,
                source,
                int(bool(patient_confirmed)),
                actor_user_id,
                actor,
                as_of.isoformat(sep=" ", timespec="seconds"),
                (note or "").strip() or None,
                int(prior["id"]) if prior else None,
            ),
        )
        row = db.execute(
            "SELECT * FROM clinical_reconciliation_events WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)

    def record(
        self,
        *,
        patient_link_id: int,
        collection_key: str,
        completeness: str,
        actor_username: str,
        actor_user_id: int | None = None,
        source: str = "clinician",
        patient_confirmed: bool = False,
        reconciled_at: datetime | str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            event = self.record_in_transaction(
                db,
                patient_link_id=patient_link_id,
                collection_key=collection_key,
                completeness=completeness,
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                source=source,
                patient_confirmed=patient_confirmed,
                reconciled_at=reconciled_at,
                note=note,
            )
            db.commit()
            return event
        except Exception:
            db.rollback()
            raise
