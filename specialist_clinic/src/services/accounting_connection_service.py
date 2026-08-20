"""Configure and verify the live, read-only Hesabdari Sib database connection."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import sqlite3
from typing import Iterable

from flask import current_app

from src.adapters.sqlite.system_settings_repo import SystemSettingsRepository


SETTING_KEY = "accounting_db_path"

_REQUIRED_COLUMNS = {
    "patients": {
        "id",
        "national_id",
        "phone_number",
        "gender",
        "birthdate",
        "address",
        "insurance_type",
        "insurance_expiry",
        "is_foreign",
    },
    "invoices": {
        "id",
        "patient_id",
        "status",
        "work_date",
        "opened_at",
        "closed_at",
        "total_amount",
    },
    "visits": {"id", "invoice_id", "price"},
    "injections": {"id", "invoice_id", "total_price"},
    "procedures": {"id", "invoice_id", "price"},
    "invoice_item_payments": {
        "invoice_id",
        "item_type",
        "item_id",
        "is_paid",
    },
}


class AccountingConnectionError(ValueError):
    """A user-correctable accounting connection problem."""


@dataclass(frozen=True, slots=True)
class AccountingConnectionStatus:
    ok: bool
    path: str
    source: str
    source_label: str
    message: str
    patient_count: int | None = None
    database_size_bytes: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class AccountingConnectionService:
    def __init__(
        self,
        repository: SystemSettingsRepository | None = None,
    ):
        self.repository = repository or SystemSettingsRepository()

    def configured_path(self) -> tuple[str, str]:
        environment = str(os.environ.get("ACCOUNTING_DB_PATH") or "").strip()
        if environment:
            return environment, "environment"
        saved = str(self.repository.get(SETTING_KEY, "") or "").strip()
        if saved:
            return saved, "saved"
        return str(current_app.config.get("ACCOUNTING_DB_PATH") or ""), "default"

    @staticmethod
    def _source_label(source: str) -> str:
        return {
            "environment": "تنظیم سیستمی",
            "saved": "ذخیره‌شده در کلینیک",
            "default": "مسیر پیش‌فرض",
        }.get(source, "مسیر انتخاب‌شده")

    @staticmethod
    def normalize(raw_path: str) -> Path:
        supplied = str(raw_path or "").strip().strip('"').strip("'")
        if not supplied:
            raise AccountingConnectionError("نشانی دیتابیس حسابداری وارد نشده است.")
        if "://" in supplied:
            raise AccountingConnectionError(
                "فقط مسیر محلی ویندوز قابل استفاده است؛ نشانی اینترنتی وارد نکنید."
            )
        expanded = os.path.expandvars(os.path.expanduser(supplied))
        if expanded.startswith("\\\\"):
            raise AccountingConnectionError(
                "دیتابیس SQLite باید روی همین سیستم باشد؛ مسیر شبکه‌ای مجاز نیست."
            )
        candidate = Path(expanded)
        if candidate.is_dir():
            candidate = candidate / "clinic_new.db"
        elif candidate.suffix.lower() == ".exe":
            candidate = candidate.with_name("clinic_new.db")
        try:
            return candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise AccountingConnectionError("مسیر واردشده قابل پردازش نیست.") from exc

    @staticmethod
    def _table_columns(
        connection: sqlite3.Connection,
        table: str,
    ) -> set[str]:
        return {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def validate(self, raw_path: str) -> AccountingConnectionStatus:
        path = self.normalize(raw_path)
        if not path.is_file():
            raise AccountingConnectionError(
                "فایل clinic_new.db در این مسیر پیدا نشد. مسیر فایل، پوشه یا "
                "HesabdariSib.exe را وارد کنید."
            )
        try:
            specialist_path = Path(current_app.config["DATABASE_PATH"]).resolve()
            if path == specialist_path:
                raise AccountingConnectionError(
                    "این فایل دیتابیس خود کلینیک تخصصی است، نه حسابداری سیب."
                )
        except KeyError:
            pass

        try:
            with path.open("rb") as stream:
                if stream.read(16) != b"SQLite format 3\x00":
                    raise AccountingConnectionError(
                        "فایل انتخاب‌شده یک دیتابیس معتبر SQLite نیست."
                    )
        except OSError as exc:
            raise AccountingConnectionError(
                "کلینیک اجازهٔ خواندن فایل انتخاب‌شده را ندارد."
            ) from exc

        connection = None
        try:
            connection = sqlite3.connect(
                f"{path.as_uri()}?mode=ro",
                uri=True,
                timeout=10,
            )
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            quick = connection.execute("PRAGMA quick_check").fetchone()
            if not quick or str(quick[0]).lower() != "ok":
                raise AccountingConnectionError(
                    "بررسی سلامت دیتابیس حسابداری موفق نبود."
                )

            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            missing_tables = sorted(set(_REQUIRED_COLUMNS) - tables)
            if missing_tables:
                raise AccountingConnectionError(
                    "این فایل ساختار حسابداری سیب را ندارد "
                    f"({', '.join(missing_tables)})."
                )
            for table, expected in _REQUIRED_COLUMNS.items():
                actual_columns = self._table_columns(connection, table)
                missing = sorted(expected - actual_columns)
                if missing:
                    raise AccountingConnectionError(
                        f"ساختار جدول {table} با حسابداری سیب سازگار نیست."
                    )
                if table == "patients" and not (
                    "full_name" in actual_columns
                    or "name" in actual_columns
                ):
                    raise AccountingConnectionError(
                        "ساختار نام بیمار در جدول patients قابل شناسایی نیست."
                    )

            try:
                connection.execute(
                    "CREATE TABLE __specialist_readonly_probe (id INTEGER)"
                )
            except sqlite3.OperationalError:
                write_blocked = True
            else:
                write_blocked = False
            if not write_blocked:
                raise AccountingConnectionError(
                    "اتصال فقط‌خواندنی تأیید نشد؛ مسیر ذخیره نشد."
                )

            patient_count = int(
                connection.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
            )
        except AccountingConnectionError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise AccountingConnectionError(
                "بازکردن دیتابیس حسابداری ممکن نشد؛ فایل یا دسترسی آن را بررسی کنید."
            ) from exc
        finally:
            if connection is not None:
                connection.close()

        return AccountingConnectionStatus(
            ok=True,
            path=str(path),
            source="candidate",
            source_label=self._source_label("candidate"),
            message="اتصال زنده و فقط‌خواندنی تأیید شد.",
            patient_count=patient_count,
            database_size_bytes=path.stat().st_size,
        )

    def status(self) -> AccountingConnectionStatus:
        path, source = self.configured_path()
        try:
            checked = self.validate(path)
        except AccountingConnectionError as exc:
            return AccountingConnectionStatus(
                ok=False,
                path=str(path),
                source=source,
                source_label=self._source_label(source),
                message=str(exc),
            )
        return AccountingConnectionStatus(
            ok=True,
            path=checked.path,
            source=source,
            source_label=self._source_label(source),
            message=checked.message,
            patient_count=checked.patient_count,
            database_size_bytes=checked.database_size_bytes,
        )

    def save(self, raw_path: str) -> AccountingConnectionStatus:
        if str(os.environ.get("ACCOUNTING_DB_PATH") or "").strip():
            raise AccountingConnectionError(
                "مسیر با تنظیم سیستمی ACCOUNTING_DB_PATH قفل شده است؛ "
                "برای مدیریت از داخل کلینیک ابتدا آن تنظیم را حذف کنید."
            )
        checked = self.validate(raw_path)
        self.repository.set(SETTING_KEY, checked.path)
        current_app.config["ACCOUNTING_DB_PATH"] = checked.path
        return AccountingConnectionStatus(
            ok=True,
            path=checked.path,
            source="saved",
            source_label=self._source_label("saved"),
            message=checked.message,
            patient_count=checked.patient_count,
            database_size_bytes=checked.database_size_bytes,
        )

    @staticmethod
    def _candidate_paths(roots: Iterable[Path]) -> list[Path]:
        candidates: list[Path] = []
        for root in roots:
            base = Path(root)
            candidates.extend(
                (
                    base / "webapp" / "dist" / "clinic_new.db",
                    base / "HesabdariSib" / "clinic_new.db",
                    base / "dist" / "clinic_new.db",
                    base / "clinic_new.db",
                    base / "webapp" / "clinic_new.db",
                )
            )
        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = os.path.normcase(str(candidate))
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return unique

    def discover(self, roots: Iterable[Path] | None = None) -> AccountingConnectionStatus:
        if roots is None:
            project_root = Path(current_app.config.get("PROJECT_ROOT") or Path.cwd())
            ancestry = [project_root, *list(project_root.parents)[:4]]
            roots = ancestry
        errors: list[str] = []
        for candidate in self._candidate_paths(roots):
            if not candidate.is_file():
                continue
            try:
                return self.validate(str(candidate))
            except AccountingConnectionError as exc:
                errors.append(str(exc))
        detail = errors[0] if errors else "هیچ فایل clinic_new.db سازگاری پیدا نشد."
        raise AccountingConnectionError(
            "یافتن خودکار حسابداری سیب موفق نبود. مسیر را دستی وارد کنید. " + detail
        )

    def discover_and_save(self) -> AccountingConnectionStatus:
        discovered = self.discover()
        return self.save(discovered.path)


__all__ = [
    "AccountingConnectionError",
    "AccountingConnectionService",
    "AccountingConnectionStatus",
    "SETTING_KEY",
]
