"""Atomic append-only writes for longitudinal clinical flag events."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import sqlite3
from typing import Any
from uuid import uuid4

from src.adapters.sqlite.core import get_db
from src.domain.clinical_engine.flag_history import (
    ClinicalFlagState,
    ClinicalFlagValueError,
    encode_flag_value,
)

from .clinical_flag_common import (
    ClinicalFlagConflict,
    ClinicalFlagValidationError,
    parsed_time,
    text_time,
)


_ALLOWED_SOURCES = frozenset(
    {"clinician", "patient", "caregiver", "imported", "system"}
)
_ALLOWED_VERIFICATION = frozenset(
    {"CONFIRMED", "PROVISIONAL", "UNVERIFIED", "REFUTED"}
)


class ClinicalFlagEventRepositoryMixin:
    @staticmethod
    def _head_event(
        db: sqlite3.Connection,
        patient_link_id: int,
        flag_key: str,
    ) -> sqlite3.Row | None:
        return db.execute(
            """SELECT event.*
                 FROM clinical_flag_events event
                WHERE event.patient_link_id=? AND event.flag_key=?
                  AND NOT EXISTS (
                      SELECT 1 FROM clinical_flag_events child
                       WHERE child.supersedes_event_id=event.id
                  )
                ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1""",
            (patient_link_id, flag_key),
        ).fetchone()

    @classmethod
    def append_batch_in_transaction(
        cls,
        db: sqlite3.Connection,
        patient_link_id: int,
        updates: Mapping[str, Mapping[str, Any]],
        *,
        actor_username: str,
        actor_user_id: int | None = None,
        expected_event_ids: Mapping[str, int | None] | None = None,
        expected_definition_hashes: Mapping[str, str] | None = None,
        source: str = "clinician",
        verification: str = "CONFIRMED",
        effective_at: datetime | str | None = None,
        recorded_at: datetime | str | None = None,
        note: str | None = None,
        batch_id: str | None = None,
        record_unchanged: bool = True,
    ) -> list[int]:
        actor = str(actor_username or "").strip()
        if not actor:
            raise ClinicalFlagValidationError("actor_username is required")
        if source not in _ALLOWED_SOURCES:
            raise ClinicalFlagValidationError("unsupported clinical flag source")
        if verification not in _ALLOWED_VERIFICATION:
            raise ClinicalFlagValidationError(
                "unsupported clinical flag verification"
            )
        normalized_updates = {
            str(key).strip(): dict(value)
            for key, value in updates.items()
            if str(key).strip()
        }
        if not normalized_updates:
            return []
        if expected_event_ids is not None:
            missing_expected = sorted(
                set(normalized_updates) - set(expected_event_ids)
            )
            if missing_expected:
                raise ClinicalFlagValidationError(
                    "missing expected event ids: " + ", ".join(missing_expected)
                )
        if expected_definition_hashes is not None:
            missing_hashes = sorted(
                set(normalized_updates) - set(expected_definition_hashes)
            )
            if missing_hashes:
                raise ClinicalFlagValidationError(
                    "missing expected definition hashes: "
                    + ", ".join(missing_hashes)
                )

        recorded_dt = parsed_time(recorded_at)
        default_effective = parsed_time(effective_at or recorded_dt)
        if default_effective > recorded_dt:
            raise ClinicalFlagValidationError(
                "clinical flag effective_at cannot be after recorded_at"
            )
        recorded_text = text_time(recorded_dt)
        normalized_batch = str(batch_id or uuid4()).strip()
        if not normalized_batch:
            raise ClinicalFlagValidationError("batch_id cannot be blank")

        if not db.execute(
            "SELECT 1 FROM patient_links WHERE id=?",
            (patient_link_id,),
        ).fetchone():
            raise LookupError("patient not found")

        marks = ",".join("?" for _ in normalized_updates)
        catalog_rows = db.execute(
            f"""SELECT * FROM flag_catalog
                WHERE is_active=1 AND flag_key IN ({marks})""",
            tuple(normalized_updates),
        ).fetchall()
        catalog = {
            str(row["flag_key"]): dict(row) for row in catalog_rows
        }
        missing = sorted(set(normalized_updates) - set(catalog))
        if missing:
            raise ClinicalFlagValidationError(
                "unknown or inactive clinical flags: " + ", ".join(missing)
            )

        appended_ids: list[int] = []
        for key in sorted(normalized_updates):
            update = normalized_updates[key]
            definition = catalog[key]
            if expected_definition_hashes is not None and str(
                expected_definition_hashes[key]
            ) != str(definition["definition_hash"]):
                raise ClinicalFlagConflict(
                    f"clinical flag definition {key} changed after form load"
                )
            try:
                state = ClinicalFlagState(
                    update.get("state", update.get("status"))
                )
                value_json = encode_flag_value(
                    state,
                    update.get("value"),
                    flag_type=definition["flag_type"],
                    options_json=definition["options_json"],
                )
            except (ValueError, ClinicalFlagValueError) as exc:
                raise ClinicalFlagValidationError(
                    f"invalid value for {key}: {exc}"
                ) from exc

            head = cls._head_event(db, patient_link_id, key)
            head_id = int(head["id"]) if head else None
            if head and recorded_dt < parsed_time(head["recorded_at"]):
                raise ClinicalFlagValidationError(
                    f"clinical flag {key} recorded_at cannot move backwards"
                )
            if expected_event_ids is not None:
                expected = expected_event_ids[key]
                expected = int(expected) if expected not in {None, ""} else None
                if expected != head_id:
                    raise ClinicalFlagConflict(
                        f"clinical flag {key} changed after form load"
                    )

            event_effective = parsed_time(
                update.get("effective_at") or default_effective
            )
            if event_effective > recorded_dt:
                raise ClinicalFlagValidationError(
                    f"clinical flag {key} effective_at cannot be after recorded_at"
                )

            if not record_unchanged and head and (
                str(head["status"]) == state.value
                and head["value_json"] == value_json
                and str(head["definition_hash"])
                == str(definition["definition_hash"])
                and str(head["verification"]) == verification
            ):
                continue

            source_record_id = update.get("source_record_id")
            source_record_id = (
                str(source_record_id).strip()
                if source_record_id is not None
                else None
            )
            cursor = db.execute(
                """INSERT INTO clinical_flag_events
                   (patient_link_id, flag_key, status, value_json, flag_type,
                    definition_hash, verification, source, source_record_id,
                    actor_user_id, actor_username, effective_at, recorded_at,
                    batch_id, supersedes_event_id, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    patient_link_id,
                    key,
                    state.value,
                    value_json,
                    definition["flag_type"],
                    definition["definition_hash"],
                    verification,
                    source,
                    source_record_id or None,
                    actor_user_id,
                    actor,
                    text_time(event_effective),
                    recorded_text,
                    normalized_batch,
                    head_id,
                    update.get("note") or note,
                ),
            )
            appended_ids.append(int(cursor.lastrowid))
        return appended_ids

    def append_batch(
        self,
        patient_link_id: int,
        updates: Mapping[str, Mapping[str, Any]],
        **kwargs,
    ) -> list[dict]:
        db = get_db()
        if db.in_transaction:
            raise RuntimeError(
                "clinical flag append requires a transaction-free connection"
            )
        db.execute("BEGIN IMMEDIATE")
        try:
            appended_ids = self.append_batch_in_transaction(
                db,
                patient_link_id,
                updates,
                **kwargs,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        if not appended_ids:
            return []
        marks = ",".join("?" for _ in appended_ids)
        rows = db.execute(
            f"SELECT * FROM clinical_flag_events WHERE id IN ({marks}) ORDER BY id",
            tuple(appended_ids),
        ).fetchall()
        return [dict(row) for row in rows]
