"""Atomic patient-response and exclusive campaign-to-Journey attribution workflow."""
from __future__ import annotations

from datetime import datetime
import sqlite3
import uuid

from src.adapters.sqlite.campaign_journey_attribution_repo import (
    CampaignAttributionConflict,
    CampaignAttributionValidationError,
    CampaignJourneyAttributionRepository,
)
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class CampaignResponseAttributionService:
    def __init__(self, *, repository=None, clock=None):
        self.repository = repository or CampaignJourneyAttributionRepository()
        self.clock = clock or iran_now

    def record_response(
        self,
        *,
        sms_message_id: int,
        response_type: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str | None = None,
        occurred_at: datetime | str | None = None,
        journey_id: str | None = None,
        allow_reattribution: bool = False,
        reattribution_note: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Record response, STOP consent, and optional positive Journey link atomically."""
        db = get_db()
        repo = CampaignJourneyAttributionRepository(db)
        message = db.execute(
            "SELECT * FROM sms_messages WHERE id=?", (int(sms_message_id),)
        ).fetchone()
        if not message:
            raise LookupError("SMS message not found")
        key = str(
            idempotency_key
            or f"response:{int(sms_message_id)}:{uuid.uuid4().hex}"
        )
        db.execute("BEGIN IMMEDIATE")
        try:
            response, response_created = repo.record_response_once(
                sms_message_id=int(sms_message_id),
                response_type=response_type,
                actor_username=actor_username,
                actor_user_id=actor_user_id,
                occurred_at=occurred_at or self.clock(),
                recorded_at=self.clock(),
                note=note,
                idempotency_key=key,
                commit=False,
            )
            attribution = None
            attribution_created = False
            if journey_id:
                if response["response_type"] not in repo.POSITIVE_RESPONSES:
                    raise CampaignAttributionValidationError(
                        "only positive patient responses may be linked to a Journey"
                    )
                if response["campaign_id"] is None:
                    raise CampaignAttributionValidationError(
                        "Journey attribution requires a campaign message"
                    )
                attribution, attribution_created = repo.attribute_journey(
                    journey_id=str(journey_id),
                    campaign_id=int(response["campaign_id"]),
                    sms_message_id=int(sms_message_id),
                    response_event_id=int(response["id"]),
                    actor_username=actor_username,
                    actor_user_id=actor_user_id,
                    note=reattribution_note,
                    reason_code="EXPLICIT_PATIENT_RESPONSE",
                    effective_at=occurred_at or self.clock(),
                    allow_reattribution=bool(allow_reattribution),
                    commit=False,
                )
            db.commit()
            return {
                "response": response,
                "response_created": bool(response_created),
                "attribution": attribution,
                "attribution_created": bool(attribution_created),
            }
        except Exception:
            db.rollback()
            raise

    def record_consent(
        self,
        *,
        patient_link_id: int,
        event_type: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str | None,
        idempotency_key: str | None = None,
    ) -> dict:
        event, created = self.repository.record_consent_once(
            patient_link_id=int(patient_link_id),
            event_type=event_type,
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            source="STAFF_RECORDED",
            occurred_at=self.clock(),
            note=note,
            idempotency_key=(
                idempotency_key
                or f"consent:{int(patient_link_id)}:{uuid.uuid4().hex}"
            ),
        )
        return {"event": event, "created": bool(created)}

    def revoke_attribution(
        self,
        *,
        journey_id: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
    ) -> dict:
        return self.repository.revoke(
            journey_id=str(journey_id),
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            note=note,
        )

    def enter_attribution_in_error(
        self,
        *,
        journey_id: str,
        actor_username: str,
        actor_user_id: int | None,
        note: str,
    ) -> dict:
        return self.repository.enter_in_error(
            journey_id=str(journey_id),
            actor_username=actor_username,
            actor_user_id=actor_user_id,
            note=note,
        )


__all__ = [
    "CampaignAttributionConflict",
    "CampaignAttributionValidationError",
    "CampaignResponseAttributionService",
]
