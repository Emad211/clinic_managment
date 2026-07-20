"""Repository for patient wallet (credit balance) and its transactions."""
from src.adapters.sqlite.core import get_db


class WalletRepository:

    def get_balance(self, pid: int) -> int:
        db = get_db()
        row = db.execute("SELECT wallet_balance FROM patient_links WHERE id=?", (pid,)).fetchone()
        return int(row["wallet_balance"]) if row else 0

    def adjust(self, pid: int, amount: int, *, reason: str, note: str = None,
               campaign_id: int = None, expires_at: str = None, created_by: str = None,
               idempotency_key: str = None) -> int:
        """Apply a credit (+) or debit (-) and record a transaction. Returns new balance."""
        db = get_db()
        if idempotency_key:
            prior = db.execute(
                "SELECT balance_after FROM wallet_transactions WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if prior:
                return int(prior["balance_after"])
        current = self.get_balance(pid)
        new_balance = current + int(amount)
        if new_balance < 0:
            new_balance = 0  # never go negative
            amount = -current
        db.execute("UPDATE patient_links SET wallet_balance=? WHERE id=?", (new_balance, pid))
        db.execute(
            """INSERT INTO wallet_transactions
               (patient_link_id, amount, balance_after, reason, campaign_id, note, expires_at,
                created_by, idempotency_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, amount, new_balance, reason, campaign_id, note, expires_at, created_by,
             idempotency_key),
        )
        db.commit()
        return new_balance

    def transactions(self, pid: int, limit: int = 100) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM wallet_transactions WHERE patient_link_id=? ORDER BY id DESC LIMIT ?",
            (pid, limit)).fetchall()]

    def total_outstanding(self) -> int:
        db = get_db()
        row = db.execute("SELECT COALESCE(SUM(wallet_balance),0) s FROM patient_links WHERE is_active=1").fetchone()
        return int(row["s"]) if row else 0
