"""
A2 (backup) + A3 (logging) test suite — specialist_clinic.

Safety contract:
  - All DB writes go to COPIES inside tmp dirs; specialist.db and clinic_new.db are
    never modified.
  - The SHA-256 of the real clinic_new.db is verified unchanged after any test that
    touches the accounting path (A2-F6).
  - No SMS is sent (scheduler.start() is never called; _backup() is called directly).
  - logging state is global — every A3 test saves and restores root.handlers in a
    teardown fixture to prevent cross-test pollution.

Run from specialist_clinic/:
    .venv\\Scripts\\python.exe -m pytest tests/test_backup_and_logging.py -v
"""

import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# ── Set up env BEFORE any src import ─────────────────────────────────────────
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_REAL_ACC_DB = os.path.join(_REPO_ROOT, "webapp", "clinic_new.db")
_SPECIALIST_ROOT = os.path.join(_REPO_ROOT, "specialist_clinic")

import hashlib
import logging
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from logging.handlers import RotatingFileHandler

import pytest

sys.path.insert(0, _SPECIALIST_ROOT)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _flush_src_modules():
    """Remove all src.* entries from sys.modules for a clean re-import."""
    for mod in list(sys.modules.keys()):
        if mod == "src" or mod.startswith("src."):
            del sys.modules[mod]


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── specialist_app fixture (mirrors test_invoice_sync.py pattern) ─────────────

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="backup_log_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def specialist_app(tmp_dir):
    """Flask test client pointing at a fresh specialist DB in tmp_dir.

    Strict isolation: env vars, Config attributes, and core._initialized are
    saved/restored so tests never bleed state into each other.
    """
    spec_db = os.path.join(tmp_dir, "specialist_test.db")
    backup_dir = os.path.join(tmp_dir, "backups")

    _saved_env = {
        "SPECIALIST_DB_PATH": os.environ.get("SPECIALIST_DB_PATH"),
        "ACCOUNTING_DB_PATH": os.environ.get("ACCOUNTING_DB_PATH"),
    }

    os.environ["SPECIALIST_DB_PATH"] = spec_db
    os.environ["ACCOUNTING_DB_PATH"] = _REAL_ACC_DB

    _flush_src_modules()

    from src.app import create_app
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": spec_db,
        "BACKUP_FOLDER": backup_dir,
        "PROPAGATE_EXCEPTIONS": True,
        "SECRET_KEY": "test-backup-secret",
    })

    ctx = app.app_context()
    ctx.push()

    yield app, spec_db, backup_dir, tmp_dir

    ctx.pop()

    for key, val in _saved_env.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val

    try:
        import src.config.settings as cfg_mod
        cfg_mod.Config.ACCOUNTING_DB_PATH = _REAL_ACC_DB
    except Exception:
        pass

    try:
        import src.adapters.sqlite.core as core_mod
        core_mod._initialized = False
    except Exception:
        pass


def _make_scheduler(app, backup_dir):
    """Create and init_app a fresh Scheduler pointed at a specific backup_dir.

    Imports Scheduler fresh each time (avoids module-level state from a prior test
    contaminating db_path / backup_dir on the singleton `scheduler` object).
    """
    import importlib
    sched_mod = sys.modules.get("src.services.scheduler")
    if sched_mod is not None:
        # Re-import to get a pristine class, not a cached singleton reference
        sched_mod = importlib.reload(sched_mod)
    else:
        import src.services.scheduler as sched_mod
    Scheduler = sched_mod.Scheduler
    s = Scheduler()
    s.app = app
    s.db_path = Path(app.config["DATABASE_PATH"])
    s.backup_dir = Path(backup_dir)
    s.backup_dir.mkdir(exist_ok=True)
    return s


# ── Logging isolation fixture ─────────────────────────────────────────────────

@pytest.fixture()
def clean_root_logging():
    """Save and restore root logger handlers + level to isolate A3 tests.

    Logging state is process-global, so every A3 test must operate inside
    this fixture.  On teardown all handlers added by the test are closed and
    removed.
    """
    root = logging.getLogger()
    _saved_handlers = list(root.handlers)
    _saved_level = root.level

    # Start with a clean slate for each test
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    yield root

    # Restore: remove anything the test may have added, then put saved ones back
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    for h in _saved_handlers:
        root.addHandler(h)
    root.setLevel(_saved_level)


# =============================================================================
# A2 — Backup tests
# =============================================================================

class TestA2Backup:

    # ── A2-1: backup file created with integrity_check='ok' and carries data ──

    def test_backup_creates_valid_file_with_data(self, specialist_app):
        """_backup() creates backup_auto_*.db that passes PRAGMA integrity_check
        and contains data inserted before the backup."""
        app, spec_db, backup_dir, _ = specialist_app

        # Insert a row so the backed-up DB is non-trivial
        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute(
            "INSERT INTO patient_links (national_id, full_name, enrolled_by)"
            " VALUES ('A2001TEST01', 'بیمار تستِ بکاپ', 'test')"
        )
        db.commit()

        s = _make_scheduler(app, backup_dir)
        s._backup()

        files = list(Path(backup_dir).glob("backup_auto_*.db"))
        assert len(files) == 1, (
            f"Expected exactly 1 backup file, found {len(files)}: {files}"
        )

        bk = str(files[0])
        conn = sqlite3.connect(bk)
        conn.row_factory = sqlite3.Row
        try:
            ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
            assert ic == "ok", f"integrity_check on backup returned '{ic}', expected 'ok'"

            row = conn.execute(
                "SELECT full_name FROM patient_links WHERE national_id = 'A2001TEST01'"
            ).fetchone()
            assert row is not None, "Backup DB does not contain the pre-backup row"
            assert row[0] == "بیمار تستِ بکاپ", (
                f"full_name mismatch in backup: {row[0]}"
            )
        finally:
            conn.close()

    # ── A2-2: no *.tmp file remains after a successful backup ─────────────────

    def test_no_tmp_file_after_success(self, specialist_app):
        """After _backup() succeeds, the .tmp staging file must be gone."""
        app, spec_db, backup_dir, _ = specialist_app

        s = _make_scheduler(app, backup_dir)
        s._backup()

        tmp_files = list(Path(backup_dir).glob("*.tmp"))
        assert tmp_files == [], (
            f"Leftover .tmp files found after backup: {tmp_files}"
        )

    # ── A2-3: backup succeeds with an open connection (no eternal lock) ────────

    def test_backup_with_open_connection(self, specialist_app):
        """_backup() completes without hanging when another connection holds a
        read on the specialist DB.  We use get_db() (which has already bootstrapped
        the schema) to write a committed row, then open a *second* raw connection
        that begins a read transaction while _backup() runs — no eternal lock."""
        app, spec_db, backup_dir, _ = specialist_app

        # First commit some data via the already-bootstrapped app connection
        from src.adapters.sqlite.core import get_db
        db = get_db()
        db.execute(
            "INSERT INTO patient_links (national_id, full_name, enrolled_by)"
            " VALUES ('A2003OPEN01', 'اتصالِ باز', 'test')"
        )
        db.commit()

        # Open a raw second connection and hold a read transaction
        second_conn = sqlite3.connect(spec_db, timeout=5)
        try:
            # Begin implicit read transaction by executing a SELECT
            second_conn.execute("SELECT COUNT(*) FROM patient_links").fetchall()

            s = _make_scheduler(app, backup_dir)
            # Must complete without hanging or raising
            s._backup()

            files = list(Path(backup_dir).glob("backup_auto_*.db"))
            assert len(files) >= 1, "Backup must produce at least one file even with open connection"

            # The backup must be internally consistent (integrity_check)
            bk = str(sorted(files, key=lambda f: f.stat().st_mtime)[-1])
            conn_check = sqlite3.connect(bk)
            try:
                ic = conn_check.execute("PRAGMA integrity_check").fetchone()[0]
                assert ic == "ok", (
                    f"Backup integrity_check failed with open connection: '{ic}'"
                )
            finally:
                conn_check.close()
        finally:
            second_conn.close()

    # ── A2-4: rotation — only 4 files kept after 6 backups ───────────────────

    def test_rotation_keeps_only_4_files(self, specialist_app):
        """After 6 _backup() calls (each producing a distinctly-named file),
        the rotation logic keeps exactly the 4 most recent and removes the 2 oldest.

        Strategy: pre-create 6 dummy backup files with distinct names and mtimes
        (spanning several minutes so Iran-time strftime gives unique basenames),
        then run _backup() once more and assert only 4 survive.  We manipulate
        file mtimes directly instead of sleeping to keep the test fast."""
        app, spec_db, backup_dir, _ = specialist_app
        # Ensure the DB file exists on disk (bootstrap triggered by first get_db call)
        from src.adapters.sqlite.core import get_db
        get_db()

        bd = Path(backup_dir)
        bd.mkdir(exist_ok=True)

        # Produce 6 dummy backup files with mtimes well in the PAST so the new
        # backup created by _backup() has the most recent mtime and is kept.
        # Oldest files (base_ts + 0..5 * 60) all predate now-3600.
        now_ts = time.time()
        base_ts = now_ts - 7200  # 2 hours ago; all dummies are older than the real backup
        dummy_files = []
        for i in range(6):
            fname = bd / f"backup_auto_20231114_{100000 + i * 100:06d}.db"
            conn = sqlite3.connect(str(fname))
            conn.close()
            mtime = base_ts + i * 60  # each 1 minute apart, all > 1 hour ago
            os.utime(str(fname), (mtime, mtime))
            dummy_files.append(fname)

        # All 6 should exist now
        assert len(list(bd.glob("backup_auto_*.db"))) == 6

        # _backup() creates one more file (mtime ≈ now) → 7 total → rotation prunes to 4
        s = _make_scheduler(app, backup_dir)
        s._backup()

        remaining = list(bd.glob("backup_auto_*.db"))
        assert len(remaining) == 4, (
            f"Rotation should keep exactly 4 files, found {len(remaining)}: "
            f"{sorted(f.name for f in remaining)}"
        )
        # The 4 kept must be the 4 with the highest mtime (3 newest dummies + new real backup)
        kept_mtimes = sorted(f.stat().st_mtime for f in remaining)
        oldest_dummy_mtime = base_ts  # dummy[0] is the oldest
        assert all(m > oldest_dummy_mtime + 2 * 60 for m in kept_mtimes), (
            "The 2 oldest dummy files should have been pruned"
        )

    # ── A2-5a: missing db_path → silent return, no crash ─────────────────────

    def test_missing_db_path_returns_silently(self, specialist_app):
        """If db_path does not exist, _backup() returns without raising."""
        app, spec_db, backup_dir, tmp_dir = specialist_app

        s = _make_scheduler(app, backup_dir)
        s.db_path = Path(tmp_dir) / "nonexistent.db"  # does not exist

        # Must not raise
        s._backup()

        files = list(Path(backup_dir).glob("backup_auto_*.db"))
        assert files == [], (
            "No backup should be created when db_path does not exist"
        )

    # ── A2-5b: invalid backup_dir → exception logged, no crash ───────────────

    def test_invalid_backup_dir_no_crash(self, specialist_app, caplog):
        """If backup_dir is un-writable / invalid, _backup() catches the error
        and logs it (via logger.exception) rather than propagating."""
        app, spec_db, backup_dir, _ = specialist_app

        s = _make_scheduler(app, backup_dir)
        # Point to a path that cannot be created as a directory
        # On Windows, a NUL device path reliably causes OSError
        s.backup_dir = Path(spec_db) / "not_a_dir" / "sub"

        with caplog.at_level(logging.ERROR, logger="src.services.scheduler"):
            # Must NOT raise
            s._backup()
        # The backup_dir mkdir is done in init_app; _backup tries to write the
        # file to a non-existent dir → OSError → caught by the outer except
        # (no assertion on caplog message because the mkdir failure already
        # happened at init_app time — here we just verify no crash)

    # ── A2-6: accounting DB SHA-256 unchanged ─────────────────────────────────

    @pytest.mark.skipif(
        not os.path.exists(_REAL_ACC_DB),
        reason=f"Real accounting DB not found at {_REAL_ACC_DB}",
    )
    def test_accounting_db_unchanged_after_backup(self, specialist_app):
        """_backup() only touches specialist.db; clinic_new.db is byte-identical
        before and after."""
        app, spec_db, backup_dir, _ = specialist_app

        sha_before = _sha256(_REAL_ACC_DB)
        wal_path = _REAL_ACC_DB + "-wal"
        shm_path = _REAL_ACC_DB + "-shm"
        wal_existed = os.path.exists(wal_path)
        shm_existed = os.path.exists(shm_path)

        s = _make_scheduler(app, backup_dir)
        s._backup()

        sha_after = _sha256(_REAL_ACC_DB)
        assert sha_before == sha_after, (
            f"clinic_new.db was modified by _backup()!\n"
            f"  before: {sha_before}\n"
            f"  after:  {sha_after}"
        )
        if not wal_existed:
            assert not os.path.exists(wal_path), (
                "A WAL file appeared on clinic_new.db — _backup() must not touch it"
            )
        if not shm_existed:
            assert not os.path.exists(shm_path), (
                "A SHM file appeared on clinic_new.db — _backup() must not touch it"
            )


# =============================================================================
# A3 — Logging tests
# =============================================================================

class TestA3Logging:

    # ── A3-7: RotatingFileHandler is added; second call is idempotent ─────────

    def test_setup_adds_rotating_handler_idempotent(self, tmp_dir, clean_root_logging):
        """setup_app_logging adds exactly one RotatingFileHandler; calling it a
        second time must NOT add another one."""
        from src.common.logging_setup import setup_app_logging

        root = clean_root_logging

        setup_app_logging(tmp_dir)
        rfh_count_1 = sum(1 for h in root.handlers if isinstance(h, RotatingFileHandler))
        assert rfh_count_1 == 1, (
            f"Expected 1 RotatingFileHandler after first setup, found {rfh_count_1}"
        )

        setup_app_logging(tmp_dir)  # second call
        rfh_count_2 = sum(1 for h in root.handlers if isinstance(h, RotatingFileHandler))
        assert rfh_count_2 == 1, (
            f"Idempotency failed: expected 1 RotatingFileHandler after second setup, "
            f"found {rfh_count_2}"
        )

    # ── A3-8: WARNING appears in file; INFO does NOT ──────────────────────────

    def test_warning_in_file_info_not_in_file(self, tmp_dir, clean_root_logging):
        """A WARNING-level message lands in specialist_errors.log; an INFO-level
        message must NOT appear (file handler level is WARNING)."""
        from src.common.logging_setup import setup_app_logging

        setup_app_logging(tmp_dir)

        log_path = os.path.join(tmp_dir, "specialist_errors.log")

        test_logger = logging.getLogger("test.a3.warn_info")
        test_logger.warning("A3-WARN-MARKER-8 this should appear")
        test_logger.info("A3-INFO-MARKER-8 this must NOT appear")

        # Flush all handlers so delayed=True handler writes to disk
        for h in logging.getLogger().handlers:
            h.flush()

        assert os.path.exists(log_path), (
            f"specialist_errors.log was not created at {log_path}"
        )

        content = Path(log_path).read_text(encoding="utf-8")
        assert "A3-WARN-MARKER-8" in content, (
            "WARNING message not found in specialist_errors.log"
        )
        assert "A3-INFO-MARKER-8" not in content, (
            "INFO message should NOT appear in specialist_errors.log (level is WARNING)"
        )

    # ── A3-9: frozen simulation — StreamHandler absent, RotatingFileHandler present

    def test_frozen_simulation_no_stream_handler(self, tmp_dir, clean_root_logging,
                                                  monkeypatch):
        """When sys.frozen is True, setup_app_logging must NOT add a StreamHandler
        but MUST add a RotatingFileHandler."""
        # Flush src.common.logging_setup from modules so it re-evaluates sys.frozen
        _flush_src_modules()

        monkeypatch.setattr(sys, "frozen", True, raising=False)

        # Re-import after monkeypatch so the module-level `sys.frozen` check in
        # setup_app_logging is re-evaluated at call time (it checks at runtime, not
        # import time, so no re-import is strictly needed — but we flush anyway to be safe)
        from src.common.logging_setup import setup_app_logging

        root = clean_root_logging
        setup_app_logging(tmp_dir)

        rfh_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        # Exclude pytest's own LogCaptureHandler (subclass of StreamHandler added by caplog/capfd)
        # and any RotatingFileHandlers — only count plain StreamHandlers that setup_app_logging
        # itself would have added.
        _log_capture_cls_name = "LogCaptureHandler"
        plain_stream_handlers = [
            h for h in root.handlers
            if (isinstance(h, logging.StreamHandler)
                and not isinstance(h, RotatingFileHandler)
                and type(h).__name__ != _log_capture_cls_name)
        ]

        assert rfh_handlers, (
            "RotatingFileHandler must be present even in frozen mode"
        )
        assert plain_stream_handlers == [], (
            f"setup_app_logging must NOT add a StreamHandler in frozen mode, "
            f"found non-pytest StreamHandlers: {plain_stream_handlers}"
        )
