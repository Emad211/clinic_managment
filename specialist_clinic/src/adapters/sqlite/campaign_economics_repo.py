"""Repository for the immutable A6 campaign-economics contract."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import sqlite3
from typing import Any

from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class CampaignEconomicsConflict(RuntimeError):
    pass


class CampaignEconomicsValidationError(ValueError):
    pass


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


def _time(value: datetime | str | None = None) -> str:
    current = value or iran_now()
    if isinstance(current, str):
        parsed = datetime.fromisoformat(current.replace("Z", "+00:00"))
    else:
        parsed = current
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


_EVENT_BY_STATUS = {
    "DRAFT": "CREATED",
    "SCHEDULED": "SCHEDULED",
    "PREPARING": "PREPARING",
    "SENDING": "SENDING",
    "AWAITING_DELIVERY": "AWAITING_DELIVERY",
    "COMPLETED": "COMPLETED",
    "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
    "ENTERED_IN_ERROR": "ENTERED_IN_ERROR",
}
_COMPAT_STATUS = {
    "DRAFT": "draft",
    "SCHEDULED": "scheduled",
    "PREPARING": "sending",
    "SENDING": "sending",
    "AWAITING_DELIVERY": "sending",
    "COMPLETED": "done",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
    "ENTERED_IN_ERROR": "failed",
}
_TERMINAL_DELIVERY = {
    "Delivered",
    "NumberBlackListed",
    "OperatorBlackList",
    "Canceled",
    "Failed",
    "Undelivered",
    "StatusUnknown",
    "SubmissionUnknown",
}
_FAILURE_DELIVERY = {
    "NumberBlackListed",
    "OperatorBlackList",
    "Canceled",
    "Failed",
    "Undelivered",
    "StatusUnknown",
    "SubmissionUnknown",
}


class CampaignEconomicsRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        db = self._connection or get_db()
        installed = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='campaign_lifecycle_events'"
        ).fetchone()
        if not installed:
            if db.in_transaction:
                raise RuntimeError(
                    "campaign economics storage is missing inside a caller transaction"
                )
            ensure_campaign_economics_storage(db)
        return db

    @staticmethod
    def _row(row) -> dict | None:
        return dict(row) if row else None

    def campaign(self, campaign_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM sms_campaigns WHERE id=?",
                (int(campaign_id),),
            ).fetchone()
        )

    # ------------------------------------------------------------------ lifecycle
    def current_lifecycle(self, campaign_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM campaign_lifecycle_events
                   WHERE campaign_id=?
                   ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (int(campaign_id),),
            ).fetchone()
        )

    def lifecycle_history(self, campaign_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM campaign_lifecycle_events
                   WHERE campaign_id=? ORDER BY recorded_at,id""",
                (int(campaign_id),),
            ).fetchall()
        ]

    def append_lifecycle(
        self,
        *,
        campaign_id: int,
        status: str,
        actor_username: str,
        idempotency_key: str,
        execution_id: str | None = None,
        outcome_code: str | None = None,
        note: str | None = None,
        effective_at: datetime | str | None = None,
        expected_current_event_id: int | None = None,
        commit: bool = True,
    ) -> dict:
        normalized = str(status or "").strip().upper()
        if normalized not in _EVENT_BY_STATUS:
            raise CampaignEconomicsValidationError("invalid campaign lifecycle status")
        actor = str(actor_username or "").strip()
        key = str(idempotency_key or "").strip()
        if not actor or not key:
            raise CampaignEconomicsValidationError(
                "campaign lifecycle actor and idempotency key are required"
            )
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            campaign = self.campaign(campaign_id)
            if not campaign:
                raise LookupError("campaign not found")
            existing = db.execute(
                "SELECT * FROM campaign_lifecycle_events WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if existing:
                existing = dict(existing)
                if (
                    int(existing["campaign_id"]) != int(campaign_id)
                    or existing["status"] != normalized
                ):
                    raise CampaignEconomicsConflict(
                        "campaign lifecycle idempotency key belongs to another event"
                    )
                if commit:
                    db.commit()
                return existing
            current = self.current_lifecycle(campaign_id)
            current_id = int(current["id"]) if current else None
            if expected_current_event_id is not None and current_id != int(
                expected_current_event_id
            ):
                raise CampaignEconomicsConflict("STALE_CAMPAIGN_LIFECYCLE")
            if current and current["status"] == normalized:
                if commit:
                    db.commit()
                return current
            inherited_execution = execution_id or (
                current.get("execution_id") if current else None
            )
            recorded = _time()
            effective = _time(effective_at or recorded)
            payload = {
                "campaign_id": int(campaign_id),
                "event_type": _EVENT_BY_STATUS[normalized],
                "status": normalized,
                "execution_id": inherited_execution,
                "outcome_code": str(outcome_code or "").strip() or None,
                "effective_at": effective,
                "recorded_at": recorded,
                "actor_username": actor,
                "note": str(note or "").strip() or None,
                "idempotency_key": key,
                "supersedes_event_id": current_id,
            }
            cursor = db.execute(
                """INSERT INTO campaign_lifecycle_events
                   (campaign_id,event_type,status,execution_id,outcome_code,
                    effective_at,recorded_at,actor_username,note,idempotency_key,
                    supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            db.execute(
                "UPDATE sms_campaigns SET status=? WHERE id=?",
                (_COMPAT_STATUS[normalized], int(campaign_id)),
            )
            row = db.execute(
                "SELECT * FROM campaign_lifecycle_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    # ------------------------------------------------------------------ audience
    def audience_snapshot(self, campaign_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                "SELECT * FROM campaign_audience_snapshots WHERE campaign_id=?",
                (int(campaign_id),),
            ).fetchone()
        )

    def audience_members(
        self,
        campaign_id: int,
        *,
        assignment: str | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT member.*, patient.full_name, patient.phone_number "
            "FROM campaign_audience_members member "
            "JOIN patient_links patient ON patient.id=member.patient_link_id "
            "WHERE member.campaign_id=?"
        )
        params: list[object] = [int(campaign_id)]
        if assignment:
            sql += " AND member.assignment=?"
            params.append(str(assignment).upper())
        sql += " ORDER BY member.assigned_rank,member.id"
        return [dict(row) for row in self._db().execute(sql, params).fetchall()]

    def create_audience_snapshot(
        self,
        *,
        campaign_id: int,
        execution_id: str,
        source_code: str,
        segment_key: str,
        purpose: str,
        holdout_percent: int,
        random_seed: str,
        members: list[dict],
        actor_username: str,
        created_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.audience_snapshot(campaign_id)
            if existing:
                if str(existing["execution_id"]) != str(execution_id):
                    raise CampaignEconomicsConflict(
                        "campaign audience is already frozen for another execution"
                    )
                if commit:
                    db.commit()
                return existing
            if not self.campaign(campaign_id):
                raise LookupError("campaign not found")
            normalized_source = str(source_code or "").strip().upper()
            if normalized_source not in {"NEW_FROZEN", "LEGACY_BACKFILL_UNTRUSTED"}:
                raise CampaignEconomicsValidationError("invalid audience snapshot source")
            seen: set[int] = set()
            for member in members:
                patient_id = int(member["patient_link_id"])
                if patient_id in seen:
                    raise CampaignEconomicsValidationError(
                        "campaign audience contains duplicate patient"
                    )
                seen.add(patient_id)
            candidate_count = len(members)
            eligible_count = sum(
                1 for member in members if member["assignment"] in {"TREATED", "CONTROL"}
            )
            treated_count = sum(1 for member in members if member["assignment"] == "TREATED")
            control_count = sum(1 for member in members if member["assignment"] == "CONTROL")
            excluded_count = candidate_count - eligible_count
            snapshot_id = "audience_" + hashlib.sha256(
                f"{campaign_id}:{execution_id}:{random_seed}".encode("utf-8")
            ).hexdigest()[:32]
            created = _time(created_at)
            root = {
                "snapshot_id": snapshot_id,
                "campaign_id": int(campaign_id),
                "execution_id": str(execution_id),
                "snapshot_version": 1,
                "source_code": normalized_source,
                "segment_key": str(segment_key),
                "purpose": str(purpose).upper(),
                "holdout_percent": int(holdout_percent),
                "random_seed": str(random_seed),
                "candidate_count": candidate_count,
                "eligible_count": eligible_count,
                "treated_count": treated_count,
                "control_count": control_count,
                "excluded_count": excluded_count,
                "created_at": created,
                "created_by": str(actor_username),
            }
            db.execute(
                """INSERT INTO campaign_audience_snapshots
                   (snapshot_id,campaign_id,execution_id,snapshot_version,source_code,
                    segment_key,purpose,holdout_percent,random_seed,candidate_count,
                    eligible_count,treated_count,control_count,excluded_count,
                    created_at,created_by,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*root.values(), _hash(root)),
            )
            for rank, source in enumerate(members, start=1):
                member = {
                    "snapshot_id": snapshot_id,
                    "campaign_id": int(campaign_id),
                    "patient_link_id": int(source["patient_link_id"]),
                    "accounting_patient_id": source.get("accounting_patient_id"),
                    "assignment": str(source["assignment"]).upper(),
                    "eligibility": str(source["eligibility"]).upper(),
                    "finance_scope": str(source["finance_scope"]).upper(),
                    "consent_event_id": source.get("consent_event_id"),
                    "consent_decision": str(source["consent_decision"]).upper(),
                    "recipient_canonical": source.get("recipient_canonical"),
                    "assigned_rank": int(source.get("assigned_rank") or rank),
                    "exclusion_reason": (
                        str(source.get("exclusion_reason") or "").strip() or None
                    ),
                }
                db.execute(
                    """INSERT INTO campaign_audience_members
                       (snapshot_id,campaign_id,patient_link_id,accounting_patient_id,
                        assignment,eligibility,finance_scope,consent_event_id,
                        consent_decision,recipient_canonical,assigned_rank,
                        exclusion_reason,content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*member.values(), _hash(member)),
                )
            # Compatibility read model only; the immutable A6 tables are authoritative.
            for member in members:
                if member["assignment"] not in {"TREATED", "CONTROL"}:
                    continue
                db.execute(
                    """INSERT INTO campaign_audience
                       (campaign_id,patient_link_id,accounting_patient_id,grp)
                       SELECT ?,?,?,? WHERE NOT EXISTS (
                           SELECT 1 FROM campaign_audience old
                           WHERE old.campaign_id=? AND old.patient_link_id=?
                       )""",
                    (
                        int(campaign_id), int(member["patient_link_id"]),
                        member.get("accounting_patient_id"),
                        str(member["assignment"]).lower(),
                        int(campaign_id), int(member["patient_link_id"]),
                    ),
                )
            if commit:
                db.commit()
            return self.audience_snapshot(campaign_id)
        except Exception:
            if commit:
                db.rollback()
            raise

    def audience_summary(self, campaign_id: int) -> dict:
        snapshot = self.audience_snapshot(campaign_id)
        if not snapshot:
            return {
                "frozen": False,
                "source_code": None,
                "candidate_count": 0,
                "eligible_count": 0,
                "treated_count": 0,
                "control_count": 0,
                "excluded_count": 0,
            }
        return {
            "frozen": True,
            **{
                key: snapshot[key]
                for key in (
                    "snapshot_id", "source_code", "candidate_count",
                    "eligible_count", "treated_count", "control_count",
                    "excluded_count", "created_at",
                )
            },
        }

    # ------------------------------------------------------------------ responses
    def current_response(self, campaign_id: int, patient_link_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM campaign_response_events
                   WHERE campaign_id=? AND patient_link_id=?
                   ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (int(campaign_id), int(patient_link_id)),
            ).fetchone()
        )

    def record_response(
        self,
        *,
        campaign_id: int,
        patient_link_id: int,
        response_type: str,
        evidence_type: str,
        actor_username: str,
        idempotency_key: str,
        message_id: int | None = None,
        evidence_ref: str | None = None,
        occurred_at: datetime | str | None = None,
        note: str | None = None,
        expected_current_event_id: int | None = None,
        commit: bool = True,
    ) -> dict:
        response = str(response_type or "").strip().upper()
        evidence = str(evidence_type or "").strip().upper()
        if response not in {"POSITIVE", "NEGATIVE", "NO_RESPONSE", "OPT_OUT"}:
            raise CampaignEconomicsValidationError("invalid campaign response type")
        if evidence not in {
            "INBOUND_REPLY", "PATIENT_STATED", "STAFF_PHONE_CALL", "LEGACY_UNKNOWN"
        }:
            raise CampaignEconomicsValidationError("invalid campaign response evidence")
        actor = str(actor_username or "").strip()
        key = str(idempotency_key or "").strip()
        if not actor or not key:
            raise CampaignEconomicsValidationError(
                "response actor and idempotency key are required"
            )
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute(
                "SELECT * FROM campaign_response_events WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if existing:
                existing = dict(existing)
                if (
                    int(existing["campaign_id"]) != int(campaign_id)
                    or int(existing["patient_link_id"]) != int(patient_link_id)
                    or existing["response_type"] != response
                ):
                    raise CampaignEconomicsConflict(
                        "campaign response idempotency key belongs to another event"
                    )
                if commit:
                    db.commit()
                return existing
            current = self.current_response(campaign_id, patient_link_id)
            current_id = int(current["id"]) if current else None
            if expected_current_event_id is not None and current_id != int(
                expected_current_event_id
            ):
                raise CampaignEconomicsConflict("STALE_CAMPAIGN_RESPONSE")
            recorded = _time()
            occurred = _time(occurred_at or recorded)
            payload = {
                "campaign_id": int(campaign_id),
                "patient_link_id": int(patient_link_id),
                "message_id": int(message_id) if message_id is not None else None,
                "response_type": response,
                "evidence_type": evidence,
                "evidence_ref": str(evidence_ref or "").strip() or None,
                "occurred_at": occurred,
                "recorded_at": recorded,
                "actor_username": actor,
                "note": str(note or "").strip() or None,
                "idempotency_key": key,
                "supersedes_event_id": current_id,
            }
            cursor = db.execute(
                """INSERT INTO campaign_response_events
                   (campaign_id,patient_link_id,message_id,response_type,
                    evidence_type,evidence_ref,occurred_at,recorded_at,
                    actor_username,note,idempotency_key,supersedes_event_id,
                    content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            if response == "OPT_OUT":
                # Purpose-specific consent revocation is performed by the application
                # service in the same caller transaction; this repository remains focused.
                pass
            row = db.execute(
                "SELECT * FROM campaign_response_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def response_rows(self, campaign_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT response.*, patient.full_name,
                      message.delivery_status, message.recipient
               FROM campaign_response_events response
               JOIN patient_links patient ON patient.id=response.patient_link_id
               LEFT JOIN sms_messages message ON message.id=response.message_id
               WHERE response.campaign_id=?
                 AND response.id=(
                     SELECT head.id FROM campaign_response_events head
                     WHERE head.campaign_id=response.campaign_id
                       AND head.patient_link_id=response.patient_link_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 )
               ORDER BY response.recorded_at DESC,response.id DESC""",
            (int(campaign_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def positive_response_options(self, patient_link_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT response.*, campaign.name AS campaign_name,
                      message.delivery_status
               FROM campaign_response_events response
               JOIN sms_campaigns campaign ON campaign.id=response.campaign_id
               LEFT JOIN sms_messages message ON message.id=response.message_id
               WHERE response.patient_link_id=?
                 AND response.response_type='POSITIVE'
                 AND response.id=(
                     SELECT head.id FROM campaign_response_events head
                     WHERE head.campaign_id=response.campaign_id
                       AND head.patient_link_id=response.patient_link_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM campaign_journey_attribution_events attribution
                     WHERE attribution.response_event_id=response.id
                       AND attribution.status='ATTRIBUTED'
                       AND attribution.id=(
                           SELECT current.id FROM campaign_journey_attribution_events current
                           WHERE current.journey_id=attribution.journey_id
                           ORDER BY current.recorded_at DESC,current.id DESC LIMIT 1
                       )
                 )
               ORDER BY response.recorded_at DESC,response.id DESC""",
            (int(patient_link_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ journey attribution
    def current_journey_attribution(self, journey_id: str) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM campaign_journey_attribution_events
                   WHERE journey_id=?
                   ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (str(journey_id),),
            ).fetchone()
        )

    def attribute_journey(
        self,
        *,
        journey_id: str,
        response_event_id: int,
        actor_username: str,
        idempotency_key: str,
        reason_code: str = "EXPLICIT_PATIENT_RESPONSE",
        effective_at: datetime | str | None = None,
        note: str | None = None,
        expected_current_event_id: int | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            response = db.execute(
                "SELECT * FROM campaign_response_events WHERE id=?",
                (int(response_event_id),),
            ).fetchone()
            if not response or response["response_type"] != "POSITIVE":
                raise CampaignEconomicsValidationError(
                    "journey attribution requires a positive response event"
                )
            response = dict(response)
            latest_response = self.current_response(
                int(response["campaign_id"]), int(response["patient_link_id"])
            )
            if not latest_response or int(latest_response["id"]) != int(response_event_id):
                raise CampaignEconomicsConflict(
                    "journey attribution requires the latest campaign response"
                )
            journey = db.execute(
                "SELECT * FROM care_journeys WHERE journey_id=?",
                (str(journey_id),),
            ).fetchone()
            if not journey or int(journey["patient_link_id"]) != int(
                response["patient_link_id"]
            ):
                raise CampaignEconomicsConflict("campaign journey patient mismatch")
            other = db.execute(
                """SELECT attribution.journey_id
                   FROM campaign_journey_attribution_events attribution
                   WHERE attribution.response_event_id=?
                     AND attribution.status='ATTRIBUTED'
                     AND attribution.id=(
                         SELECT head.id FROM campaign_journey_attribution_events head
                         WHERE head.journey_id=attribution.journey_id
                         ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                     ) AND attribution.journey_id<>?
                   LIMIT 1""",
                (int(response_event_id), str(journey_id)),
            ).fetchone()
            if other:
                raise CampaignEconomicsConflict(
                    "campaign response is already attributed to another journey"
                )
            key = str(idempotency_key or "").strip()
            actor = str(actor_username or "").strip()
            if not key or not actor:
                raise CampaignEconomicsValidationError(
                    "attribution actor and idempotency key are required"
                )
            existing = db.execute(
                """SELECT * FROM campaign_journey_attribution_events
                   WHERE idempotency_key=?""",
                (key,),
            ).fetchone()
            if existing:
                if commit:
                    db.commit()
                return dict(existing)
            current = self.current_journey_attribution(journey_id)
            current_id = int(current["id"]) if current else None
            if expected_current_event_id is not None and current_id != int(
                expected_current_event_id
            ):
                raise CampaignEconomicsConflict("STALE_CAMPAIGN_ATTRIBUTION")
            if current and current["status"] == "ATTRIBUTED":
                if (
                    int(current["campaign_id"]) == int(response["campaign_id"])
                    and int(current["response_event_id"]) == int(response_event_id)
                ):
                    if commit:
                        db.commit()
                    return current
                if not str(note or "").strip():
                    raise CampaignEconomicsValidationError(
                        "reattribution requires an explanatory note"
                    )
                event_type = "REATTRIBUTED"
            else:
                event_type = "ATTRIBUTED" if current is None else "REATTRIBUTED"
                if current is not None and not str(note or "").strip():
                    raise CampaignEconomicsValidationError(
                        "corrected attribution requires an explanatory note"
                    )
            recorded = _time()
            effective = _time(effective_at or recorded)
            payload = {
                "journey_id": str(journey_id),
                "campaign_id": int(response["campaign_id"]),
                "patient_link_id": int(response["patient_link_id"]),
                "response_event_id": int(response_event_id),
                "event_type": event_type,
                "status": "ATTRIBUTED",
                "reason_code": str(reason_code or "EXPLICIT_PATIENT_RESPONSE"),
                "effective_at": effective,
                "recorded_at": recorded,
                "actor_username": actor,
                "note": str(note or "").strip() or None,
                "idempotency_key": key,
                "supersedes_event_id": current_id,
            }
            cursor = db.execute(
                """INSERT INTO campaign_journey_attribution_events
                   (journey_id,campaign_id,patient_link_id,response_event_id,
                    event_type,status,reason_code,effective_at,recorded_at,
                    actor_username,note,idempotency_key,supersedes_event_id,
                    content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                "SELECT * FROM campaign_journey_attribution_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def revoke_journey_attribution(
        self,
        *,
        journey_id: str,
        actor_username: str,
        idempotency_key: str,
        note: str,
        expected_current_event_id: int,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            current = self.current_journey_attribution(journey_id)
            if not current or current["status"] != "ATTRIBUTED":
                raise CampaignEconomicsConflict("journey has no active campaign attribution")
            if int(current["id"]) != int(expected_current_event_id):
                raise CampaignEconomicsConflict("STALE_CAMPAIGN_ATTRIBUTION")
            recorded = _time()
            payload = {
                "journey_id": str(journey_id),
                "campaign_id": int(current["campaign_id"]),
                "patient_link_id": int(current["patient_link_id"]),
                "response_event_id": int(current["response_event_id"]),
                "event_type": "REVOKED",
                "status": "REVOKED",
                "reason_code": "MANUAL_CORRECTION",
                "effective_at": recorded,
                "recorded_at": recorded,
                "actor_username": str(actor_username),
                "note": str(note or "").strip(),
                "idempotency_key": str(idempotency_key),
                "supersedes_event_id": int(current["id"]),
            }
            cursor = db.execute(
                """INSERT INTO campaign_journey_attribution_events
                   (journey_id,campaign_id,patient_link_id,response_event_id,
                    event_type,status,reason_code,effective_at,recorded_at,
                    actor_username,note,idempotency_key,supersedes_event_id,
                    content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                "SELECT * FROM campaign_journey_attribution_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    def current_campaign_attributions(self, campaign_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT attribution.*, journey.origin_type, journey.origin_ref,
                      CASE WHEN attribution.response_event_id=(
                          SELECT latest_response.id
                          FROM campaign_response_events latest_response
                          WHERE latest_response.campaign_id=attribution.campaign_id
                            AND latest_response.patient_link_id=attribution.patient_link_id
                          ORDER BY latest_response.recorded_at DESC,
                                   latest_response.id DESC LIMIT 1
                      ) AND EXISTS (
                          SELECT 1 FROM campaign_response_events response
                          WHERE response.id=attribution.response_event_id
                            AND response.response_type='POSITIVE'
                      ) THEN 1 ELSE 0 END AS response_current_positive
               FROM campaign_journey_attribution_events attribution
               JOIN care_journeys journey ON journey.journey_id=attribution.journey_id
               WHERE attribution.campaign_id=?
                 AND attribution.id=(
                     SELECT head.id FROM campaign_journey_attribution_events head
                     WHERE head.journey_id=attribution.journey_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 ) AND attribution.status='ATTRIBUTED'
               ORDER BY attribution.recorded_at,attribution.id""",
            (int(campaign_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ wallet grant stream
    def current_wallet_grant(self, campaign_id: int, patient_link_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM campaign_wallet_grant_events
                   WHERE campaign_id=? AND patient_link_id=?
                   ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (int(campaign_id), int(patient_link_id)),
            ).fetchone()
        )

    def append_wallet_grant_event(
        self,
        *,
        campaign_id: int,
        patient_link_id: int,
        message_id: int,
        event_type: str,
        amount: int,
        actor_username: str,
        idempotency_key: str,
        wallet_transaction_id: int | None = None,
        compensation_transaction_id: int | None = None,
        reason_code: str,
        note: str | None = None,
        occurred_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict:
        event = str(event_type or "").strip().upper()
        status_by_event = {
            "GRANTED": "ACTIVE",
            "GRANT_REVIEW_REQUIRED": "REVIEW_REQUIRED",
            "GRANT_NOT_REQUIRED": "NO_GRANT",
            "COMPENSATED": "COMPENSATED",
            "COMPENSATION_REVIEW_REQUIRED": "REVIEW_REQUIRED",
            "ENTERED_IN_ERROR": "ENTERED_IN_ERROR",
        }
        if event not in status_by_event:
            raise CampaignEconomicsValidationError("invalid campaign wallet event")
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            key = str(idempotency_key or "").strip()
            existing = db.execute(
                "SELECT * FROM campaign_wallet_grant_events WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if existing:
                if commit:
                    db.commit()
                return dict(existing)
            current = self.current_wallet_grant(campaign_id, patient_link_id)
            if current and event == "GRANT_REVIEW_REQUIRED":
                if current["status"] == "REVIEW_REQUIRED":
                    if commit:
                        db.commit()
                    return current
                raise CampaignEconomicsConflict("wallet grant stream already exists")
            if current and event == "GRANTED":
                if current["status"] == "ACTIVE":
                    if commit:
                        db.commit()
                    return current
                if current["status"] != "REVIEW_REQUIRED":
                    raise CampaignEconomicsConflict("wallet grant stream already exists")
            if current and event == "GRANT_NOT_REQUIRED":
                if current["status"] == "NO_GRANT":
                    if commit:
                        db.commit()
                    return current
                if current["status"] != "REVIEW_REQUIRED":
                    raise CampaignEconomicsConflict("wallet grant stream is not under review")
            recorded = _time()
            occurred = _time(occurred_at or recorded)
            payload = {
                "campaign_id": int(campaign_id),
                "patient_link_id": int(patient_link_id),
                "message_id": int(message_id),
                "event_type": event,
                "status": status_by_event[event],
                "amount": int(amount),
                "wallet_transaction_id": wallet_transaction_id,
                "compensation_transaction_id": compensation_transaction_id,
                "reason_code": str(reason_code),
                "occurred_at": occurred,
                "recorded_at": recorded,
                "actor_username": str(actor_username),
                "note": str(note or "").strip() or None,
                "idempotency_key": key,
                "supersedes_event_id": int(current["id"]) if current else None,
            }
            cursor = db.execute(
                """INSERT INTO campaign_wallet_grant_events
                   (campaign_id,patient_link_id,message_id,event_type,status,amount,
                    wallet_transaction_id,compensation_transaction_id,reason_code,
                    occurred_at,recorded_at,actor_username,note,idempotency_key,
                    supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                "SELECT * FROM campaign_wallet_grant_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    # ------------------------------------------------------------------ direct SMS cost stream
    def current_message_cost(self, message_id: int) -> dict | None:
        return self._row(
            self._db().execute(
                """SELECT * FROM campaign_message_cost_events
                   WHERE message_id=? ORDER BY recorded_at DESC,id DESC LIMIT 1""",
                (int(message_id),),
            ).fetchone()
        )

    def record_message_cost(
        self,
        *,
        campaign_id: int,
        message_id: int,
        evidence_type: str,
        parts: int,
        unit_cost: int,
        actor_username: str,
        idempotency_key: str,
        source_ref: str | None = None,
        note: str | None = None,
        commit: bool = True,
    ) -> dict:
        db = self._db()
        if commit:
            db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute(
                "SELECT * FROM campaign_message_cost_events WHERE idempotency_key=?",
                (str(idempotency_key),),
            ).fetchone()
            if existing:
                if commit:
                    db.commit()
                return dict(existing)
            current = self.current_message_cost(message_id)
            event_type = "ADJUSTED" if current else "RECORDED"
            recorded = _time()
            payload = {
                "campaign_id": int(campaign_id),
                "message_id": int(message_id),
                "event_type": event_type,
                "status": "ACTIVE",
                "evidence_type": str(evidence_type).upper(),
                "currency": "TOMAN",
                "parts": int(parts),
                "unit_cost": int(unit_cost),
                "amount": int(parts) * int(unit_cost),
                "source_ref": str(source_ref or "").strip() or None,
                "recorded_at": recorded,
                "actor_username": str(actor_username),
                "note": str(note or "").strip() or None,
                "idempotency_key": str(idempotency_key),
                "supersedes_event_id": int(current["id"]) if current else None,
            }
            cursor = db.execute(
                """INSERT INTO campaign_message_cost_events
                   (campaign_id,message_id,event_type,status,evidence_type,currency,
                    parts,unit_cost,amount,source_ref,recorded_at,actor_username,
                    note,idempotency_key,supersedes_event_id,content_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*payload.values(), _hash(payload)),
            )
            row = db.execute(
                "SELECT * FROM campaign_message_cost_events WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit:
                db.commit()
            return dict(row)
        except Exception:
            if commit:
                db.rollback()
            raise

    # ------------------------------------------------------------------ projections
    def campaign_messages(self, campaign_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT message.*, patient.full_name,
                      governance.purpose, governance.consent_event_id,
                      delivery.id AS current_delivery_event_id,
                      delivery.status AS current_delivery_status,
                      delivery.status_int AS current_delivery_status_int,
                      response.id AS current_response_event_id,
                      response.response_type AS current_response_type,
                      cost.amount AS current_sms_cost,
                      cost.evidence_type AS cost_evidence_type
               FROM sms_messages message
               JOIN patient_links patient ON patient.id=message.patient_link_id
               LEFT JOIN sms_message_governance governance
                 ON governance.message_id=message.id
               LEFT JOIN sms_delivery_events delivery
                 ON delivery.message_id=message.id
                AND delivery.id=(
                    SELECT head.id FROM sms_delivery_events head
                    WHERE head.message_id=message.id
                    ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                )
               LEFT JOIN campaign_response_events response
                 ON response.campaign_id=message.campaign_id
                AND response.patient_link_id=message.patient_link_id
                AND response.id=(
                    SELECT response_head.id FROM campaign_response_events response_head
                    WHERE response_head.campaign_id=message.campaign_id
                      AND response_head.patient_link_id=message.patient_link_id
                    ORDER BY response_head.recorded_at DESC,response_head.id DESC LIMIT 1
                )
               LEFT JOIN campaign_message_cost_events cost
                 ON cost.message_id=message.id
                AND cost.id=(
                    SELECT cost_head.id FROM campaign_message_cost_events cost_head
                    WHERE cost_head.message_id=message.id
                    ORDER BY cost_head.recorded_at DESC,cost_head.id DESC LIMIT 1
                )
               WHERE message.campaign_id=?
               ORDER BY message.id""",
            (int(campaign_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def message_state_counts(self, campaign_id: int) -> dict:
        rows = self.campaign_messages(campaign_id)
        result = {
            "messages": len(rows),
            "accepted": 0,
            "provider_accepted": 0,
            "delivered": 0,
            "in_flight": 0,
            "failed": 0,
            "unknown": 0,
            "terminal": 0,
            "nonterminal": 0,
        }
        for row in rows:
            if str(row.get("status") or "") in {"accepted", "delivered", "sent"}:
                result["provider_accepted"] += 1
            status = str(
                row.get("current_delivery_status")
                or row.get("delivery_status")
                or "Queued"
            )
            if status == "Delivered":
                result["delivered"] += 1
            if status in {"Accepted", "PendingApproval", "WaitingForSend", "Sending", "SendToOperator", "Sent"}:
                result["accepted"] += 1
            if status in _FAILURE_DELIVERY:
                result["failed"] += 1
                if status in {"StatusUnknown", "SubmissionUnknown"}:
                    result["unknown"] += 1
            elif status != "Delivered":
                result["in_flight"] += 1
            if status in _TERMINAL_DELIVERY:
                result["terminal"] += 1
            else:
                result["nonterminal"] += 1
        return result

    def financial_rows_for_campaign(self, campaign_id: int) -> list[dict]:
        rows = self._db().execute(
            """SELECT attribution.journey_id,
                      attribution.patient_link_id,
                      attribution.response_event_id,
                      observation.accounting_invoice_id,
                      observation.invoice_status,
                      observation.billed_amount,
                      observation.collected_amount AS gross_collected_amount,
                      observation.collection_state,
                      observation.observed_at,
                      review.id AS financial_review_event_id,
                      review.status AS financial_review_status,
                      CASE WHEN review.status='REVIEWED'
                                AND review.financial_observation_id=observation.id
                           THEN 1 ELSE 0 END AS financial_review_ready,
                      COALESCE((
                          SELECT SUM(adjustment.signed_amount)
                          FROM specialist_financial_adjustment_events adjustment
                          WHERE adjustment.accounting_invoice_id=observation.accounting_invoice_id
                            AND adjustment.financial_observation_id=observation.id
                            AND adjustment.id=(
                                SELECT head.id
                                FROM specialist_financial_adjustment_events head
                                WHERE head.adjustment_id=adjustment.adjustment_id
                                ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                            ) AND adjustment.status='ACTIVE'
                      ),0) AS adjustment_total,
                      observation.collected_amount+COALESCE((
                          SELECT SUM(adjustment.signed_amount)
                          FROM specialist_financial_adjustment_events adjustment
                          WHERE adjustment.accounting_invoice_id=observation.accounting_invoice_id
                            AND adjustment.financial_observation_id=observation.id
                            AND adjustment.id=(
                                SELECT head.id
                                FROM specialist_financial_adjustment_events head
                                WHERE head.adjustment_id=adjustment.adjustment_id
                                ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                            ) AND adjustment.status='ACTIVE'
                      ),0) AS adjusted_collected_amount
               FROM campaign_journey_attribution_events attribution
               LEFT JOIN specialist_financial_observations observation
                 ON observation.journey_id=attribution.journey_id
                AND observation.id=(
                    SELECT latest.id FROM specialist_financial_observations latest
                    WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
                    ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
                )
               LEFT JOIN specialist_financial_review_events review
                 ON review.accounting_invoice_id=observation.accounting_invoice_id
                AND review.id=(
                    SELECT review_head.id FROM specialist_financial_review_events review_head
                    WHERE review_head.accounting_invoice_id=observation.accounting_invoice_id
                    ORDER BY review_head.recorded_at DESC,review_head.id DESC LIMIT 1
                )
               WHERE attribution.campaign_id=?
                 AND attribution.id=(
                     SELECT head.id FROM campaign_journey_attribution_events head
                     WHERE head.journey_id=attribution.journey_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 ) AND attribution.status='ATTRIBUTED'
                 AND attribution.response_event_id=(
                     SELECT latest_response.id
                     FROM campaign_response_events latest_response
                     WHERE latest_response.campaign_id=attribution.campaign_id
                       AND latest_response.patient_link_id=attribution.patient_link_id
                     ORDER BY latest_response.recorded_at DESC,
                              latest_response.id DESC LIMIT 1
                 )
                 AND EXISTS (
                     SELECT 1 FROM campaign_response_events positive_response
                     WHERE positive_response.id=attribution.response_event_id
                       AND positive_response.response_type='POSITIVE'
                 )
               ORDER BY attribution.journey_id,observation.accounting_invoice_id""",
            (int(campaign_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def cost_summary(self, campaign_id: int) -> dict:
        db = self._db()
        sms = db.execute(
            """SELECT COALESCE(SUM(cost.amount),0) AS amount,
                      COUNT(*) AS costed_messages
               FROM campaign_message_cost_events cost
               WHERE cost.campaign_id=?
                 AND cost.id=(
                     SELECT head.id FROM campaign_message_cost_events head
                     WHERE head.message_id=cost.message_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 ) AND cost.status='ACTIVE'""",
            (int(campaign_id),),
        ).fetchone()
        wallet = db.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN grant.status='ACTIVE' THEN grant.amount ELSE 0 END),0)
                   AS active_liability,
                 COALESCE(SUM(CASE WHEN grant.status='COMPENSATED' THEN grant.amount ELSE 0 END),0)
                   AS compensated,
                 SUM(CASE WHEN grant.status='REVIEW_REQUIRED' THEN 1 ELSE 0 END)
                   AS review_required,
                 COUNT(*) AS grant_streams
               FROM campaign_wallet_grant_events grant
               WHERE grant.campaign_id=?
                 AND grant.id=(
                     SELECT head.id FROM campaign_wallet_grant_events head
                     WHERE head.campaign_id=grant.campaign_id
                       AND head.patient_link_id=grant.patient_link_id
                     ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                 )""",
            (int(campaign_id),),
        ).fetchone()
        return {
            "sms_cost": int(sms["amount"] or 0),
            "costed_messages": int(sms["costed_messages"] or 0),
            "wallet_liability": int(wallet["active_liability"] or 0),
            "wallet_compensated": int(wallet["compensated"] or 0),
            "wallet_review_required": int(wallet["review_required"] or 0),
            "wallet_grant_streams": int(wallet["grant_streams"] or 0),
        }

    def campaign_projection(self, campaign_id: int) -> dict:
        campaign = self.campaign(campaign_id)
        if not campaign:
            raise LookupError("campaign not found")
        lifecycle = self.current_lifecycle(campaign_id)
        audience = self.audience_summary(campaign_id)
        messages = self.message_state_counts(campaign_id)
        response_rows = self.response_rows(campaign_id)
        positive = sum(1 for row in response_rows if row["response_type"] == "POSITIVE")
        negative = sum(1 for row in response_rows if row["response_type"] == "NEGATIVE")
        opt_out = sum(1 for row in response_rows if row["response_type"] == "OPT_OUT")
        attributions = self.current_campaign_attributions(campaign_id)
        trusted_attributions = [
            row for row in attributions if int(row["response_current_positive"] or 0) == 1
        ]
        stale_attributions = [
            row for row in attributions if int(row["response_current_positive"] or 0) != 1
        ]
        financial = self.financial_rows_for_campaign(campaign_id)
        observed_journeys = {
            row["journey_id"]
            for row in financial
            if row["accounting_invoice_id"] is not None
        }
        reviewed_journeys = {
            row["journey_id"]
            for row in financial
            if int(row["financial_review_ready"] or 0) == 1
        }
        attributed_journeys = {row["journey_id"] for row in trusted_attributions}
        billed = sum(int(row["billed_amount"] or 0) for row in financial)
        gross_collected = sum(
            int(row["gross_collected_amount"] or 0) for row in financial
        )
        adjustment_total = sum(
            int(row["adjustment_total"] or 0)
            for row in financial
            if int(row["financial_review_ready"] or 0) == 1
        )
        collected = sum(
            int(row["adjusted_collected_amount"] or 0)
            for row in financial
            if int(row["financial_review_ready"] or 0) == 1
        )
        invoices = sum(
            1 for row in financial if row["accounting_invoice_id"] is not None
        )
        costs = self.cost_summary(campaign_id)
        direct_cost = costs["sms_cost"] + costs["wallet_liability"]
        net = collected - direct_cost
        roi = round((net / direct_cost) * 100, 2) if direct_cost > 0 else None
        trusted_audience = audience.get("source_code") == "NEW_FROZEN"
        provider_accepted_messages = messages["provider_accepted"]
        cost_complete = (
            provider_accepted_messages == costs["costed_messages"]
            if provider_accepted_messages
            else messages["messages"] == 0
        )
        finance_complete = attributed_journeys <= observed_journeys
        adjustment_review_complete = attributed_journeys <= reviewed_journeys
        safe_to_sum = bool(
            trusted_audience
            and cost_complete
            and finance_complete
            and adjustment_review_complete
            and not stale_attributions
            and costs["wallet_review_required"] == 0
        )
        if not audience["frozen"]:
            measurement_status = "AUDIENCE_NOT_FROZEN"
        elif not trusted_audience:
            measurement_status = "LEGACY_AUDIENCE_UNTRUSTED"
        elif messages["nonterminal"]:
            measurement_status = "DELIVERY_IN_PROGRESS"
        elif not cost_complete:
            measurement_status = "DIRECT_COST_INCOMPLETE"
        elif stale_attributions:
            measurement_status = "STALE_RESPONSE_ATTRIBUTION_REVIEW_REQUIRED"
        elif not finance_complete:
            measurement_status = "FINANCIAL_RECONCILIATION_INCOMPLETE"
        elif not adjustment_review_complete:
            measurement_status = "FINANCIAL_ADJUSTMENT_REVIEW_REQUIRED"
        elif costs["wallet_review_required"]:
            measurement_status = "WALLET_COMPENSATION_REVIEW_REQUIRED"
        elif not attributions:
            measurement_status = "JOURNEY_ATTRIBUTION_REQUIRED"
        else:
            measurement_status = "READY"
        return {
            "campaign": campaign,
            "lifecycle": lifecycle,
            "audience": audience,
            "messages": messages,
            "responses": {
                "positive": positive,
                "negative": negative,
                "opt_out": opt_out,
                "rows": response_rows,
            },
            "attributions": {
                "journeys": len(attributed_journeys),
                "stale": len(stale_attributions),
                "rows": attributions,
            },
            "finance": {
                "billed": billed,
                "gross_collected": gross_collected,
                "adjustment_total": adjustment_total,
                "collected": collected,
                "invoices": invoices,
                "observed_journeys": len(observed_journeys),
                "reviewed_journeys": len(reviewed_journeys),
                "missing_journeys": len(attributed_journeys - observed_journeys),
                "pending_adjustment_review": len(
                    attributed_journeys - reviewed_journeys
                ),
            },
            "costs": {
                **costs,
                "direct_cost": direct_cost,
            },
            "net_contribution": net,
            "roi_percent": roi,
            "safe_to_sum": safe_to_sum,
            "measurement_status": measurement_status,
            "policy_version": "EXPLICIT_CAMPAIGN_JOURNEY_ROI_V1",
        }


__all__ = [
    "CampaignEconomicsConflict",
    "CampaignEconomicsRepository",
    "CampaignEconomicsValidationError",
]
