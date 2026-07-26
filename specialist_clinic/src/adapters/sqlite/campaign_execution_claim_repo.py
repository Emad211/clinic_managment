"""Short-lived execution claim for campaigns; lifecycle status lives elsewhere."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


class CampaignExecutionClaimRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def claim(self, campaign_id: int, token: str, *, commit: bool = True) -> bool:
        db = self._db()
        cursor = db.execute(
            """UPDATE sms_campaigns
               SET claim_token=?,
                   claim_at=datetime('now','+3 hours','+30 minutes')
               WHERE id=?
                 AND (
                     claim_token IS NULL OR
                     claim_at<datetime('now','+3 hours','+30 minutes','-20 minutes')
                 )""",
            (str(token), int(campaign_id)),
        )
        if commit:
            db.commit()
        return cursor.rowcount == 1

    def release(self, campaign_id: int, token: str, *, commit: bool = True) -> bool:
        db = self._db()
        cursor = db.execute(
            """UPDATE sms_campaigns SET claim_token=NULL,claim_at=NULL
               WHERE id=? AND claim_token=?""",
            (int(campaign_id), str(token)),
        )
        if commit:
            db.commit()
        return cursor.rowcount == 1
