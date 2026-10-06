"""Panel database: connections, schema install and migrations (docs/04 §1).

``peygiri_panel.db`` is WAL with ``foreign_keys=ON`` and ``busy_timeout=5000``.
Connections use ``isolation_level=None``; writes go through :func:`transaction`
so every write is one short explicit transaction.

Before any schema upgrade of an existing database a consistent backup is taken
with the SQLite backup API.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from ...common import iran_time
from ...config.settings import resource_dir

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4
KEEP_BACKUPS = 4

# version → additive, re-runnable step that brings the DB from version-1 to version.
def _migrate_v2(conn: sqlite3.Connection) -> None:
    """M1: preserve an M0 mirror while adding the visit timestamp used by the queue."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(acc_item)")}
    if "item_at" not in columns:
        conn.execute("ALTER TABLE acc_item ADD COLUMN item_at TEXT")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """M2: baseline existing mirror at upgrade time; never invent historical quality."""
    from . import identity_repo
    identity_repo.observe_invoices(conn, identity_repo.all_invoice_ids(conn), iran_time.now_str())


_V4_STEP_COLUMNS = {
    "accept_early": "INTEGER NOT NULL DEFAULT 0",
    "recall_on_miss": "INTEGER NOT NULL DEFAULT 0",
    "completes": "INTEGER NOT NULL DEFAULT 0",
    "about_category": "TEXT",
}


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """M3: per-step rule flags copied from the template when the journey is planned."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(journey_step)")}
    for name, ddl in _V4_STEP_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE journey_step ADD COLUMN {name} {ddl}")
    if "chronic_tags" not in {row[1] for row in conn.execute("PRAGMA table_info(encounter)")}:
        conn.execute("ALTER TABLE encounter ADD COLUMN chronic_tags TEXT")


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {2: _migrate_v2, 3: _migrate_v3, 4: _migrate_v4}


def schema_sql() -> str:
    return (resource_dir() / "src" / "adapters" / "sqlite" / "schema.sql").read_text(encoding="utf-8")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5, isolation_level=None, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE … COMMIT, rolled back on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


@contextmanager
def savepoint(conn: sqlite3.Connection, name: str) -> Iterator[sqlite3.Connection]:
    """Nested unit inside an open transaction: on error only its own writes are undone, then re-raise."""
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield conn
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    conn.execute(f"RELEASE {name}")


def _current_version(conn: sqlite3.Connection) -> int | None:
    """None for an empty file, 0 for a file with tables but no version row."""
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'").fetchone()
    if not has_meta:
        any_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1").fetchone()
        return 0 if any_table else None
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
    return int(row[0]) if row else 0


def backup(conn: sqlite3.Connection, backups_dir: Path, label: str, when=None) -> Path:
    """Consistent copy via the backup API; keeps the newest KEEP_BACKUPS per label."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = (when or iran_time.now()).strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"peygiri_panel_{label}_{stamp}.db"
    target = sqlite3.connect(str(dest))
    try:
        conn.backup(target)
    finally:
        target.close()
    old = sorted(backups_dir.glob(f"peygiri_panel_{label}_*.db"))
    for stale in old[:-KEEP_BACKUPS]:
        stale.unlink(missing_ok=True)
    log.info("panel DB backup written: %s", dest.name)
    return dest


def init_db(path: Path, backups_dir: Path) -> int:
    """Create or upgrade the panel DB. Returns the schema version now in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError(f"could not enable WAL on the panel DB (got {mode})")
        version = _current_version(conn)
        if version is not None and version > SCHEMA_VERSION:
            raise RuntimeError(
                f"panel DB schema v{version} is newer than this program (v{SCHEMA_VERSION}); "
                "run the newer PeygiriPanel.exe")
        if version == SCHEMA_VERSION:
            return version
        if version is not None:
            backup(conn, backups_dir, f"pre-migration-v{version}")

        now = iran_time.now_str()
        conn.executescript(schema_sql())        # idempotent; runs outside our transaction
        with transaction(conn):
            for step in range(max(version or 0, 1) + 1, SCHEMA_VERSION + 1):
                MIGRATIONS[step](conn)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(SCHEMA_VERSION),))
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('created_at', ?)", (now,))
        log.info("panel DB schema: %s → v%d", "new" if version is None else f"v{version}", SCHEMA_VERSION)
        return SCHEMA_VERSION
    finally:
        conn.close()
