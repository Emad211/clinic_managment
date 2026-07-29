import sqlite3
from typing import Optional, List, Dict

from src.adapters.sqlite.core import get_db


class AuthRepository:
    """Low-level DB operations for users."""

    def count_users(self) -> int:
        row = get_db().execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"] or 0)

    def get_manager_requiring_password_change(self) -> Optional[Dict]:
        row = get_db().execute(
            """SELECT * FROM users
               WHERE role='manager' AND is_active=1 AND must_change_password=1
               ORDER BY id LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None

    def create_initial_manager(
        self,
        *,
        username: str,
        password_hash: bytes,
        full_name: str,
    ) -> Dict:
        db = get_db()
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
            raise RuntimeError("Initial manager can only be created in an empty database")
        cursor = db.execute(
            """INSERT INTO users
               (username,password_hash,role,full_name,is_active,must_change_password)
               VALUES (?,?,'manager',?,1,0)""",
            (username, password_hash, full_name),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM users WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
        return dict(row)

    def complete_required_password_change(
        self, *, user_id: int, password_hash: bytes
    ) -> Dict:
        db = get_db()
        cursor = db.execute(
            """UPDATE users
               SET password_hash=?,must_change_password=0,
                   failed_attempts=0,locked_until=NULL
               WHERE id=? AND role='manager' AND is_active=1
                 AND must_change_password=1""",
            (password_hash, user_id),
        )
        if cursor.rowcount != 1:
            db.rollback()
            raise RuntimeError("Required password-change target is no longer valid")
        db.commit()
        row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row)

    def get_raw_by_username(self, username: str) -> Optional[sqlite3.Row]:
        db = get_db()
        return db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    def get_all_users(self) -> List[Dict]:
        db = get_db()
        rows = db.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [dict(r) for r in rows]

    def get_active_usernames(self, role: Optional[str] = None) -> List[str]:
        users = self.get_all_users()
        return [
            u["username"]
            for u in users
            if u.get("is_active", 1) and (role is None or u.get("role") == role)
        ]

    def update_failed_attempts(self, user_id: int, failed_attempts: int, locked_until: Optional[str]):
        db = get_db()
        db.execute(
            "UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
            (failed_attempts, locked_until, user_id),
        )
        db.commit()

    def reset_failed_attempts(self, user_id: int):
        db = get_db()
        db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?", (user_id,))
        db.commit()

    def set_last_login(self, user_id: int):
        db = get_db()
        try:
            db.execute(
                "UPDATE users SET last_login=datetime('now', '+3 hours', '+30 minutes') WHERE id=?",
                (user_id,),
            )
            db.commit()
        except sqlite3.OperationalError:
            db.rollback()

    def create_user(self, username: str, password_hash: bytes, role: str = "staff",
                    full_name: Optional[str] = None) -> bool:
        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                (username, password_hash, role, full_name),
            )
            db.commit()
            return True
        except Exception as e:
            print(f"Error creating user: {e}")
            return False

    def update_user_password(self, user_id: int, password_hash: bytes) -> bool:
        db = get_db()
        try:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
            db.commit()
            return True
        except Exception as e:
            print(f"Error updating password: {e}")
            return False

    def set_api_token(self, user_id: int, token: str, ttl_days: int = 90):
        """Store the (rotated) extension API token for a user, with an expiry (SECU-05).
        Tokens are short-lived (default 90 days) so a leaked extension token can't be used
        indefinitely; the physician re-rotates from Manager → Users when it lapses."""
        from datetime import timedelta
        from src.common.utils import iran_now
        expires_at = (iran_now() + timedelta(days=ttl_days)).strftime('%Y-%m-%d %H:%M:%S')
        db = get_db()
        db.execute("UPDATE users SET api_token=?, api_token_expires_at=? WHERE id=?",
                   (token, expires_at, user_id))
        db.commit()

    def get_user_by_token(self, token: str) -> Optional[Dict]:
        """Look up an active user by their UNEXPIRED extension API token, or None (SECU-05).
        A NULL expiry is a legacy token issued before SECU-05 — treated as valid (no real
        extension tokens are in use yet); any re-rotation stamps a fresh expiry."""
        if not token:
            return None
        from src.common.utils import iran_now
        now = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        db = get_db()
        r = db.execute(
            "SELECT * FROM users WHERE api_token=? AND is_active=1 "
            "AND (api_token_expires_at IS NULL OR api_token_expires_at >= ?)",
            (token, now)
        ).fetchone()
        return dict(r) if r else None
