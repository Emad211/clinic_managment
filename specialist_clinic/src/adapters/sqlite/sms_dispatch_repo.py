"""Atomic governed SMS submission and provider-affine delivery projection.

`sms_messages` remains the compatibility read model. Every new mutation also appends an
immutable delivery event and requires an immutable purpose/consent snapshot.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.sms_governance_repo import SmsGovernanceRepository
from src.adapters.sqlite.sms_governance_schema import ensure_sms_governance_storage
from src.common.utils import iran_now


TERMINAL_DELIVERY = frozenset(
    {
        "Delivered",
        "NumberBlackListed",
        "OperatorBlackList",
        "Canceled",
        "Failed",
        "Undelivered",
        "StatusUnknown",
        "SubmissionUnknown",
    }
)
IN_FLIGHT_DELIVERY = frozenset(
    {
        "Accepted",
        "Queued",
        "Scheduled",
        "PendingApproval",
        "WaitingForSend",
        "Sending",
        "SendToOperator",
        "Sent",
    }
)


class SmsDispatchConflict(RuntimeError):
    pass


class SmsDailyCapExceeded(RuntimeError):
    pass


class SmsDispatchRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def get(self, message_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM sms_messages WHERE id=?",
                (int(message_id),),
            ).fetchone()
        )

    def get_by_idempotency(self, key: str) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM sms_messages WHERE idempotency_key=?",
                (str(key),),
            ).fetchone()
        )

    def create_message(
        self,
        *,
        campaign_id: int | None,
        patient_link_id: int,
        recipient: str,
        body: str,
        provider_name: str,
        idempotency_key: str,
        source_type: str,
        source_ref: str | None,
        purpose: str,
        consent_event_id: int,
        consent_decision: str,
        source_policy: str,
        created_by: str,
        daily_cap: int | None = None,
        commit: bool = True,
    ) -> tuple[int, bool]:
        db = self._db()
        ensure_sms_governance_storage(db)
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.get_by_idempotency(idempotency_key)
            if existing:
                governance = SmsGovernanceRepository(db).governance_for_message(
                    int(existing["id"])
                )
                if not governance:
                    raise SmsDispatchConflict(
                        "existing SMS message has no governance snapshot"
                    )
                expected = (
                    int(patient_link_id),
                    str(recipient),
                    str(provider_name).lower(),
                    str(purpose).upper(),
                )
                actual = (
                    int(existing["patient_link_id"]),
                    str(governance["recipient_canonical"]),
                    str(governance["provider_name"]),
                    str(governance["purpose"]),
                )
                if actual != expected:
                    raise SmsDispatchConflict(
                        "SMS idempotency key belongs to another governed message"
                    )
                if commit:
                    db.commit()
                return int(existing["id"]), False

            if daily_cap is not None:
                used = db.execute(
                    """SELECT COUNT(*) AS c
                       FROM sms_messages
                       WHERE patient_link_id=?
                         AND (
                               status IN ('pending','accepted','delivered','sent')
                               OR delivery_status IN (
                                   'Queued','Submitting','SubmissionUnknown'
                               )
                         )
                         AND date(COALESCE(sent_at,last_attempt_at,created_at))
                             = date('now','+3 hours','+30 minutes')""",
                    (int(patient_link_id),),
                ).fetchone()["c"]
                if int(used) >= int(daily_cap):
                    raise SmsDailyCapExceeded("daily_cap")

            cursor = db.execute(
                """INSERT INTO sms_messages
                   (campaign_id, patient_link_id, recipient, body, status,
                    provider, idempotency_key, delivery_status, retryable,
                    source_type, source_ref)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?, 'Queued', 1, ?, ?)""",
                (
                    campaign_id,
                    int(patient_link_id),
                    str(recipient),
                    str(body),
                    str(provider_name).strip().lower(),
                    str(idempotency_key),
                    str(source_type or "manual"),
                    source_ref,
                ),
            )
            message_id = int(cursor.lastrowid)
            SmsGovernanceRepository(db).bind_message(
                message_id=message_id,
                patient_link_id=int(patient_link_id),
                purpose=str(purpose).upper(),
                consent_event_id=int(consent_event_id),
                consent_decision=str(consent_decision).upper(),
                allowed_at_submission=True,
                provider_name=str(provider_name).lower(),
                recipient_canonical=str(recipient),
                source_policy=str(source_policy),
                created_by=str(created_by),
                commit=False,
            )
            SmsGovernanceRepository(db).append_delivery(
                message_id=message_id,
                provider_name=str(provider_name).lower(),
                status="Queued",
                source_code="SUBMISSION",
                commit=False,
            )
            if commit:
                db.commit()
            return message_id, True
        except Exception:
            if commit:
                db.rollback()
            raise

    def claim_submission(self, message_id: int, *, commit: bool = True) -> bool:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            cursor = db.execute(
                """UPDATE sms_messages
                   SET delivery_status='Submitting', retryable=0,
                       send_attempts=send_attempts+1,
                       last_attempt_at=datetime('now','+3 hours','+30 minutes')
                   WHERE id=?
                     AND delivery_status IN ('Queued','RetryableFailure')
                     AND provider_request_id IS NULL
                     AND provider_msgid IS NULL
                     AND EXISTS (
                         SELECT 1 FROM sms_message_governance governance
                         WHERE governance.message_id=sms_messages.id
                           AND governance.allowed_at_submission=1
                           AND governance.consent_decision='GRANTED'
                           AND governance.provider_name=sms_messages.provider
                     )""",
                (int(message_id),),
            )
            if cursor.rowcount == 1:
                message = self.get(message_id)
                SmsGovernanceRepository(db).append_delivery(
                    message_id=message_id,
                    provider_name=message["provider"],
                    status="Submitting",
                    source_code="SUBMISSION",
                    commit=False,
                )
            if commit:
                db.commit()
            return cursor.rowcount == 1
        except Exception:
            if commit:
                db.rollback()
            raise

    def record_submission(
        self,
        message_id: int,
        *,
        ok: bool,
        pending: bool = False,
        provider_request_id: str | None = None,
        provider_msgid: str | None = None,
        delivery_status: str | None = None,
        delivery_status_int: int | None = None,
        error: str | None = None,
        retryable: bool = False,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            message = self.get(message_id)
            if not message:
                raise LookupError("SMS message not found")
            now = iran_now().strftime("%Y-%m-%d %H:%M:%S")
            if ok:
                local_status = "accepted"
                status = delivery_status or "Accepted"
                next_check = now
            elif pending:
                local_status = "pending"
                status = delivery_status or "SubmissionUnknown"
                next_check = None
            elif retryable:
                local_status = "failed"
                status = delivery_status or "RetryableFailure"
                next_check = None
            else:
                local_status = "failed"
                status = delivery_status or "Failed"
                next_check = None
            db.execute(
                """UPDATE sms_messages
                   SET status=?, provider_request_id=?, provider_msgid=?,
                       delivery_status=?, delivery_status_int=?, error=?,
                       retryable=?, sent_at=CASE WHEN ?='accepted' THEN ? ELSE sent_at END,
                       next_status_check_at=?
                   WHERE id=?""",
                (
                    local_status,
                    provider_request_id,
                    provider_msgid,
                    status,
                    delivery_status_int,
                    error,
                    int(bool(retryable)),
                    local_status,
                    now,
                    next_check,
                    int(message_id),
                ),
            )
            event = SmsGovernanceRepository(db).append_delivery(
                message_id=message_id,
                provider_name=message["provider"],
                status=status,
                status_int=delivery_status_int,
                source_code="SUBMISSION",
                provider_request_id=provider_request_id,
                provider_msgid=provider_msgid,
                error_code=error,
                commit=False,
            )
            if commit:
                db.commit()
            return event
        except Exception:
            if commit:
                db.rollback()
            raise

    def due_delivery_messages(
        self,
        *,
        limit: int = 100,
        message_ids: list[int] | None = None,
        campaign_id: int | None = None,
    ) -> list[dict]:
        clauses = [
            "message.provider IN ('mediana','kavenegar')",
            "message.delivery_status NOT IN ("
            "'Delivered','NumberBlackListed','OperatorBlackList','Canceled',"
            "'Failed','Undelivered','StatusUnknown','SubmissionUnknown')",
            "(message.provider_request_id IS NOT NULL OR message.provider_msgid IS NOT NULL)",
            "governance.allowed_at_submission=1",
            "governance.provider_name=message.provider",
        ]
        params: list[object] = []
        if message_ids:
            marks = ",".join("?" for _ in message_ids)
            clauses.append(f"message.id IN ({marks})")
            params.extend(int(value) for value in message_ids)
        elif campaign_id:
            clauses.append("message.campaign_id=?")
            params.append(int(campaign_id))
        else:
            clauses.append(
                "(message.next_status_check_at IS NULL OR "
                "message.next_status_check_at<=datetime('now','+3 hours','+30 minutes'))"
            )
        params.append(int(limit))
        rows = self._db().execute(
            f"""SELECT message.*, governance.purpose,
                       governance.recipient_canonical
                FROM sms_messages message
                JOIN sms_message_governance governance
                  ON governance.message_id=message.id
                WHERE {' AND '.join(clauses)}
                ORDER BY message.id LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def record_delivery(
        self,
        message_id: int,
        *,
        status: str,
        status_int: int | None = None,
        delivered_at: str | None = None,
        provider_msgid: str | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            message = self.get(message_id)
            if not message:
                raise LookupError("SMS message not found")
            terminal = status in TERMINAL_DELIVERY
            now = iran_now()
            created = message.get("sent_at") or message.get("created_at")
            age = 0.0
            if created:
                try:
                    age = (now - datetime.fromisoformat(str(created))).total_seconds()
                except (ValueError, TypeError):
                    age = 0.0
            if terminal:
                next_check = None
            elif age < 3600:
                next_check = (now + timedelta(minutes=2)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            elif age < 86400:
                next_check = (now + timedelta(minutes=10)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            else:
                next_check = (now + timedelta(hours=1)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            delivered = delivered_at or (
                now.strftime("%Y-%m-%d %H:%M:%S")
                if status == "Delivered"
                else None
            )
            db.execute(
                """UPDATE sms_messages
                   SET delivery_status=?, delivery_status_int=?,
                       delivery_checked_at=?, next_status_check_at=?,
                       delivered_at=COALESCE(?, delivered_at),
                       provider_msgid=COALESCE(?, provider_msgid), retryable=0,
                       status=CASE WHEN ?='Delivered' THEN 'delivered' ELSE status END
                   WHERE id=?""",
                (
                    status,
                    status_int,
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    next_check,
                    delivered,
                    provider_msgid,
                    status,
                    int(message_id),
                ),
            )
            event = SmsGovernanceRepository(db).append_delivery(
                message_id=message_id,
                provider_name=message["provider"],
                status=status,
                status_int=status_int,
                source_code="PROVIDER_POLL",
                provider_request_id=message.get("provider_request_id"),
                provider_msgid=provider_msgid or message.get("provider_msgid"),
                occurred_at=delivered_at or None,
                commit=False,
            )
            if commit:
                db.commit()
            return event
        except Exception:
            if commit:
                db.rollback()
            raise

    def expire_stale_delivery(self, *, hours: int = 72) -> list[int]:
        db = self._db()
        rows = db.execute(
            """SELECT message.id, message.campaign_id, message.provider
               FROM sms_messages message
               JOIN sms_message_governance governance
                 ON governance.message_id=message.id
               WHERE message.provider IN ('mediana','kavenegar')
                 AND message.sent_at < datetime(
                     'now','+3 hours','+30 minutes', ?
                 )
                 AND message.delivery_status NOT IN (
                     'Delivered','NumberBlackListed','OperatorBlackList',
                     'Canceled','Failed','Undelivered','StatusUnknown',
                     'SubmissionUnknown'
                 )
                 AND governance.allowed_at_submission=1""",
            (f"-{int(hours)} hours",),
        ).fetchall()
        affected: list[int] = []
        for row in rows:
            self.record_delivery(
                int(row["id"]),
                status="StatusUnknown",
                commit=False,
            )
            if row["campaign_id"]:
                affected.append(int(row["campaign_id"]))
        db.commit()
        return affected


__all__ = [
    "IN_FLIGHT_DELIVERY",
    "TERMINAL_DELIVERY",
    "SmsDispatchConflict",
    "SmsDailyCapExceeded",
    "SmsDispatchRepository",
]
