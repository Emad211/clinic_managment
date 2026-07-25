"""Append-only clinical encounter lifecycle and exact context projection."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from src.adapters.sqlite.clinical_context_schema import (
    ensure_clinical_context_storage,
)
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now, parse_datetime
from src.domain.clinical_engine.context import (
    CareSetting,
    ClinicalContextError,
    ClinicalEvaluationContext,
    EncounterEventType,
    EncounterStatus,
    EncounterType,
    EvaluationMode,
    iso_local,
    local_naive,
    make_context,
    normalize_reason_codes,
)


class ClinicalEncounterConflict(RuntimeError):
    """The encounter head changed after the caller loaded the form."""


class ClinicalEncounterRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self):
        db = self._connection or get_db()
        ensure_clinical_context_storage(db)
        return db

    @staticmethod
    def _event_payload(
        *,
        encounter_id: int,
        event_type: EncounterEventType,
        status: EncounterStatus,
        care_setting: CareSetting,
        encounter_type: EncounterType,
        reason_codes: tuple[str, ...],
        chief_complaint: str | None,
        responsible_actor: str | None,
        effective_at: datetime,
        recorded_at: datetime,
        supersedes_event_id: int | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "encounter_id": int(encounter_id),
            "event_type": event_type.value,
            "status": status.value,
            "care_setting": care_setting.value,
            "encounter_type": encounter_type.value,
            "reason_codes": list(reason_codes),
            "chief_complaint": chief_complaint,
            "responsible_actor": responsible_actor,
            "effective_at": iso_local(effective_at),
            "recorded_at": iso_local(recorded_at),
            "supersedes_event_id": supersedes_event_id,
        }

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _clean_text(value, *, limit: int) -> str | None:
        text = " ".join(str(value or "").strip().split())
        if not text:
            return None
        if len(text) > limit:
            raise ClinicalContextError(f"text exceeds {limit} characters")
        return text

    @staticmethod
    def _head(db, encounter_id: int):
        return db.execute(
            """SELECT event.*, encounter.encounter_key,
                      encounter.patient_link_id, encounter.appointment_id
               FROM clinical_encounter_events event
               JOIN clinical_encounters encounter ON encounter.id=event.encounter_id
               WHERE event.encounter_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_encounter_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1""",
            (encounter_id,),
        ).fetchone()

    def open(
        self,
        patient_link_id: int,
        *,
        care_setting: str | CareSetting,
        encounter_type: str | EncounterType,
        actor_username: str,
        actor_user_id: int | None = None,
        appointment_id: int | None = None,
        reason_codes=(),
        chief_complaint: str | None = None,
        responsible_actor: str | None = None,
        effective_at: datetime | None = None,
        recorded_at: datetime | None = None,
        note: str | None = None,
        encounter_key: str | None = None,
    ) -> dict:
        db = self._db()
        actor = self._clean_text(actor_username, limit=200)
        if not actor:
            raise ClinicalContextError("actor_username is required")
        recorded = local_naive(recorded_at or iran_now())
        effective = local_naive(effective_at or recorded)
        if effective > recorded:
            raise ClinicalContextError("encounter effective_at cannot exceed recorded_at")
        setting = CareSetting(care_setting)
        kind = EncounterType(encounter_type)
        if kind is EncounterType.LONGITUDINAL_REVIEW:
            raise ClinicalContextError("longitudinal_review is not a clinical encounter")
        reasons = normalize_reason_codes(reason_codes)
        complaint = self._clean_text(chief_complaint, limit=1000)
        responsible = self._clean_text(
            responsible_actor or actor, limit=200
        )
        key = (encounter_key or f"enc:{uuid.uuid4()}").strip()

        db.execute("BEGIN IMMEDIATE")
        try:
            patient = db.execute(
                "SELECT id FROM patient_links WHERE id=? AND is_active=1",
                (patient_link_id,),
            ).fetchone()
            if not patient:
                raise LookupError("patient not found or inactive")
            cursor = db.execute(
                """INSERT INTO clinical_encounters
                   (encounter_key, patient_link_id, appointment_id,
                    created_by, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, patient_link_id, appointment_id, actor, iso_local(recorded)),
            )
            encounter_id = int(cursor.lastrowid)
            payload = self._event_payload(
                encounter_id=encounter_id,
                event_type=EncounterEventType.OPENED,
                status=EncounterStatus.OPEN,
                care_setting=setting,
                encounter_type=kind,
                reason_codes=reasons,
                chief_complaint=complaint,
                responsible_actor=responsible,
                effective_at=effective,
                recorded_at=recorded,
                supersedes_event_id=None,
            )
            event_cursor = db.execute(
                """INSERT INTO clinical_encounter_events
                   (encounter_id, event_type, status, care_setting,
                    encounter_type, reason_codes_json, chief_complaint,
                    responsible_actor, effective_at, recorded_at, content_hash,
                    actor_user_id, actor_username, supersedes_event_id, note)
                   VALUES (?, 'OPENED', 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    encounter_id,
                    setting.value,
                    kind.value,
                    json.dumps(list(reasons), ensure_ascii=False),
                    complaint,
                    responsible,
                    iso_local(effective),
                    iso_local(recorded),
                    self._hash(payload),
                    actor_user_id,
                    actor,
                    self._clean_text(note, limit=1000),
                ),
            )
            event_id = int(event_cursor.lastrowid)
            db.commit()
            return self.get_event(event_id)
        except Exception:
            db.rollback()
            raise

    def append(
        self,
        encounter_key: str,
        *,
        event_type: str | EncounterEventType,
        actor_username: str,
        actor_user_id: int | None = None,
        expected_current_event_id: int,
        care_setting: str | CareSetting | None = None,
        encounter_type: str | EncounterType | None = None,
        reason_codes=None,
        chief_complaint: str | None = None,
        responsible_actor: str | None = None,
        effective_at: datetime | None = None,
        recorded_at: datetime | None = None,
        note: str | None = None,
    ) -> dict:
        db = self._db()
        actor = self._clean_text(actor_username, limit=200)
        if not actor:
            raise ClinicalContextError("actor_username is required")
        event_kind = EncounterEventType(event_type)
        status = {
            EncounterEventType.UPDATED: EncounterStatus.OPEN,
            EncounterEventType.FINALIZED: EncounterStatus.FINALIZED,
            EncounterEventType.CANCELLED: EncounterStatus.CANCELLED,
            EncounterEventType.ENTERED_IN_ERROR: EncounterStatus.ENTERED_IN_ERROR,
        }.get(event_kind)
        if status is None:
            raise ClinicalContextError("OPENED can only be created by open()")
        recorded = local_naive(recorded_at or iran_now())

        db.execute("BEGIN IMMEDIATE")
        try:
            encounter = db.execute(
                "SELECT * FROM clinical_encounters WHERE encounter_key=?",
                (encounter_key,),
            ).fetchone()
            if not encounter:
                raise LookupError("clinical encounter not found")
            head = self._head(db, int(encounter["id"]))
            if not head or int(head["id"]) != int(expected_current_event_id):
                raise ClinicalEncounterConflict("clinical encounter changed after load")
            if head["status"] != EncounterStatus.OPEN.value:
                raise ClinicalContextError("terminal encounter cannot be changed")
            setting = CareSetting(care_setting or head["care_setting"])
            kind = EncounterType(encounter_type or head["encounter_type"])
            reasons = normalize_reason_codes(
                json.loads(head["reason_codes_json"])
                if reason_codes is None
                else reason_codes
            )
            complaint = self._clean_text(
                head["chief_complaint"]
                if chief_complaint is None
                else chief_complaint,
                limit=1000,
            )
            responsible = self._clean_text(
                head["responsible_actor"]
                if responsible_actor is None
                else responsible_actor,
                limit=200,
            )
            effective = local_naive(
                effective_at or parse_datetime(head["effective_at"]) or recorded
            )
            if effective > recorded:
                raise ClinicalContextError(
                    "encounter effective_at cannot exceed recorded_at"
                )
            payload = self._event_payload(
                encounter_id=int(encounter["id"]),
                event_type=event_kind,
                status=status,
                care_setting=setting,
                encounter_type=kind,
                reason_codes=reasons,
                chief_complaint=complaint,
                responsible_actor=responsible,
                effective_at=effective,
                recorded_at=recorded,
                supersedes_event_id=int(head["id"]),
            )
            cursor = db.execute(
                """INSERT INTO clinical_encounter_events
                   (encounter_id, event_type, status, care_setting,
                    encounter_type, reason_codes_json, chief_complaint,
                    responsible_actor, effective_at, recorded_at, content_hash,
                    actor_user_id, actor_username, supersedes_event_id, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(encounter["id"]),
                    event_kind.value,
                    status.value,
                    setting.value,
                    kind.value,
                    json.dumps(list(reasons), ensure_ascii=False),
                    complaint,
                    responsible,
                    iso_local(effective),
                    iso_local(recorded),
                    self._hash(payload),
                    actor_user_id,
                    actor,
                    int(head["id"]),
                    self._clean_text(note, limit=1000),
                ),
            )
            event_id = int(cursor.lastrowid)
            db.commit()
            return self.get_event(event_id)
        except Exception:
            db.rollback()
            raise

    def get_event(self, event_id: int) -> dict | None:
        row = self._db().execute(
            """SELECT event.*, encounter.encounter_key,
                      encounter.patient_link_id, encounter.appointment_id,
                      encounter.created_by, encounter.created_at
               FROM clinical_encounter_events event
               JOIN clinical_encounters encounter ON encounter.id=event.encounter_id
               WHERE event.id=?""",
            (event_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["reason_codes"] = tuple(json.loads(result["reason_codes_json"]))
        return result

    def current(self, encounter_key: str) -> dict | None:
        encounter = self._db().execute(
            "SELECT id FROM clinical_encounters WHERE encounter_key=?",
            (encounter_key,),
        ).fetchone()
        if not encounter:
            return None
        row = self._head(self._db(), int(encounter["id"]))
        if not row:
            return None
        result = dict(row)
        result["reason_codes"] = tuple(json.loads(result["reason_codes_json"]))
        return result

    def list_for_patient(self, patient_link_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT encounter.encounter_key, encounter.appointment_id,
                      event.*, encounter.created_by, encounter.created_at
               FROM clinical_encounters encounter
               JOIN clinical_encounter_events event ON event.encounter_id=encounter.id
               WHERE encounter.patient_link_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM clinical_encounter_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.recorded_at DESC, event.id DESC""",
            (patient_link_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["reason_codes"] = tuple(json.loads(item["reason_codes_json"]))
            result.append(item)
        return result

    def context_for_event(
        self,
        event_id: int,
        *,
        assessed_at: datetime,
        require_current: bool = True,
    ) -> ClinicalEvaluationContext:
        event = self.get_event(event_id)
        if not event:
            raise LookupError("clinical encounter event not found")
        current = self.current(str(event["encounter_key"]))
        if require_current and (
            not current or int(current["id"]) != int(event["id"])
        ):
            raise ClinicalEncounterConflict("encounter event is no longer current")
        status = EncounterStatus(event["status"])
        if status not in {EncounterStatus.OPEN, EncounterStatus.FINALIZED}:
            raise ClinicalContextError("encounter is not executable")
        assessed = local_naive(assessed_at)
        return make_context(
            patient_link_id=int(event["patient_link_id"]),
            context_key=f"encounter:{event['encounter_key']}:{assessed.date().isoformat()}",
            evaluation_mode=EvaluationMode.ENCOUNTER,
            care_setting=CareSetting(event["care_setting"]),
            encounter_type=EncounterType(event["encounter_type"]),
            assessment_date=assessed.date().isoformat(),
            effective_at=parse_datetime(event["effective_at"]) or assessed,
            recorded_at=assessed,
            source="clinical-encounter-event",
            encounter_key=str(event["encounter_key"]),
            encounter_event_id=int(event["id"]),
            encounter_status=status,
            appointment_id=(
                int(event["appointment_id"])
                if event.get("appointment_id") is not None
                else None
            ),
            reason_codes=tuple(event["reason_codes"]),
            chief_complaint=event.get("chief_complaint"),
            responsible_actor=event.get("responsible_actor"),
        )
