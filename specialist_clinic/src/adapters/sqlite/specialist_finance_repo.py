"""Specialist-side read models used by the scoped finance dashboard."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


class SpecialistFinanceRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def campaigns(self) -> list[dict]:
        rows = self._db().execute(
            """SELECT id, name, campaign_type, credit_amount, sent_count,
                      delivered_count, created_at
               FROM sms_campaigns ORDER BY id DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def positive_campaign_credit(self, campaign_id: int) -> int:
        row = self._db().execute(
            """SELECT COALESCE(SUM(amount),0) AS amount
               FROM wallet_transactions
               WHERE reason='campaign' AND campaign_id=? AND amount>0""",
            (int(campaign_id),),
        ).fetchone()
        return int(row["amount"] or 0)
