"""Authentication service for AppUser (preserves the Flask apps' semantics).

- bcrypt passwords; legacy werkzeug hashes are transparently re-hashed to bcrypt
  on a successful login (werkzeug is an OPTIONAL dependency — if absent, legacy
  hashes simply fail to verify).
- 5 failed attempts -> account locked for 15 minutes.
- RLS ordering: the caller MUST resolve the clinic (by slug; the ``clinic`` table
  is not RLS-protected) and set the tenant GUC BEFORE querying ``app_user``,
  because ``app_user`` is itself RLS-protected. ``authenticate()`` is meant to be
  called inside ``with tenant_context(clinic.id):``.
"""

from datetime import timedelta

import bcrypt
from django.utils import timezone

from apps.identity.models import AppUser

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class AuthError(Exception):
    """Login failed. ``code`` is a stable machine string for the API layer."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _looks_like_bcrypt(raw: bytes) -> bool:
    return raw[:2] == b"$2"


def _verify_password(user: AppUser, password: str) -> bool:
    raw = bytes(user.password_hash)
    pw = password.encode("utf-8")
    if _looks_like_bcrypt(raw):
        try:
            return bcrypt.checkpw(pw, raw)
        except ValueError:
            return False
    # Legacy werkzeug hash (pbkdf2:/scrypt:) — verify then upgrade to bcrypt.
    try:
        from werkzeug.security import check_password_hash  # optional dep
    except Exception:
        return False
    if check_password_hash(raw.decode("utf-8", "ignore"), password):
        user.password_hash = bcrypt.hashpw(pw, bcrypt.gensalt())
        user.save(update_fields=["password_hash"])
        return True
    return False


def authenticate(clinic, username: str, password: str) -> AppUser:
    """Return the AppUser on success, else raise AuthError. Call inside the
    clinic's tenant context."""
    now = timezone.now()
    try:
        user = AppUser.objects.get(clinic=clinic, username=username)
    except AppUser.DoesNotExist:
        raise AuthError("invalid_credentials", "نام کاربری یا رمز عبور نادرست است.")

    if not user.is_active:
        raise AuthError("inactive", "این حساب غیرفعال است.")

    if user.locked_until and user.locked_until > now:
        raise AuthError("locked", "حساب موقتاً قفل شده است؛ بعداً تلاش کنید.")

    if not _verify_password(user, password):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        fields = ["failed_attempts"]
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_attempts = 0
            fields.append("locked_until")
        user.save(update_fields=fields)
        raise AuthError("invalid_credentials", "نام کاربری یا رمز عبور نادرست است.")

    # success
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login = now
    user.save(update_fields=["failed_attempts", "locked_until", "last_login"])
    return user
