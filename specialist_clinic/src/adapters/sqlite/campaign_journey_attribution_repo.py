"""Append-only campaign response, consent, audience and Journey attribution repository."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from src.adapters.sqlite.campaign_journey_attribution_schema import (
    ensure_campaign_journey_attribution_storage,
)
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class CampaignAttributionConflict(RuntimeError):
    pass


class CampaignAttributionValidationError(ValueError):
    pass


def _clean(value, *, limit: int = 2000) -> str | None:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    if len(text) > limit:
        raise CampaignAttributionValidationError(f"text exceeds {limit} characters")
    return text


def _time(value: datetime | str | None = None) -> str:
    current = value or iran_now()
    if isinstance(current, str):
        parsed = datetime.fromisoformat(current.replace("Z", "+00:00"))
    else:
        parsed = current
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class CampaignJourneyAttributionRepository:
    POSITIVE_RESPONSES = {"INTERESTED", "BOOKING_REQUEST"}
    RESPONSE_TYPES = POSITIVE_RESPONSES | {"DECLINED", "STOP", "OTHER"}

    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        db = get_db()
        ensure_campaign_journey_attribution_storage(db)
        return db

    @staticmethod
    def _dict(row) -> dict | None:
        return dict(row) if row else None

    # ------------------------------------------------------------------ audience
    def audience_snapshot(self, campaign_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT snapshot.*, patient.is_active AS current_is_active,
                      COALESCE(patient.sms_opt_out,0) AS current_sms_opt_out,
                      patient.phone_number AS current_phone_number,
                      patient.full_name AS current_full_name
               FROM campaign_audience_snapshots snapshot
               JOIN patient_links patient ON patient.id=snapshot.patient_link_id
               WHERE snapshot.campaign_id=?
               ORDER BY snapshot.grp, snapshot.patient_link_id""",
            (int(campaign_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def freeze_audience_once(
        self,
        *,
        campaign_id: int,
        recipients: list[dict],
        control_ids: set[int] | None = None,
        assigned_at: datetime | str | None = None,
    ) -> tuple[list[dict], bool]:
        db = self._db()
        existing = self.audience_snapshot(campaign_id)
        if existing:
            return existing, False
        when = _time(assigned_at)
        controls = {int(value) for value in (control_ids or set())}
        normalized: list[dict] = []
        seen: set[int] = set()
        for source in recipients:
            patient_id = int(source["id"])
            if patient_id in seen:
                continue
            seen.add(patient_id)
            name = _clean(source.get("full_name"), limit=500)
            recipient = _clean(source.get("phone_number"), limit=100)
            if not name or not recipient:
                raise CampaignAttributionValidationError(
                    "audience snapshot requires patient name and recipient"
                )
            normalized.append(
                {
                    "campaign_id": int(campaign_id),
                    "patient_link_id": patient_id,
                    "accounting_patient_id": (
                        int(source["accounting_patient_id"])
                        if source.get("accounting_patient_id") is not None
                        else None
                    ),
                    "grp": "control" if patient_id in controls else "treated",
                    "full_name_snapshot": name,
                    "recipient_snapshot": recipient,
                    "assigned_at": when,
                    "assignment_key": f"campaign:{int(campaign_id)}:patient:{patient_id}",
                }
            )
        if not normalized:
            return [], True

        db.execute("BEGIN IMMEDIATE")
        try:
            race = db.execute(
                "SELECT COUNT(*) AS count FROM campaign_audience_snapshots WHERE campaign_id=?",
                (int(campaign_id),),
            ).fetchone()["count"]
            if int(race or 0):
                db.commit()
                return self.audience_snapshot(campaign_id), False
            for item in normalized:
                db.execute(
                    """INSERT INTO campaign_audience_snapshots
                       (campaign_id, patient_link_id, accounting_patient_id, grp,
                        full_name_snapshot, recipient_snapshot, assigned_at,
                        assignment_key, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item["campaign_id"], item["patient_link_id"],
                        item["accounting_patient_id"], item["grp"],
                        item["full_name_snapshot"], item["recipient_snapshot"],
                        item["assigned_at"], item["assignment_key"], _hash(item),
                    ),
                )
            db.commit()
            return self.audience_snapshot(campaign_id), True
        except Exception:
            db.rollback()
            raise

    # ------------------------------------------------------------------ responses
    def response_by_idempotency(self, key: str) -> dict | None:
        return self._dict(
            self._db().execute(
                "SELECT * FROM sms_response_events WHERE idempotency_key=?",
                (str(key),),
            ).fetchone()
        )

    def record_response_once(
        self,
        *,
        sms_message_id: int,
        response_type: str,
        actor_username: str,
        actor_user_id: int | None = None,
        occurred_at: datetime | str | None = None,
        recorded_at: datetime | str | None = None,
        note: str | None = None,
        idempotency_key: str,
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        key = _clean(idempotency_key, limit=300)
        if not key or len(key) < 12:
            raise CampaignAttributionValidationError("response idempotency key is required")
        existing = self.response_by_idempotency(key)
        if existing:
            return existing, False
        kind = str(response_type or "").strip().upper()
        if kind not in self.RESPONSE_TYPES:
            raise CampaignAttributionValidationError("invalid SMS response type")
        message = db.execute(
            "SELECT * FROM sms_messages WHERE id=?", (int(sms_message_id),)
        ).fetchone()
        if not message:
            raise LookupError("SMS message not found")
        if message["status"] != "sent":
            raise CampaignAttributionValidationError(
                "patient response can only be recorded for a provider-accepted message"
            )
        actor = _clean(actor_username, limit=200)
        if not actor:
            raise CampaignAttributionValidationError("actor_username is required")
        note_text = _clean(note)
        if kind == "OTHER" and not note_text:
            raise CampaignAttributionValidationError("OTHER response requires a note")
        occurred = _time(occurred_at)
        recorded = _time(recorded_at)
        if datetime.fromisoformat(recorded) < datetime.fromisoformat(occurred):
            raise CampaignAttributionValidationError(
                "response recorded_at cannot precede occurred_at"
            )
        payload = {
            "sms_message_id": int(sms_message_id),
            "campaign_id": (
                int(message["campaign_id"])
                if message["campaign_id"] is not None
                else None
            ),
            "patient_link_id": int(message["patient_link_id"]),
            "response_type": kind,
            "occurred_at": occurred,
            "recorded_at": recorded,
            "actor_user_id": actor_user_id,
            "actor_username": actor,
            "note": note_text,
            "delivery_status_snapshot": message["delivery_status"],
            "idempotency_key": key,
        }
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            cursor = db.execute(
                """INSERT INTO sms_response_events
                   (sms_message_id, campaign_id, patient_link_id, response_type,
                    occurred_at, recorded_at, actor_user_id, actor_username,
                    note, delivery_status_snapshot, idempotency_key, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["sms_message_id"], payload["campaign_id"],
                    payload["patient_link_id"], payload["response_type"],
                    payload["occurred_at"], payload["recorded_at"],
                    payload["actor_user_id"], payload["actor_username"],
                    payload["note"], payload["delivery_status_snapshot"],
                    payload["idempotency_key"], _hash(payload),
                ),
            )
            row = db.execute(
                "SELECT * FROM sms_response_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if kind == "STOP":
                self._record_consent(
                    db,
                    patient_link_id=int(message["patient_link_id"]),
                    event_type="OPTED_OUT",
                    source="PATIENT_RESPONSE",
                    sms_message_id=int(sms_message_id),
                    occurred_at=occurred,
                    recorded_at=recorded,
                    actor_user_id=actor_user_id,
                    actor_username=actor,
                    note=note_text or "Patient requested STOP",
                    idempotency_key=f"consent:stop:response:{int(cursor.lastrowid)}",
                )
                db.execute(
                    "UPDATE patient_links SET sms_opt_out=1 WHERE id=?",
                    (int(message["patient_link_id"]),),
                )
            if commit:
                db.commit()
            return dict(row), True
        except sqlite3.IntegrityError:
            if commit:
                db.rollback()
            existing = self.response_by_idempotency(key)
            if existing:
                return existing, False
            raise
        except Exception:
            if commit:
                db.rollback()
            raise

    def _record_consent(
        self,
        db: sqlite3.Connection,
        *,
        patient_link_id: int,
        event_type: str,
        source: str,
        sms_message_id: int | None,
        occurred_at: str,
        recorded_at: str,
        actor_user_id: int | None,
        actor_username: str,
        note: str | None,
        idempotency_key: str,
    ) -> int:
        payload = {
            "patient_link_id": int(patient_link_id),
            "event_type": str(event_type),
            "source": str(source),
            "sms_message_id": sms_message_id,
            "occurred_at": occurred_at,
            "recorded_at": recorded_at,
            "actor_user_id": actor_user_id,
            "actor_username": actor_username,
            "note": note,
            "idempotency_key": idempotency_key,
        }
        cursor = db.execute(
            """INSERT OR IGNORE INTO sms_consent_events
               (patient_link_id, event_type, source, sms_message_id,
                occurred_at, recorded_at, actor_user_id, actor_username,
                note, idempotency_key, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["patient_link_id"], payload["event_type"],
                payload["source"], payload["sms_message_id"],
                payload["occurred_at"], payload["recorded_at"],
                payload["actor_user_id"], payload["actor_username"],
                payload["note"], payload["idempotency_key"], _hash(payload),
            ),
        )
        return int(cursor.lastrowid or 0)

    def record_consent_once(
        self,
        *,
        patient_link_id: int,
        event_type: str,
        actor_username: str,
        actor_user_id: int | None = None,
        source: str = "STAFF_RECORDED",
        sms_message_id: int | None = None,
        occurred_at: datetime | str | None = None,
        note: str | None = None,
        idempotency_key: str,
    ) -> tuple[dict, bool]:
        kind = str(event_type or "").strip().upper()
        if kind not in {"OPTED_IN", "OPTED_OUT"}:
            raise CampaignAttributionValidationError("invalid consent event")
        actor = _clean(actor_username, limit=200)
        if not actor:
            raise CampaignAttributionValidationError("actor_username is required")
        key = _clean(idempotency_key, limit=300)
        if not key or len(key) < 12:
            raise CampaignAttributionValidationError("consent idempotency key is required")
        db = self._db()
        existing = db.execute(
            "SELECT * FROM sms_consent_events WHERE idempotency_key=?", (key,)
        ).fetchone()
        if existing:
            return dict(existing), False
        when = _time(occurred_at)
        db.execute("BEGIN IMMEDIATE")
        try:
            consent_id = self._record_consent(
                db,
                patient_link_id=int(patient_link_id),
                event_type=kind,
                source=str(source),
                sms_message_id=sms_message_id,
                occurred_at=when,
                recorded_at=_time(),
                actor_user_id=actor_user_id,
                actor_username=actor,
                note=_clean(note),
                idempotency_key=key,
            )
            db.execute(
                "UPDATE patient_links SET sms_opt_out=? WHERE id=?",
                (1 if kind == "OPTED_OUT" else 0, int(patient_link_id)),
            )
            row = db.execute(
                "SELECT * FROM sms_consent_events WHERE id=?", (consent_id,)
            ).fetchone()
            db.commit()
            return dict(row), True
        except Exception:
            db.rollback()
            raise

    def responses_for_message(self, sms_message_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM sms_response_events
                   WHERE sms_message_id=? ORDER BY occurred_at DESC, id DESC""",
                (int(sms_message_id),),
            ).fetchall()
        ]

    # --------------------------------------------------------------- attribution
    @staticmethod
    def _head(db: sqlite3.Connection, attribution_id: str):
        return db.execute(
            """SELECT event.* FROM campaign_journey_attribution_events event
               WHERE event.attribution_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM campaign_journey_attribution_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.recorded_at DESC, event.id DESC LIMIT 1""",
            (str(attribution_id),),
        ).fetchone()

    def current_attribution_for_journey(self, journey_id: str) -> dict | None:
        row = self._db().execute(
            """SELECT root.*, event.id AS current_event_id,
                      event.event_type AS current_event_type,
                      event.status AS current_status,
                      event.campaign_id, event.sms_message_id,
                      event.response_event_id, event.reason_code,
                      event.note AS current_note,
                      event.recorded_at AS current_recorded_at
               FROM campaign_journey_attributions root
               JOIN campaign_journey_attribution_events event
                 ON event.attribution_id=root.attribution_id
               WHERE root.journey_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM campaign_journey_attribution_events child
                     WHERE child.supersedes_event_id=event.id
                 )""",
            (str(journey_id),),
        ).fetchone()
        return self._dict(row)

    def attribute_journey(
        self,
        *,
        journey_id: str,
        campaign_id: int,
        sms_message_id: int,
        response_event_id: int,
        actor_username: str,
        actor_user_id: int | None = None,
        note: str | None = None,
        reason_code: str = "EXPLICIT_PATIENT_RESPONSE",
        effective_at: datetime | str | None = None,
        allow_reattribution: bool = False,
        commit: bool = True,
    ) -> tuple[dict, bool]:
        db = self._db()
        actor = _clean(actor_username, limit=200)
        if not actor:
            raise CampaignAttributionValidationError("actor_username is required")
        journey = db.execute(
            "SELECT journey_id, patient_link_id FROM care_journeys WHERE journey_id=?",
            (str(journey_id),),
        ).fetchone()
        if not journey:
            raise LookupError("CareJourney not found")
        response = db.execute(
            "SELECT * FROM sms_response_events WHERE id=?",
            (int(response_event_id),),
        ).fetchone()
        if not response:
            raise LookupError("SMS response event not found")
        if response["response_type"] not in self.POSITIVE_RESPONSES:
            raise CampaignAttributionValidationError(
                "Journey attribution requires INTERESTED or BOOKING_REQUEST"
            )
        if (
            int(response["patient_link_id"]) != int(journey["patient_link_id"])
            or int(response["sms_message_id"]) != int(sms_message_id)
            or int(response["campaign_id"] or 0) != int(campaign_id)
        ):
            raise CampaignAttributionValidationError(
                "response, message, campaign and Journey scope mismatch"
            )
        when = _time(effective_at)
        current = self.current_attribution_for_journey(journey_id)
        if current and current["current_status"] == "ATTRIBUTED":
            same = all(
                (
                    int(current["campaign_id"]) == int(campaign_id),
                    int(current["sms_message_id"]) == int(sms_message_id),
                    int(current["response_event_id"]) == int(response_event_id),
                )
            )
            if same:
                return current, False
            if not allow_reattribution:
                raise CampaignAttributionConflict(
                    "JOURNEY_ALREADY_ATTRIBUTED_TO_ANOTHER_CAMPAIGN"
                )
            if not _clean(note):
                raise CampaignAttributionValidationError(
                    "re-attribution requires an explanatory note"
                )

        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            current = self.current_attribution_for_journey(journey_id)
            if not current:
                attribution_id = "campaignattr_" + uuid.uuid4().hex
                root = {
                    "attribution_id": attribution_id,
                    "journey_id": str(journey_id),
                    "patient_link_id": int(journey["patient_link_id"]),
                    "created_at": when,
                    "created_by": actor,
                }
                db.execute(
                    """INSERT INTO campaign_journey_attributions
                       (attribution_id, journey_id, patient_link_id,
                        created_at, created_by, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        root["attribution_id"], root["journey_id"],
                        root["patient_link_id"], root["created_at"],
                        root["created_by"], _hash(root),
                    ),
                )
                event_type = "ATTRIBUTED"
                supersedes = None
            else:
                attribution_id = str(current["attribution_id"])
                if current["current_status"] == "ATTRIBUTED" and not allow_reattribution:
                    raise CampaignAttributionConflict(
                        "JOURNEY_ALREADY_ATTRIBUTED_TO_ANOTHER_CAMPAIGN"
                    )
                event_type = "REATTRIBUTED"
                supersedes = int(current["current_event_id"])
            event = {
                "attribution_id": attribution_id,
                "event_type": event_type,
                "status": "ATTRIBUTED",
                "campaign_id": int(campaign_id),
                "sms_message_id": int(sms_message_id),
                "response_event_id": int(response_event_id),
                "reason_code": str(reason_code),
                "note": _clean(note),
                "effective_at": when,
                "recorded_at": _time(),
                "actor_user_id": actor_user_id,
                "actor_username": actor,
                "supersedes_event_id": supersedes,
            }
            cursor = db.execute(
                """INSERT INTO campaign_journey_attribution_events
                   (attribution_id, event_type, status, campaign_id,
                    sms_message_id, response_event_id, reason_code, note,
                    effective_at, recorded_at, actor_user_id, actor_username,
                    supersedes_event_id, content_hash)
                   VALUES (?, ?, 'ATTRIBUTED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["attribution_id"], event["event_type"],
                    event["campaign_id"], event["sms_message_id"],
                    event["response_event_id"], event["reason_code"],
                    event["note"], event["effective_at"], event["recorded_at"],
                    event["actor_user_id"], event["actor_username"],
                    event["supersedes_event_id"], _hash(event),
                ),
            )
            if commit:
                db.commit()
            result = self.current_attribution_for_journey(journey_id)
            result["appended_event_id"] = int(cursor.lastrowid)
            return result, True
        except Exception:
            if commit:
                db.rollback()
            raise

    def _terminal_event(
        self,
        *,
        journey_id: str,
        event_type: str,
        status: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
        reason_code: str,
    ) -> dict:
        db = self._db()
        current = self.current_attribution_for_journey(journey_id)
        if not current:
            raise LookupError("campaign Journey attribution not found")
        note_text = _clean(note)
        if not note_text:
            raise CampaignAttributionValidationError(
                f"{event_type.lower()} requires an explanatory note"
            )
        actor = _clean(actor_username, limit=200)
        if not actor:
            raise CampaignAttributionValidationError("actor_username is required")
        event = {
            "attribution_id": current["attribution_id"],
            "event_type": event_type,
            "status": status,
            "campaign_id": current["campaign_id"],
            "sms_message_id": current["sms_message_id"],
            "response_event_id": current["response_event_id"],
            "reason_code": str(reason_code),
            "note": note_text,
            "effective_at": _time(),
            "recorded_at": _time(),
            "actor_user_id": actor_user_id,
            "actor_username": actor,
            "supersedes_event_id": int(current["current_event_id"]),
        }
        db.execute("BEGIN IMMEDIATE")
        try:
            cursor = db.execute(
                """INSERT INTO campaign_journey_attribution_events
                   (attribution_id, event_type, status, campaign_id,
                    sms_message_id, response_event_id, reason_code, note,
                    effective_at, recorded_at, actor_user_id, actor_username,
                    supersedes_event_id, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["attribution_id"], event["event_type"], event["status"],
                    event["campaign_id"], event["sms_message_id"],
                    event["response_event_id"], event["reason_code"],
                    event["note"], event["effective_at"], event["recorded_at"],
                    event["actor_user_id"], event["actor_username"],
                    event["supersedes_event_id"], _hash(event),
                ),
            )
            db.commit()
            result = self.current_attribution_for_journey(journey_id)
            result["appended_event_id"] = int(cursor.lastrowid)
            return result
        except Exception:
            db.rollback()
            raise

    def revoke(
        self,
        *,
        journey_id: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
    ) -> dict:
        current = self.current_attribution_for_journey(journey_id)
        if not current or current["current_status"] != "ATTRIBUTED":
            raise CampaignAttributionConflict("only current attribution can be revoked")
        return self._terminal_event(
            journey_id=journey_id,
            event_type="REVOKED",
            status="REVOKED",
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            note=note,
            reason_code="MANUAL_REVOCATION",
        )

    def enter_in_error(
        self,
        *,
        journey_id: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
    ) -> dict:
        return self._terminal_event(
            journey_id=journey_id,
            event_type="ENTERED_IN_ERROR",
            status="ENTERED_IN_ERROR",
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            note=note,
            reason_code="DATA_CORRECTION",
        )

    # -------------------------------------------------------------- read models
    def candidate_journeys(self, patient_link_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT journey.journey_id, journey.accounting_invoice_id,
                      journey.created_at, event.event_type AS current_event_type,
                      event.status AS current_status,
                      attribution.attribution_id,
                      attribution.current_campaign_id,
                      attribution.current_attribution_status
               FROM care_journeys journey
               JOIN care_journey_events event ON event.journey_id=journey.journey_id
               LEFT JOIN (
                   SELECT root.journey_id, root.attribution_id,
                          head.campaign_id AS current_campaign_id,
                          head.status AS current_attribution_status
                   FROM campaign_journey_attributions root
                   JOIN campaign_journey_attribution_events head
                     ON head.attribution_id=root.attribution_id
                   WHERE NOT EXISTS (
                       SELECT 1 FROM campaign_journey_attribution_events child
                       WHERE child.supersedes_event_id=head.id
                   )
               ) attribution ON attribution.journey_id=journey.journey_id
               WHERE journey.patient_link_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM care_journey_events child
                     WHERE child.supersedes_event_id=event.id
                 )
                 AND event.status NOT IN ('ENTERED_IN_ERROR')
               ORDER BY journey.created_at DESC, journey.journey_id DESC""",
            (int(patient_link_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def current_attributions(self, campaign_id: int | None = None) -> list[dict]:
        sql = """SELECT root.*, event.id AS current_event_id,
                        event.status AS current_status,
                        event.campaign_id, event.sms_message_id,
                        event.response_event_id, event.recorded_at,
                        journey.accounting_invoice_id
                 FROM campaign_journey_attributions root
                 JOIN campaign_journey_attribution_events event
                   ON event.attribution_id=root.attribution_id
                 JOIN care_journeys journey ON journey.journey_id=root.journey_id
                 WHERE NOT EXISTS (
                     SELECT 1 FROM campaign_journey_attribution_events child
                     WHERE child.supersedes_event_id=event.id
                 )"""
        params: list[Any] = []
        if campaign_id is not None:
            sql += " AND event.campaign_id=?"
            params.append(int(campaign_id))
        sql += " ORDER BY event.recorded_at DESC, event.id DESC"
        return [dict(row) for row in self._db().execute(sql, params).fetchall()]

    def message_response_projection(self, campaign_id: int) -> dict[int, dict]:
        rows = self._db().execute(
            """SELECT message.id AS sms_message_id,
                      response.id AS response_event_id,
                      response.response_type, response.occurred_at,
                      response.note AS response_note,
                      root.journey_id,
                      attribution.status AS attribution_status,
                      attribution.campaign_id AS attributed_campaign_id
               FROM sms_messages message
               LEFT JOIN sms_response_events response ON response.id=(
                   SELECT latest.id FROM sms_response_events latest
                   WHERE latest.sms_message_id=message.id
                   ORDER BY latest.occurred_at DESC, latest.id DESC LIMIT 1
               )
               LEFT JOIN campaign_journey_attribution_events attribution
                 ON attribution.response_event_id=response.id
                AND NOT EXISTS (
                    SELECT 1 FROM campaign_journey_attribution_events child
                    WHERE child.supersedes_event_id=attribution.id
                )
               LEFT JOIN campaign_journey_attributions root
                 ON root.attribution_id=attribution.attribution_id
               WHERE message.campaign_id=?""",
            (int(campaign_id),),
        ).fetchall()
        return {int(row["sms_message_id"]): dict(row) for row in rows}

    def campaign_metrics(self, campaign_id: int) -> dict:
        db = self._db()
        response_counts = {
            str(row["response_type"]): int(row["count"])
            for row in db.execute(
                """SELECT response_type, COUNT(DISTINCT sms_message_id) AS count
                   FROM sms_response_events WHERE campaign_id=?
                   GROUP BY response_type""",
                (int(campaign_id),),
            ).fetchall()
        }
        financial = db.execute(
            """SELECT COUNT(DISTINCT root.journey_id) AS journeys,
                      COUNT(DISTINCT observation.accounting_invoice_id) AS invoices,
                      COALESCE(SUM(CASE WHEN observation.id IS NOT NULL
                          THEN observation.billed_amount ELSE 0 END),0) AS billed,
                      COALESCE(SUM(CASE WHEN observation.id IS NOT NULL
                          THEN observation.collected_amount ELSE 0 END),0) AS collected,
                      COUNT(DISTINCT CASE WHEN observation.id IS NULL
                          THEN root.journey_id END) AS pending_financial
               FROM campaign_journey_attributions root
               JOIN campaign_journey_attribution_events attribution
                 ON attribution.attribution_id=root.attribution_id
                AND NOT EXISTS (
                    SELECT 1 FROM campaign_journey_attribution_events child
                    WHERE child.supersedes_event_id=attribution.id
                )
               LEFT JOIN specialist_financial_observations observation
                 ON observation.journey_id=root.journey_id
                AND observation.id=(
                    SELECT latest.id FROM specialist_financial_observations latest
                    WHERE latest.journey_id=root.journey_id
                    ORDER BY latest.observed_at DESC, latest.id DESC LIMIT 1
                )
               WHERE attribution.status='ATTRIBUTED'
                 AND attribution.campaign_id=?""",
            (int(campaign_id),),
        ).fetchone()
        audience = db.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(grp='treated'),0) AS treated,
                      COALESCE(SUM(grp='control'),0) AS control
               FROM campaign_audience_snapshots WHERE campaign_id=?""",
            (int(campaign_id),),
        ).fetchone()
        return {
            "responses": response_counts,
            "positive_responses": sum(
                response_counts.get(key, 0) for key in self.POSITIVE_RESPONSES
            ),
            "attributed_journeys": int(financial["journeys"] or 0),
            "invoices": int(financial["invoices"] or 0),
            "billed": int(financial["billed"] or 0),
            "collected": int(financial["collected"] or 0),
            "pending_financial": int(financial["pending_financial"] or 0),
            "audience_total": int(audience["total"] or 0),
            "audience_treated": int(audience["treated"] or 0),
            "audience_control": int(audience["control"] or 0),
            "measurement_status": "EXPLICIT_RESPONSE_JOURNEY",
        }
