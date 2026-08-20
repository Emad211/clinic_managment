"""Secure first-run manager provisioning and legacy-default remediation."""
from __future__ import annotations

import re

import bcrypt

from src.adapters.sqlite.auth_repo import AuthRepository


_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")
_COMMON_PASSWORDS = {
    "admin",
    "admin123",
    "password",
    "password123",
    "123456789012",
    "qwerty123456",
}


class FirstRunValidationError(ValueError):
    pass


class FirstRunService:
    def __init__(self, repo: AuthRepository | None = None):
        self.repo = repo or AuthRepository()

    def setup_target(self) -> dict | None:
        if self.repo.count_users() == 0:
            return {"mode": "create", "username": None}
        user = self.repo.get_manager_requiring_password_change()
        if user:
            return {
                "mode": "change",
                "user_id": int(user["id"]),
                "username": str(user["username"]),
            }
        return None

    def setup_required(self) -> bool:
        return self.setup_target() is not None

    def complete(
        self,
        *,
        username: str,
        password: str,
        password_confirm: str,
        full_name: str | None = None,
    ) -> dict:
        target = self.setup_target()
        if target is None:
            raise FirstRunValidationError("راه‌اندازی اولیه قبلاً تکمیل شده است.")

        effective_username = (
            target["username"]
            if target["mode"] == "change"
            else (username or "").strip()
        )
        self._validate_username(effective_username)
        self._validate_password(
            password=password,
            confirmation=password_confirm,
            username=effective_username,
        )
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=12),
        )
        if target["mode"] == "create":
            user = self.repo.create_initial_manager(
                username=effective_username,
                password_hash=password_hash,
                full_name=(full_name or "").strip() or "مدیر سیستم",
            )
        else:
            user = self.repo.complete_required_password_change(
                user_id=int(target["user_id"]),
                password_hash=password_hash,
            )
        return user

    @staticmethod
    def _validate_username(username: str) -> None:
        if not _USERNAME.fullmatch(username or ""):
            raise FirstRunValidationError(
                "نام کاربری باید ۳ تا ۴۰ نویسه و فقط شامل حروف انگلیسی، "
                "عدد، نقطه، خط تیره یا زیرخط باشد."
            )

    @staticmethod
    def _validate_password(
        *, password: str, confirmation: str, username: str
    ) -> None:
        if password != confirmation:
            raise FirstRunValidationError("تکرار رمز عبور یکسان نیست.")
        normalized = (password or "").casefold()
        if len(password or "") < 12:
            raise FirstRunValidationError(
                "رمز عبور باید دست‌کم ۱۲ نویسه داشته باشد."
            )
        if normalized in _COMMON_PASSWORDS or username.casefold() in normalized:
            raise FirstRunValidationError(
                "رمز عبور نباید رایج باشد یا نام کاربری را در خود داشته باشد."
            )
        if not any(char.isalpha() for char in password) or not any(
            char.isdigit() for char in password
        ):
            raise FirstRunValidationError(
                "رمز عبور باید دست‌کم یک حرف و یک عدد داشته باشد."
            )


__all__ = ["FirstRunService", "FirstRunValidationError"]
