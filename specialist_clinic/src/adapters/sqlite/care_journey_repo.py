"""Append-only repository for specialist care journeys and invoice attribution."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.specialist_revenue_boundary_schema import (
    ensure_specialist_revenue_boundary_storage,
)

_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def _now_text(value: datetime | str | None = None) -> str:
    if value is None:
        parsed = datetime.now(_IRAN_TZ)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IRAN_TZ).replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _hash(payload: dict[str, Any]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class CareJourneyConflict(RuntimeError):
    pass


class CareJourneyRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def connection(self) -> sqlite3.Connection:
        return self._db()

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def enrollment_for_patient(self, patient_link_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM specialist_program_enrollments WHERE patient_link_id=?",
                (int(patient_link_id),),
            ).fetchone()
        )

    def journey(self, journey_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM care_journeys WHERE journey_id=?",
                (str(journey_id),),
            ).fetchone()
        )

    def journey_by_origin(
        self, patient_link_id: int, origin_type: str, origin_ref: str
    ) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM care_journeys
                   WHERE patient_link_id=? AND origin_type=? AND origin_ref=?""",
                (int(patient_link_id), str(origin_type), str(origin_ref)),
            ).fetchone()
        )

    def create_journey_once(
        self,
        *,
        patient_link_id: int,
        origin_type: str,
        origin_ref: str,
        actor_username: str,
        effective_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict:
        existing = self.journey_by_origin(patient_link_id, origin_type, origin_ref)
        if existing:
            return existing
        enrollment = self.enrollment_for_patient(patient_link_id)
        if not enrollment:
            raise CareJourneyConflict("SPECIALIST_ENROLLMENT_REQUIRED")
        when = _now_text(effective_at)
        if datetime.fromisoformat(when) < datetime.fromisoformat(enrollment["effective_at"]):
            raise CareJourneyConflict("JOURNEY_BEFORE_SPECIALIST_CUTOVER")
        journey_id = "journey_" + uuid.uuid4().hex
        db = self._db()
        db.execute(
            """INSERT INTO care_journeys
               (journey_id, patient_link_id, enrollment_id, origin_type,
                origin_ref, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                journey_id,
                int(patient_link_id),
                int(enrollment["id"]),
                str(origin_type),
                str(origin_ref),
                when,
                str(actor_username),
            ),
        )
        self._append_journey_event(
            journey_id=journey_id,
            event_type="OPENED",
            actor_username=actor_username,
            effective_at=when,
        )
        if commit:
            db.commit()
        return self.journey(journey_id)

    def current_journey_event(self, journey_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM care_journey_events
                   WHERE journey_id=? ORDER BY recorded_at DESC, id DESC LIMIT 1""",
                (str(journey_id),),
            ).fetchone()
        )

    def _append_journey_event(
        self,
        *,
        journey_id: str,
        event_type: str,
        actor_username: str,
        effective_at: datetime | str | None = None,
        note: str | None = None,
    ) -> dict:
        recorded = _now_text()
        effective = _now_text(effective_at or recorded)
        current = self.current_journey_event(journey_id)
        payload = {
            "journey_id": str(journey_id),
            "event_type": str(event_type),
            "effective_at": effective,
            "recorded_at": recorded,
            "actor_username": str(actor_username),
            "note": note,
            "supersedes_event_id": int(current["id"]) if current else None,
        }
        cursor = self._db().execute(
            """INSERT INTO care_journey_events
               (journey_id, event_type, effective_at, recorded_at,
                actor_username, note, supersedes_event_id, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["journey_id"],
                payload["event_type"],
                payload["effective_at"],
                payload["recorded_at"],
                payload["actor_username"],
                payload["note"],
                payload["supersedes_event_id"],
                _hash(payload),
            ),
        )
        return self._row(
            self._db().execute(
                "SELECT * FROM care_journey_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        )

    def encounter_for_invoice(self, accounting_invoice_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM care_encounters WHERE accounting_invoice_id=?",
                (int(accounting_invoice_id),),
            ).fetchone()
        )

    def encounter(self, encounter_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM care_encounters WHERE encounter_id=?",
                (str(encounter_id),),
            ).fetchone()
        )

    def current_encounter_event(self, encounter_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM care_encounter_events
                   WHERE encounter_id=? ORDER BY recorded_at DESC, id DESC LIMIT 1""",
                (str(encounter_id),),
            ).fetchone()
        )

    def _append_encounter_event(
        self,
        *,
        encounter_id: str,
        event_type: str,
        actor_username: str,
        effective_at: datetime | str | None = None,
        note: str | None = None,
    ) -> dict:
        recorded = _now_text()
        effective = _now_text(effective_at or recorded)
        current = self.current_encounter_event(encounter_id)
        payload = {
            "encounter_id": str(encounter_id),
            "event_type": str(event_type),
            "effective_at": effective,
            "recorded_at": recorded,
            "actor_username": str(actor_username),
            "note": note,
            "supersedes_event_id": int(current["id"]) if current else None,
        }
        cursor = self._db().execute(
            """INSERT INTO care_encounter_events
               (encounter_id, event_type, effective_at, recorded_at,
                actor_username, note, supersedes_event_id, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["encounter_id"],
                payload["event_type"],
                payload["effective_at"],
                payload["recorded_at"],
                payload["actor_username"],
                payload["note"],
                payload["supersedes_event_id"],
                _hash(payload),
            ),
        )
        return self._row(
            self._db().execute(
                "SELECT * FROM care_encounter_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        )

    def create_invoice_encounter_once(
        self,
        *,
        patient_link_id: int,
        accounting_invoice_id: int,
        actor_username: str,
        effective_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict:
        existing = self.encounter_for_invoice(accounting_invoice_id)
        if existing:
            if int(existing["patient_link_id"]) != int(patient_link_id):
                raise CareJourneyConflict("INVOICE_ALREADY_BOUND_TO_ANOTHER_PATIENT")
            return existing
        journey = self.create_journey_once(
            patient_link_id=patient_link_id,
            origin_type="ACCOUNTING_INVOICE",
            origin_ref=str(int(accounting_invoice_id)),
            actor_username=actor_username,
            effective_at=effective_at,
            commit=False,
        )
        encounter_id = "encounter_" + uuid.uuid4().hex
        when = _now_text(effective_at)
        db = self._db()
        db.execute(
            """INSERT INTO care_encounters
               (encounter_id, journey_id, patient_link_id, encounter_type,
                accounting_invoice_id, created_at, created_by)
               VALUES (?, ?, ?, 'SPECIALIST_VISIT', ?, ?, ?)""",
            (
                encounter_id,
                journey["journey_id"],
                int(patient_link_id),
                int(accounting_invoice_id),
                when,
                str(actor_username),
            ),
        )
        self._append_encounter_event(
            encounter_id=encounter_id,
            event_type="CREATED",
            actor_username=actor_username,
            effective_at=when,
        )
        if commit:
            db.commit()
        return self.encounter(encounter_id)

    def start_encounter(
        self,
        encounter_id: str,
        *,
        actor_username: str,
        effective_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict:
        current = self.current_encounter_event(encounter_id)
        if current and current["event_type"] == "STARTED":
            return current
        if not current or current["event_type"] not in {"CREATED", "SCHEDULED"}:
            raise CareJourneyConflict("ENCOUNTER_NOT_STARTABLE")
        event = self._append_encounter_event(
            encounter_id=encounter_id,
            event_type="STARTED",
            actor_username=actor_username,
            effective_at=effective_at,
        )
        if commit:
            self._db().commit()
        return event

    def complete_encounter(
        self,
        encounter_id: str,
        *,
        actor_username: str,
        effective_at: datetime | str | None = None,
        note: str | None = None,
        commit: bool = True,
    ) -> dict:
        current = self.current_encounter_event(encounter_id)
        if current and current["event_type"] == "COMPLETED":
            return current
        if not current or current["event_type"] != "STARTED":
            raise CareJourneyConflict("ENCOUNTER_NOT_STARTED")
        event = self._append_encounter_event(
            encounter_id=encounter_id,
            event_type="COMPLETED",
            actor_username=actor_username,
            effective_at=effective_at,
            note=note,
        )
        encounter = self.encounter(encounter_id)
        journey_current = self.current_journey_event(encounter["journey_id"])
        if journey_current and journey_current["event_type"] == "OPENED":
            self._append_journey_event(
                journey_id=encounter["journey_id"],
                event_type="COMPLETED",
                actor_username=actor_username,
                effective_at=effective_at,
                note=note,
            )
        if commit:
            self._db().commit()
        return event

    def current_attribution(self, accounting_invoice_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM accounting_invoice_attribution_events
                   WHERE accounting_invoice_id=?
                   ORDER BY recorded_at DESC, id DESC LIMIT 1""",
                (int(accounting_invoice_id),),
            ).fetchone()
        )

    def attribute_invoice_once(
        self,
        *,
        accounting_invoice_id: int,
        accounting_patient_id: int,
        patient_link_id: int,
        encounter_id: str,
        actor_username: str,
        reason_code: str = "DOCTOR_QUEUE_STARTED",
        effective_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict:
        current = self.current_attribution(accounting_invoice_id)
        if current and current["event_type"] == "ATTRIBUTED":
            if (
                int(current["patient_link_id"]) == int(patient_link_id)
                and current["encounter_id"] == encounter_id
            ):
                return current
            raise CareJourneyConflict("INVOICE_ATTRIBUTION_CONFLICT")
        encounter = self.encounter(encounter_id)
        enrollment = self.enrollment_for_patient(patient_link_id)
        if not encounter or not enrollment:
            raise CareJourneyConflict("ENCOUNTER_AND_ENROLLMENT_REQUIRED")
        recorded = _now_text()
        effective = _now_text(effective_at or recorded)
        payload = {
            "accounting_invoice_id": int(accounting_invoice_id),
            "accounting_patient_id": int(accounting_patient_id),
            "patient_link_id": int(patient_link_id),
            "enrollment_id": int(enrollment["id"]),
            "journey_id": encounter["journey_id"],
            "encounter_id": encounter_id,
            "event_type": "ATTRIBUTED",
            "reason_code": str(reason_code),
            "effective_at": effective,
            "recorded_at": recorded,
            "actor_username": str(actor_username),
            "note": None,
            "supersedes_event_id": int(current["id"]) if current else None,
        }
        cursor = self._db().execute(
            """INSERT INTO accounting_invoice_attribution_events
               (accounting_invoice_id, accounting_patient_id, patient_link_id,
                enrollment_id, journey_id, encounter_id, event_type, reason_code,
                effective_at, recorded_at, actor_username, note,
                supersedes_event_id, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, 'ATTRIBUTED', ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["accounting_invoice_id"],
                payload["accounting_patient_id"],
                payload["patient_link_id"],
                payload["enrollment_id"],
                payload["journey_id"],
                payload["encounter_id"],
                payload["reason_code"],
                payload["effective_at"],
                payload["recorded_at"],
                payload["actor_username"],
                payload["note"],
                payload["supersedes_event_id"],
                _hash(payload),
            ),
        )
        if commit:
            self._db().commit()
        return self._row(
            self._db().execute(
                "SELECT * FROM accounting_invoice_attribution_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        )

    def attributed_invoice_ids(self) -> list[int]:
        rows = self._db().execute(
            """SELECT event.accounting_invoice_id
               FROM accounting_invoice_attribution_events event
               WHERE event.id=(
                   SELECT head.id FROM accounting_invoice_attribution_events head
                   WHERE head.accounting_invoice_id=event.accounting_invoice_id
                   ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
               ) AND event.event_type='ATTRIBUTED'
               ORDER BY event.accounting_invoice_id"""
        ).fetchall()
        return [int(row["accounting_invoice_id"]) for row in rows]

    def attributed_invoices_by_patient(
        self, patient_link_ids: list[int]
    ) -> dict[int, list[int]]:
        ids = [int(value) for value in patient_link_ids if value]
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self._db().execute(
            f"""SELECT event.patient_link_id, event.accounting_invoice_id
                FROM accounting_invoice_attribution_events event
                WHERE event.patient_link_id IN ({marks})
                  AND event.id=(
                      SELECT head.id FROM accounting_invoice_attribution_events head
                      WHERE head.accounting_invoice_id=event.accounting_invoice_id
                      ORDER BY head.recorded_at DESC, head.id DESC LIMIT 1
                  ) AND event.event_type='ATTRIBUTED'""",
            ids,
        ).fetchall()
        result: dict[int, list[int]] = {}
        for row in rows:
            result.setdefault(int(row["patient_link_id"]), []).append(
                int(row["accounting_invoice_id"])
            )
        return result

    def scope_summary(self) -> dict:
        db = self._db()
        enrolled = db.execute(
            "SELECT COUNT(*) AS count FROM specialist_program_enrollments"
        ).fetchone()["count"]
        missing = db.execute(
            """SELECT COUNT(*) AS count FROM patient_links patient
               WHERE patient.accounting_patient_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM specialist_program_enrollments enrollment
                     WHERE enrollment.patient_link_id=patient.id
                 )"""
        ).fetchone()["count"]
        return {
            "enrollments": int(enrolled or 0),
            "linked_patients_missing_cutover": int(missing or 0),
            "attributed_invoices": len(self.attributed_invoice_ids()),
        }
