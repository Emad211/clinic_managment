import sqlite3
from typing import Optional, List, Dict

from src.adapters.sqlite.core import get_db


class AuthRepository:
    """Low-level DB operations for users."""

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
