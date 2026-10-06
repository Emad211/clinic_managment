"""Login from two sources (ADR-0007, docs/06 §3).

* Doctors: local ``doctor_account`` (bcrypt). On every login the linked
  ``medical_staff`` row is read live from accounting and must exist, be a
  doctor and be active.
* Reception and manager: accounting ``users`` row, read-only bcrypt check.
  Accounting's ``is_active`` and ``locked_until`` are honoured; a non-bcrypt
  legacy hash is refused (accounting migrates it on the user's next login there).
* Lockout: 5 failures → 15 minutes, counted in the panel (we never write to accounting).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import bcrypt

from ..adapters.accounting.bridge import AccountingBridge, CycleSkipped
from ..adapters.accounting.reader import read_staff, read_user
from ..adapters.sqlite import account_repo, mirror_repo
from ..adapters.sqlite.core import transaction
from ..common.iran_time import TS_FORMAT

MAX_FAILURES = 5
LOCK_MINUTES = 15
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt())

MSG_BAD_CREDENTIALS = "نام کاربری یا رمز نادرست است"
MSG_ACC_INACTIVE = "حساب شما در حسابداری غیرفعال یا قفل است"
MSG_STAFF_INACTIVE = "حساب پزشک شما در کادر درمان حسابداری فعال نیست؛ با مدیر تماس بگیرید"
MSG_DOCTOR_DISABLED = "حساب پزشک شما در پنل غیرفعال شده است؛ با مدیر تماس بگیرید"
MSG_LEGACY_HASH = "رمز شما در حسابداری قدیمی است؛ یک بار در حسابداری وارد شوید و دوباره امتحان کنید"
MSG_BRIDGE_DOWN = "ارتباط با حسابداری برقرار نیست؛ ورود فعلاً ممکن نیست. اگر ادامه داشت با مدیر تماس بگیرید"
MSG_DOCTOR_ROLE = "پزشکان با حساب پنل پیگیری وارد می‌شوند، نه با حساب حسابداری"
MSG_EMPTY = "نام کاربری و رمز را وارد کنید"

ACC_ROLE_MAP = {"manager": "manager", "admin": "manager", "reception": "reception"}


class LoginError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Principal:
    kind: str                    # 'doctor' | 'acc'
    username: str
    role: str                    # 'doctor' | 'reception' | 'manager'
    display_name: str
    staff_id: int | None = None
    doctor_id: int | None = None
    is_director: bool = False

    @property
    def actor(self) -> str:
        """Value stored in *_by columns (docs/04 §1)."""
        return f"{'doctor' if self.kind == 'doctor' else 'acc'}:{self.username}"

    def to_session(self) -> dict:
        return asdict(self)

    @classmethod
    def from_session(cls, data: dict) -> "Principal":
        return cls(**data)


def _check_bcrypt(password: str, stored: bytes | str | None) -> bool:
    if isinstance(stored, str):
        stored = stored.encode("utf-8")
    try:
        return bool(stored) and bcrypt.checkpw(password.encode("utf-8"), stored)
    except ValueError:
        return False


def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None


class AuthService:
    def __init__(self, conn: sqlite3.Connection, bridge: AccountingBridge, now: datetime) -> None:
        self.conn = conn
        self.bridge = bridge
        self.now = now

    # ------------------------------------------------------------ guard
    def _locked_message(self, username: str) -> str | None:
        row = account_repo.guard_get(self.conn, username)
        until = _parse_ts(row["locked_until"]) if row else None
        if until and until > self.now:
            return f"به‌دلیل {MAX_FAILURES} تلاش ناموفق، ورود با این نام کاربری تا ساعت {until:%H:%M} بسته است"
        return None

    def _fail(self, username: str) -> LoginError:
        with transaction(self.conn):
            row = account_repo.guard_get(self.conn, username)
            count = (row["failed_count"] if row else 0) + 1
            locked = None
            if count >= MAX_FAILURES:
                locked = (self.now + timedelta(minutes=LOCK_MINUTES)).strftime(TS_FORMAT)
                count = 0
            account_repo.guard_set(self.conn, username, count, locked)
            account_repo.audit(self.conn, self.now.strftime(TS_FORMAT), username, "auth.fail", "login", username)
        return LoginError(MSG_BAD_CREDENTIALS)

    def _succeed(self, principal: Principal) -> Principal:
        with transaction(self.conn):
            account_repo.guard_clear(self.conn, principal.username)
            account_repo.audit(self.conn, self.now.strftime(TS_FORMAT), principal.actor, "auth.login",
                               "login", principal.username)
        return principal

    # ------------------------------------------------------------ login
    def login(self, username: str, password: str) -> Principal:
        username = (username or "").strip()
        if not username or not password:
            raise LoginError(MSG_EMPTY)
        locked = self._locked_message(username)
        if locked:
            raise LoginError(locked)

        doctor = account_repo.doctor_by_username(self.conn, username)
        if doctor is not None:
            return self._login_doctor(doctor, password)
        return self._login_accounting(username, password)

    def _login_doctor(self, doctor: sqlite3.Row, password: str) -> Principal:
        if not _check_bcrypt(password, doctor["password_hash"]):
            raise self._fail(doctor["username"])
        if not doctor["is_active"]:
            raise LoginError(MSG_DOCTOR_DISABLED)
        try:
            staff, _ = self.bridge.read(read_staff).value
        except CycleSkipped:
            raise LoginError(MSG_BRIDGE_DOWN) from None
        row = next((s for s in staff if s.id == doctor["staff_id"]), None)
        if row is None or row.staff_type != "doctor" or not (row.is_active is None or row.is_active):
            raise LoginError(MSG_STAFF_INACTIVE)
        return self._succeed(Principal("doctor", doctor["username"], "doctor", row.full_name,
                                       staff_id=row.id, doctor_id=doctor["id"],
                                       is_director=bool(doctor["is_director"])))

    def _login_accounting(self, username: str, password: str) -> Principal:
        try:
            user = self.bridge.read(lambda s: read_user(s, username)).value
        except CycleSkipped:
            raise LoginError(MSG_BRIDGE_DOWN) from None
        if user is None:
            _check_bcrypt(password, _DUMMY_HASH)     # same validation as a real check
            raise self._fail(username)
        stored = user.password_hash.encode("utf-8") if isinstance(user.password_hash, str) else user.password_hash
        if not stored or not stored.startswith(b"$2"):
            raise LoginError(MSG_LEGACY_HASH)
        if not _check_bcrypt(password, stored):
            raise self._fail(username)
        acc_locked = _parse_ts(user.locked_until)
        if not user.is_active or (acc_locked and acc_locked > self.now):
            raise LoginError(MSG_ACC_INACTIVE)
        role = ACC_ROLE_MAP.get(user.role)
        if role is None:
            raise LoginError(MSG_DOCTOR_ROLE if user.role == "doctor" else MSG_BAD_CREDENTIALS)
        return self._succeed(Principal("acc", user.username, role, user.full_name or user.username))


# ---------------------------------------------------------------- doctor accounts (manager)
def doctor_accounts(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    """(existing accounts with their staff row, active accounting doctors without an account)."""
    accounts = account_repo.list_doctors(conn)
    linked = {a["staff_id"] for a in accounts}
    return accounts, [d for d in mirror_repo.active_doctors(conn) if d["acc_id"] not in linked]


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD = 6


class AccountError(ValueError):
    pass


def _validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(f"رمز باید دست‌کم {MIN_PASSWORD} نویسه باشد")
    if len(password.encode("utf-8")) > 72:
        raise AccountError("رمز باید حداکثر ۷۲ بایت باشد؛ رمز کوتاه‌تری انتخاب کنید")


def create_doctor(conn: sqlite3.Connection, bridge: AccountingBridge, *, username: str, password: str,
                  staff_id: int, is_director: bool, actor: str, now: datetime) -> int:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise AccountError("نام کاربری باید ۳ تا ۳۲ نویسهٔ لاتین، رقم، نقطه، خط تیره یا زیرخط باشد")
    _validate_password(password)
    if account_repo.doctor_by_username(conn, username):
        raise AccountError("این نام کاربری در پنل وجود دارد")
    if staff_id not in {r["acc_id"] for r in mirror_repo.active_doctors(conn)}:
        raise AccountError("پزشک انتخاب‌شده در کادر درمانِ فعال حسابداری نیست")
    if account_repo.doctor_by_staff(conn, staff_id):
        raise AccountError("برای این پزشک قبلاً حساب ساخته شده است")
    try:
        clash = bridge.read(lambda s: read_user(s, username)).value
    except CycleSkipped:
        raise AccountError("ارتباط با حسابداری برقرار نیست؛ یکتایی نام کاربری قابل بررسی نیست") from None
    if clash is not None:
        raise AccountError("این نام کاربری در حسابداری وجود دارد؛ نام دیگری انتخاب کنید")
    ts = now.strftime(TS_FORMAT)
    with transaction(conn):
        doctor_id = account_repo.insert_doctor(conn, username, hash_password(password), staff_id,
                                               is_director, actor, ts)
        account_repo.audit(conn, ts, actor, "doctor.create", "doctor_account", doctor_id,
                           after={"username": username, "staff_id": staff_id, "is_director": is_director})
    return doctor_id


def update_doctor(conn: sqlite3.Connection, doctor_id: int, *, actor: str, now: datetime,
                  is_director: bool | None = None, is_active: bool | None = None,
                  password: str | None = None) -> None:
    before = account_repo.doctor_by_id(conn, doctor_id)
    if before is None:
        raise AccountError("حساب پیدا نشد")
    fields: dict = {}
    if is_director is not None:
        fields["is_director"] = int(is_director)
    if is_active is not None:
        fields["is_active"] = int(is_active)
    if password is not None:
        _validate_password(password)
        fields["password_hash"] = hash_password(password)
    if not fields:
        return
    ts = now.strftime(TS_FORMAT)
    with transaction(conn):
        account_repo.update_doctor(conn, doctor_id, **fields)
        shown = {k: v for k, v in fields.items() if k != "password_hash"}
        if "password_hash" in fields:
            shown["password"] = "changed"
        account_repo.audit(conn, ts, actor, "doctor.update", "doctor_account", doctor_id,
                           before={k: before[k] for k in ("is_director", "is_active")}, after=shown)
        if is_active:
            account_repo.guard_clear(conn, before["username"])
