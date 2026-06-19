from datetime import datetime, timedelta
from typing import Optional, List

import bcrypt
from werkzeug.security import check_password_hash

from src.adapters.sqlite.auth_repo import AuthRepository
from src.common.utils import iran_now


class AuthService:
    """Auth logic with bcrypt + lockout (5 failed attempts -> 15 min lock)."""

    def __init__(self, repo: AuthRepository | None = None):
        self.repo = repo or AuthRepository()

    def _is_locked(self, user_row: dict) -> bool:
        locked_until = user_row.get("locked_until")
        if not locked_until:
            return False
        try:
            return iran_now() < datetime.fromisoformat(str(locked_until))
        except Exception:
            return False

    def _increment_failed(self, user_row: dict):
        new_val = (user_row.get("failed_attempts") or 0) + 1
        lock_until: Optional[str] = None
        if new_val >= 5:
            lock_until = (iran_now() + timedelta(minutes=15)).isoformat(timespec="seconds")
            new_val = 0
        self.repo.update_failed_attempts(user_row["id"], new_val, lock_until)

    def get_usernames(self, role: Optional[str] = None) -> List[str]:
        return self.repo.get_active_usernames(role)

    def validate_login(self, username: str, password: str) -> Optional[dict]:
        username = (username or "").strip()
        user = self.repo.get_raw_by_username(username)
        if not user:
            return None
        user_dict = dict(user)

        if not user_dict.get("is_active", 1):
            return None
        if self._is_locked(user_dict):
            return None

        stored_hash = user_dict.get("password_hash")
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode("utf-8")

        password_ok = False
        try:
            if stored_hash and isinstance(stored_hash, (bytes, bytearray)) and stored_hash.startswith(b"$2"):
                password_ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash)
            else:
                stored_str = stored_hash.decode("utf-8") if isinstance(stored_hash, (bytes, bytearray)) else stored_hash
                if stored_str:
                    try:
                        password_ok = check_password_hash(stored_str, password)
                        if password_ok:
                            new_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
                            try:
                                self.repo.update_user_password(user_dict['id'], new_hash)
                            except Exception:
                                pass
                    except Exception:
                        password_ok = False
        except Exception:
            password_ok = False

        if not password_ok:
            if not self._is_locked(user_dict):
                self._increment_failed(user_dict)
            return None

        self.repo.reset_failed_attempts(user_dict["id"])
        self.repo.set_last_login(user_dict["id"])
        return user_dict

    def register_user(self, username: str, password: str, role: str = "staff",
                      full_name: str | None = None) -> bool:
        if self.repo.get_raw_by_username(username):
            return False
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        return self.repo.create_user(username, password_hash, role, full_name)

    def rotate_api_token(self, user_id: int) -> str:
        """Issue a fresh extension API token for a user (invalidates the old one)
        and return it once. The token authenticates the browser-extension bridge."""
        import secrets
        token = secrets.token_urlsafe(24)
        self.repo.set_api_token(user_id, token)
        return token
