"""Repository for patient wallet credit with caller-owned transaction support."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db


class WalletRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def get_balance(self, pid: int) -> int:
        row = self._db().execute(
            "SELECT wallet_balance FROM patient_links WHERE id=?",
            (int(pid),),
        ).fetchone()
        return int(row["wallet_balance"] or 0) if row else 0

    def apply(
        self,
        pid: int,
        amount: int,
        *,
        reason: str,
        note: str | None = None,
        campaign_id: int | None = None,
        expires_at: str | None = None,
        created_by: str | None = None,
        idempotency_key: str | None = None,
        commit: bool = True,
    ) -> dict:
        """Apply one idempotent credit/debit and return the persisted transaction row."""
        db = self._db()
        owns_transaction = bool(commit and not db.in_transaction)
        if owns_transaction:
            db.execute("BEGIN IMMEDIATE")
        try:
            patient = db.execute(
                "SELECT id,wallet_balance FROM patient_links WHERE id=?",
                (int(pid),),
            ).fetchone()
            if not patient:
                raise LookupError("wallet patient not found")
            key = str(idempotency_key or "").strip() or None
            if key:
                prior = db.execute(
                    "SELECT * FROM wallet_transactions WHERE idempotency_key=?",
                    (key,),
                ).fetchone()
                if prior:
                    prior = dict(prior)
                    if (
                        int(prior["patient_link_id"]) != int(pid)
                        or int(prior["amount"]) != int(amount)
                        or str(prior.get("reason") or "") != str(reason or "")
                    ):
                        raise ValueError(
                            "wallet idempotency key belongs to another adjustment"
                        )
                    if owns_transaction:
                        db.commit()
                    return prior
            current = int(patient["wallet_balance"] or 0)
            applied_amount = int(amount)
            new_balance = current + applied_amount
            if new_balance < 0:
                new_balance = 0
                applied_amount = -current
            cursor = db.execute(
                """INSERT INTO wallet_transactions
                   (patient_link_id,amount,balance_after,reason,campaign_id,note,
                    expires_at,created_by,idempotency_key)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    int(pid), applied_amount, new_balance, str(reason),
                    campaign_id, note, expires_at, created_by, key,
                ),
            )
            db.execute(
                "UPDATE patient_links SET wallet_balance=? WHERE id=?",
                (new_balance, int(pid)),
            )
            row = db.execute(
                "SELECT * FROM wallet_transactions WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            if commit and owns_transaction:
                db.commit()
            return dict(row)
        except Exception:
            if owns_transaction:
                db.rollback()
            raise

    def adjust(
        self,
        pid: int,
        amount: int,
        *,
        reason: str,
        note: str | None = None,
        campaign_id: int | None = None,
        expires_at: str | None = None,
        created_by: str | None = None,
        idempotency_key: str | None = None,
        commit: bool = True,
    ) -> int:
        """Backward-compatible wrapper returning the resulting balance."""
        event = self.apply(
            pid,
            amount,
            reason=reason,
            note=note,
            campaign_id=campaign_id,
            expires_at=expires_at,
            created_by=created_by,
            idempotency_key=idempotency_key,
            commit=commit,
        )
        return int(event["balance_after"])

    def transactions(self, pid: int, limit: int = 100) -> list[dict]:
        return [
            dict(row)
            for row in self._db().execute(
                """SELECT * FROM wallet_transactions
                   WHERE patient_link_id=? ORDER BY id DESC LIMIT ?""",
                (int(pid), int(limit)),
            ).fetchall()
        ]

    def total_outstanding(self) -> int:
        row = self._db().execute(
            """SELECT COALESCE(SUM(wallet_balance),0) AS amount
               FROM patient_links WHERE is_active=1"""
        ).fetchone()
        return int(row["amount"] or 0) if row else 0
