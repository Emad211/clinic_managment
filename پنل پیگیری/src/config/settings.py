"""Runtime paths and ``config.ini`` (docs/02 §7).

``config.ini`` lives next to the exe (or next to ``start.py`` from source) and
is created with defaults on first run. The bridge safety limits can be lowered
in the file but never raised above the hard caps of docs/03 §1.
"""
from __future__ import annotations

import configparser
import ipaddress
import logging
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_FILENAME = "config.ini"
PANEL_DB_FILENAME = "peygiri_panel.db"

# Hard caps from docs/03 §1 — config may lower these, never raise them.
MAX_READ_BUDGET_MS = 200
MAX_BUSY_TIMEOUT_MS = 250
POLL_SECONDS_RANGE = (5, 10)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    """Folder that holds config.ini, the panel DB, backups/ and logs/."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_dir() -> Path:
    """Folder that holds bundled read-only files (templates, static, schema.sql)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """config.ini has a value that cannot be used."""


@dataclass(frozen=True)
class Settings:
    accounting_db_path: str            # empty → bridge disabled until set
    host: str
    port: int
    open_browser: bool
    allowed_clients: tuple[str, ...]
    poll_seconds: int
    read_budget_ms: int
    busy_timeout_ms: int
    secret_key: str
    base_dir: Path = field(default_factory=base_dir)

    @property
    def panel_db_path(self) -> Path:
        return self.base_dir / PANEL_DB_FILENAME

    @property
    def backups_dir(self) -> Path:
        return self.base_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"


_TEMPLATE = """\
; پنل پیگیری — تنظیمات. پس از تغییر، برنامه را دوباره اجرا کنید.

[accounting]
; مسیر فایل دیتابیس حسابداری. فقط خوانده می‌شود و هرگز تغییر نمی‌کند.
db_path = {db_path}

[server]
; 0.0.0.0 یعنی کامپیوتر پذیرش هم از شبکهٔ داخلی دسترسی دارد.
host = {host}
port = {port}
open_browser = {open_browser}
; اختیاری: فهرست IPهای مجاز با کاما، مثلاً 127.0.0.1, 192.168.1.20
allowed_clients = {allowed_clients}

[sync]
; فاصلهٔ پایش حسابداری به ثانیه (۵ تا ۱۰).
poll_seconds = {poll_seconds}
; سقف سخت هر چرخهٔ خواندن (حداکثر 200).
read_budget_ms = {read_budget_ms}
; اگر حسابداری مشغول نوشتن بود، تا این زمان صبر و سپس رد کردن چرخه (حداکثر 250).
busy_timeout_ms = {busy_timeout_ms}

[app]
; کلید امضای نشست. خالی بماند تا خودکار ساخته شود.
secret_key = {secret_key}
"""

_DEFAULTS = {
    "db_path": "",
    "host": "0.0.0.0",
    "port": "8091",
    "open_browser": "true",
    "allowed_clients": "",
    "poll_seconds": "5",
    "read_budget_ms": str(MAX_READ_BUDGET_MS),
    "busy_timeout_ms": str(MAX_BUSY_TIMEOUT_MS),
    "secret_key": "",
}


def _write(path: Path, values: dict[str, str]) -> None:
    tmp = path.with_suffix(".ini.tmp")
    tmp.write_text(_TEMPLATE.format(**values), encoding="utf-8")
    tmp.replace(path)


def _read_raw(path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    with path.open(encoding="utf-8-sig") as fh:  # tolerate a BOM from Notepad
        parser.read_file(fh)
    section_of = {
        "db_path": "accounting",
        "host": "server", "port": "server", "open_browser": "server", "allowed_clients": "server",
        "poll_seconds": "sync", "read_budget_ms": "sync", "busy_timeout_ms": "sync",
        "secret_key": "app",
    }
    return {
        key: parser.get(section, key, fallback=_DEFAULTS[key]).strip()
        for key, section in section_of.items()
    }


def _int(values: dict[str, str], key: str) -> int:
    try:
        return int(values[key])
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got {values[key]!r}") from None


def _capped(values: dict[str, str], key: str, cap: int) -> int:
    value = _int(values, key)
    if value <= 0:
        raise ConfigError(f"{key} must be positive, got {value}")
    if value > cap:
        log.warning("%s=%d is above the safety cap; using %d", key, value, cap)
        return cap
    return value


def _bool(values: dict[str, str], key: str) -> bool:
    raw = values[key].lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be true or false, got {values[key]!r}")


def _clients(raw: str) -> tuple[str, ...]:
    out = []
    for item in filter(None, (part.strip() for part in raw.split(","))):
        try:
            out.append(str(ipaddress.ip_address(item)))
        except ValueError:
            raise ConfigError(f"allowed_clients has an invalid IP address: {item!r}") from None
    return tuple(out)


def load_settings(directory: Path | None = None) -> Settings:
    """Read config.ini, creating it (and a secret key) on first run."""
    directory = directory or base_dir()
    path = directory / CONFIG_FILENAME
    if path.exists():
        values = _read_raw(path)
    else:
        values = dict(_DEFAULTS)
        log.info("config.ini not found; creating %s", path)

    if not values["secret_key"]:
        values["secret_key"] = secrets.token_hex(32)
        _write(path, values)
    elif not path.exists():
        _write(path, values)

    port = _int(values, "port")
    if not 1 <= port <= 65535:
        raise ConfigError(f"port out of range: {port}")
    poll = _int(values, "poll_seconds")
    lo, hi = POLL_SECONDS_RANGE
    if not lo <= poll <= hi:
        raise ConfigError(f"poll_seconds must be between {lo} and {hi}, got {poll}")

    return Settings(
        accounting_db_path=values["db_path"],
        host=values["host"] or _DEFAULTS["host"],
        port=port,
        open_browser=_bool(values, "open_browser"),
        allowed_clients=_clients(values["allowed_clients"]),
        poll_seconds=poll,
        read_budget_ms=_capped(values, "read_budget_ms", MAX_READ_BUDGET_MS),
        busy_timeout_ms=_capped(values, "busy_timeout_ms", MAX_BUSY_TIMEOUT_MS),
        secret_key=values["secret_key"],
        base_dir=directory,
    )
