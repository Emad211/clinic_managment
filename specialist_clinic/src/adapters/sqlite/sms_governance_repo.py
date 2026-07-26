"""Repository for immutable SMS consent, purpose and delivery event streams."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_governance_schema import (
    CONSENT_PURPOSES,
    ensure_sms_governance_storage,
)
from src.common.utils import iran_now


class SmsGovernanceConflict(RuntimeError):
    pass


class SmsGovernanceValidationError(ValueError):
    pass


def _hash(payload: dict[str, Any]) -> str:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _time(value: datetime | str | None = None) -> str:
    if value is None:
        current = iran_now()
    elif isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(str(value))
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return current.isoformat(sep=" ", timespec="seconds")


class SmsGovernanceRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def current_consent(self, patient_link_id: int, purpose: str) -> dict | None:
        normalized = str(purpose or "").strip().upper()
        if normalized not in CONSENT_PURPOSES:
            raise SmsGovernanceValidationError("invalid SMS consent purpose")
        return self._row(
            self._db().execute(
                """SELECT * FROM sms_consent_events
                   WHERE patient_link_id=? AND purpose=?
                   ORDER BY recorded_at DESC, id DESC LIMIT 1""",
                (int(patient_link_id), normalized),
            ).fetchone()
        )

    def ensure_patient_defaults(
        self,
        patient_link_id: int,
        *,
        actor_username: str = "system:sms-consent-default",
        commit: bool = True,
    ) -> dict[str, dict]:
        db = self._db()
        patient = db.execute(
            """SELECT id, COALESCE(sms_opt_out,0) AS sms_opt_out,
                      COALESCE(enrolled_at, updated_at,
                               datetime('now','+3 hours','+30 minutes')) AS effective_at
               FROM patient_links WHERE id=?""",
            (int(patient_link_id),),
        ).fetchone()
        if not patient:
            raise LookupError("patient not found")
        output: dict[str, dict] = {}
        for purpose in CONSENT_PURPOSES:
            current = self.current_consent(patient_link_id, purpose)
            if current:
                output[purpose] = current
                continue
            if bool(patient["sms_opt_out"]):
                decision = "REVOKED"
                source = "LEGACY_GLOBAL_OPT_OUT"
            elif purpose == "CARE":
                decision = "GRANTED"
                source = "CARE_RELATIONSHIP_DEFAULT"
            else:
                decision = "REVOKED"
                source = "NO_MARKETING_OPT_IN"
            output[purpose] = self.append_consent(
                patient_link_id=patient_link_id,
                purpose=purpose,
                decision=decision,
                source_code=source,
                actor_username=actor_username,
                actor_user_id=None,
                reason_code=source,
                effective_at=patient["effective_at"],
                idempotency_key=f"sms-consent-default:{patient_link_id}:{purpose}",
                commit=False,
            )
        if commit:
            db.commit()
        return output

    def append_consent(
        self,
        *,
        patient_link_id: int,
        purpose: str,
        decision: str,
        source_code: str,
        actor_username: str,
        actor_user_id: int | None,
        idempotency_key: str,
        effective_at: datetime | str | None = None,
        reason_code: str | None = None,
        note: str | None = None,
        expected_current_event_id: int | None = None,
        commit: bool = True,
    ) -> dict:
        normalized_purpose = str(purpose or "").strip().upper()
        normalized_decision = str(decision or "").strip().upper()
        actor = str(actor_username or "").strip()
        source = str(source_code or "").strip().upper()
        key = str(idempotency_key or "").strip()
        if normalized_purpose not in CONSENT_PURPOSES:
            raise SmsGovernanceValidationError("invalid SMS consent purpose")
        if normalized_decision not in {"GRANTED", "REVOKED"}:
            raise SmsGovernanceValidationError("invalid SMS consent decision")
        if not actor or not source or not key:
            raise SmsGovernanceValidationError(
                "actor, source_code and idempotency_key are required"
            )
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            patient = db.execute(
                "SELECT id FROM patient_links WHERE id=?",
                (int(patient_link_id),),
            ).fetchone()
            if not patient:
                raise LookupError("patient not found")
            existing = db.execute(
                "SELECT * FROM sms_consent_events WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if existing:
                existing = dict(existing)
                if (
                    int(existing["patient_link_id"]) != int(patient_link_id)
                    or existing["purpose"] != normalized_purpose
                    or existing["decision"] != normalized_decision
                ):
                    raise SmsGovernanceConflict(
                        "SMS consent idempotency key belongs to another mutation"
                    )
                if commit:
                    db.commit()
                return existing
            current = self.current_consent(patient_link_id, normalized_purpose)
            current_id = int(current["id"]) if current else None
            if expected_current_event_id is not None and current_id != int(
                expected_current_event_id
            ):
                raise SmsGovernanceConflict("STALE_SMS_CONSENT_STATE")
            if current and current["decision"] == normalized_decision:
                if commit:
                    db.commit()
                return current
            recorded = _time()
            effective = _time(effective_at or recorded)
            if datetime.fromisoformat(recorded) < datetime.fromisoformat(effective):
                raise SmsGovernanceValidationError(
                    "SMS consent effective time cannot be in the future"
                )
            payload = {
                "patient_link_id": int(patient_link_id),
                "purpose": normalized_purpose,
                "decision": normalized_decision,
                "source_code": source,
                "effective_at": effective,
                "recorded_at": recorded,
                "actor_user_id": actor_user_id,
                "actor_username": actor,
                "reason_code": str(reason_code or "").strip() or None,
                "note": str(note or "").strip() or None,
                "idempotency_key": key,
                "supersedes_event_id": current_id,
            }
            cursor = db.execute(
                """INSERT INTO sms_consent_events
                   (patient_link_id, purpose, decision, source_code, effective_at,
                    recorded_at, actor_user_id, actor_username, reason_code, note,
                    idempotency_key, supersedes_event_id, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["patient_link_id"],
                    payload["purpose"],
                    payload["decision"],
                    payload["source_code"],
                    payload["effective_at"],
                    payload["recorded_at"],
                    payload["actor_user_id"],
                    payload["actor_username"],
                    payload["reason_code"],
                    payload["note"],
                    payload["idempotency_key"],
                    payload["supersedes_event_id"],
                    _hash(payload),
                ),
            )
            # Legacy compatibility: the old global flag now mirrors CARE consent only.
            if normalized_purpose == "CARE":
                db.execute(
                    "UPDATE patient_links SET sms_opt_out=? WHERE id=?",
                    (1 if normalized_decision == "REVOKED" else 0, patient_link_id),
                )
            row = db.execute(
                "SELECT * FROM sms_consent_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def consent_summary(self, patient_link_id: int) -> dict[str, dict]:
        self.ensure_patient_defaults(patient_link_id)
        return {
            purpose: self.current_consent(patient_link_id, purpose)
            for purpose in CONSENT_PURPOSES
        }

    def bind_message(
        self,
        *,
        message_id: int,
        patient_link_id: int | None,
        purpose: str,
        consent_event_id: int | None,
        consent_decision: str,
        allowed_at_submission: bool,
        provider_name: str,
        recipient_canonical: str,
        source_policy: str,
        created_by: str,
        commit: bool = True,
    ) -> dict:
        normalized_purpose = str(purpose or "").strip().upper()
        if normalized_purpose not in CONSENT_PURPOSES:
            raise SmsGovernanceValidationError("new SMS messages require CARE or MARKETING")
        provider = str(provider_name or "").strip().lower()
        recipient = str(recipient_canonical or "").strip()
        actor = str(created_by or "").strip()
        if not provider or not recipient or not actor:
            raise SmsGovernanceValidationError(
                "provider, canonical recipient and creator are required"
            )
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            message = db.execute(
                "SELECT id, patient_link_id FROM sms_messages WHERE id=?",
                (int(message_id),),
            ).fetchone()
            if not message:
                raise LookupError("SMS message not found")
            if patient_link_id is not None and message["patient_link_id"] is not None:
                if int(message["patient_link_id"]) != int(patient_link_id):
                    raise SmsGovernanceConflict("SMS message patient mismatch")
            existing = db.execute(
                "SELECT * FROM sms_message_governance WHERE message_id=?",
                (int(message_id),),
            ).fetchone()
            if existing:
                existing = dict(existing)
                if (
                    existing["purpose"] != normalized_purpose
                    or existing["provider_name"] != provider
                    or existing["recipient_canonical"] != recipient
                ):
                    raise SmsGovernanceConflict(
                        "SMS message governance already exists with another identity"
                    )
                if commit:
                    db.commit()
                return existing
            created_at = _time()
            payload = {
                "message_id": int(message_id),
                "patient_link_id": patient_link_id,
                "purpose": normalized_purpose,
                "consent_decision": str(consent_decision).strip().upper(),
                "consent_event_id": consent_event_id,
                "allowed_at_submission": int(bool(allowed_at_submission)),
                "provider_name": provider,
                "recipient_canonical": recipient,
                "source_policy": str(source_policy or "").strip(),
                "created_at": created_at,
                "created_by": actor,
            }
            cursor = db.execute(
                """INSERT INTO sms_message_governance
                   (message_id, patient_link_id, purpose, consent_decision,
                    consent_event_id, allowed_at_submission, provider_name,
                    recipient_canonical, source_policy, created_at, created_by,
                    content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["message_id"],
                    payload["patient_link_id"],
                    payload["purpose"],
                    payload["consent_decision"],
                    payload["consent_event_id"],
                    payload["allowed_at_submission"],
                    payload["provider_name"],
                    payload["recipient_canonical"],
                    payload["source_policy"],
                    payload["created_at"],
                    payload["created_by"],
                    _hash(payload),
                ),
            )
            row = db.execute(
                "SELECT * FROM sms_message_governance WHERE rowid=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def governance_for_message(self, message_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM sms_message_governance WHERE message_id=?",
                (int(message_id),),
            ).fetchone()
        )

    def current_delivery(self, message_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM sms_delivery_events
                   WHERE message_id=? ORDER BY recorded_at DESC, id DESC LIMIT 1""",
                (int(message_id),),
            ).fetchone()
        )

    def append_delivery(
        self,
        *,
        message_id: int,
        provider_name: str,
        status: str,
        source_code: str,
        status_int: int | None = None,
        occurred_at: datetime | str | None = None,
        provider_request_id: str | None = None,
        provider_msgid: str | None = None,
        error_code: str | None = None,
        commit: bool = True,
    ) -> dict:
        provider = str(provider_name or "").strip().lower()
        normalized_status = str(status or "").strip()
        source = str(source_code or "").strip().upper()
        if not provider or not normalized_status:
            raise SmsGovernanceValidationError("provider and delivery status are required")
        if source not in {
            "LEGACY_BACKFILL",
            "SUBMISSION",
            "PROVIDER_POLL",
            "SYSTEM_EXPIRY",
        }:
            raise SmsGovernanceValidationError("invalid delivery event source")
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            message = db.execute(
                "SELECT id FROM sms_messages WHERE id=?",
                (int(message_id),),
            ).fetchone()
            if not message:
                raise LookupError("SMS message not found")
            current = self.current_delivery(message_id)
            if current and (
                current["provider_name"] == provider
                and current["status"] == normalized_status
                and current["status_int"] == status_int
                and (current["provider_msgid"] or None) == (provider_msgid or None)
            ):
                if commit:
                    db.commit()
                return current
            recorded = _time()
            occurred = _time(occurred_at or recorded)
            payload = {
                "message_id": int(message_id),
                "provider_name": provider,
                "status": normalized_status,
                "status_int": status_int,
                "occurred_at": occurred,
                "recorded_at": recorded,
                "source_code": source,
                "provider_request_id": str(provider_request_id or "").strip() or None,
                "provider_msgid": str(provider_msgid or "").strip() or None,
                "error_code": str(error_code or "").strip()[:200] or None,
                "supersedes_event_id": int(current["id"]) if current else None,
            }
            cursor = db.execute(
                """INSERT INTO sms_delivery_events
                   (message_id, provider_name, status, status_int, occurred_at,
                    recorded_at, source_code, provider_request_id, provider_msgid,
                    error_code, supersedes_event_id, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["message_id"],
                    payload["provider_name"],
                    payload["status"],
                    payload["status_int"],
                    payload["occurred_at"],
                    payload["recorded_at"],
                    payload["source_code"],
                    payload["provider_request_id"],
                    payload["provider_msgid"],
                    payload["error_code"],
                    payload["supersedes_event_id"],
                    _hash(payload),
                ),
            )
            row = db.execute(
                "SELECT * FROM sms_delivery_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def delivery_history(self, message_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM sms_delivery_events
                   WHERE message_id=? ORDER BY recorded_at, id""",
                (int(message_id),),
            ).fetchall()
        ]


__all__ = [
    "SmsGovernanceConflict",
    "SmsGovernanceRepository",
    "SmsGovernanceValidationError",
]
