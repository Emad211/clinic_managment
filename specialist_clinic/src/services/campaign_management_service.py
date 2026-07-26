"""Atomic creation and cancellation of campaigns with immutable lifecycle events."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.campaign_economics_repo import (
    CampaignEconomicsRepository,
)
from src.adapters.sqlite.campaign_economics_schema import (
    ensure_campaign_economics_storage,
)
from src.adapters.sqlite.core import get_db


class CampaignManagementService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def create(
        self,
        *,
        name: str,
        body: str,
        segment: str,
        campaign_type: str,
        credit_amount: int,
        credit_expires_days: int | None,
        holdout_percent: int,
        scheduled_at: str | None,
        created_by: str,
        template_id: int | None = None,
    ) -> int:
        db = self._db()
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_lifecycle_events'"
        ).fetchone():
            if db.in_transaction:
                raise RuntimeError("campaign economics storage missing inside transaction")
            ensure_campaign_economics_storage(db)
        db.execute("BEGIN IMMEDIATE")
        try:
            cursor = db.execute(
                """INSERT INTO sms_campaigns
                   (name,body,segment,template_id,scheduled_at,status,
                    campaign_type,credit_amount,credit_expires_days,
                    holdout_percent,created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(name), str(body), str(segment), template_id,
                    scheduled_at, "scheduled" if scheduled_at else "draft",
                    str(campaign_type), int(credit_amount or 0),
                    credit_expires_days, int(holdout_percent or 0),
                    str(created_by),
                ),
            )
            campaign_id = int(cursor.lastrowid)
            CampaignEconomicsRepository(db).append_lifecycle(
                campaign_id=campaign_id,
                status="SCHEDULED" if scheduled_at else "DRAFT",
                actor_username=created_by,
                idempotency_key=f"campaign-created:{campaign_id}",
                note="Campaign created through A6 atomic management service.",
                commit=False,
            )
            db.commit()
            return campaign_id
        except Exception:
            db.rollback()
            raise

    def cancel(
        self,
        campaign_id: int,
        *,
        actor_username: str,
        note: str,
        expected_current_event_id: int,
    ) -> dict:
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            event = CampaignEconomicsRepository(db).append_lifecycle(
                campaign_id=int(campaign_id),
                status="CANCELLED",
                actor_username=actor_username,
                expected_current_event_id=int(expected_current_event_id),
                idempotency_key=(
                    f"campaign-cancel:{campaign_id}:{expected_current_event_id}"
                ),
                note=note,
                commit=False,
            )
            db.execute(
                "UPDATE sms_campaigns SET claim_token=NULL,claim_at=NULL WHERE id=?",
                (int(campaign_id),),
            )
            db.commit()
            return event
        except Exception:
            db.rollback()
            raise
