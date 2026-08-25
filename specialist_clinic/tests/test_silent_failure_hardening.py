from __future__ import annotations

from datetime import timedelta
import logging
import sqlite3
import time
from pathlib import Path

import pytest
from flask import Flask


@pytest.fixture()
def secure_app(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "secure.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "silent-failure-test",
            "PROPAGATE_EXCEPTIONS": True,
        }
    )
    context = app.app_context()
    context.push()
    yield app, tmp_path
    context.pop()
    core._initialized = False


def test_activity_log_strict_failure_is_logged_and_raised(monkeypatch, caplog):
    from src.services import activity_logger

    class BrokenDatabase:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("disk full")

        def rollback(self):
            return None

    app = Flask(__name__)
    monkeypatch.setattr(activity_logger, "get_db", lambda: BrokenDatabase())
    with app.app_context(), caplog.at_level(logging.ERROR):
        with pytest.raises(activity_logger.ActivityLogError):
            activity_logger.log_activity("test-action", strict=True)

    assert "activity audit write failed" in caplog.text
    assert "disk full" in caplog.text


def test_committed_first_run_is_not_reported_as_retryable_failure(
    tmp_path, monkeypatch, caplog
):
    from src.adapters.sqlite import core
    from src.app import create_app
    from src.services import activity_logger

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "PROPAGATE_EXCEPTIONS": False,
            "DATABASE_PATH": str(tmp_path / "first-run.db"),
            "ACCOUNTING_DB_PATH": str(tmp_path / "accounting.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "first-run-audit-regression",
            "CREATE_TEST_ADMIN": False,
            "START_SCHEDULER": False,
            "CSRF_PROTECTION_ENABLED": False,
        }
    )

    class BrokenAuditDatabase:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("audit unavailable")

        def rollback(self):
            return None

    monkeypatch.setattr(
        activity_logger, "get_db", lambda: BrokenAuditDatabase()
    )
    with caplog.at_level(logging.ERROR):
        response = app.test_client().post(
            "/auth/setup",
            data={
                "username": "clinic_manager",
                "full_name": "مدیر درمانگاه",
                "password": "SafeClinicPass2026",
                "password_confirm": "SafeClinicPass2026",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    with app.app_context():
        row = core.get_db().execute(
            "SELECT username FROM users WHERE username='clinic_manager'"
        ).fetchone()
        assert row is not None
    assert app.extensions["activity_audit_healthy"] is False
    assert "activity audit write failed" in caplog.text

    restarted = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "first-run.db"),
            "ACCOUNTING_DB_PATH": str(tmp_path / "accounting.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups-restarted"),
            "SECRET_KEY": "first-run-audit-regression-restarted",
            "CREATE_TEST_ADMIN": False,
            "START_SCHEDULER": False,
            "CSRF_PROTECTION_ENABLED": False,
        }
    )
    assert restarted.extensions["activity_audit_healthy"] is False

    monkeypatch.undo()
    from src.services.activity_logger import acknowledge_activity_audit_gap

    with restarted.app_context():
        assert acknowledge_activity_audit_gap("pytest-operator") is True
    assert restarted.extensions["activity_audit_healthy"] is True
    clean_restart = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "first-run.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups-clean"),
            "SECRET_KEY": "clean-restart",
            "START_SCHEDULER": False,
        }
    )
    assert clean_restart.extensions["activity_audit_healthy"] is True


def test_condition_metadata_seed_failure_aborts_migration():
    from src.adapters.sqlite.core import _seed_condition_meta

    class PartiallyFailingDatabase:
        def __init__(self):
            self.calls = 0

        def execute(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 2:
                raise sqlite3.OperationalError("seed write failed")
            return None

        def commit(self):
            return None

    with pytest.raises(sqlite3.OperationalError, match="seed write failed"):
        _seed_condition_meta(PartiallyFailingDatabase())


def test_partial_additive_migration_is_explicitly_resumable():
    from src.adapters.sqlite.core import _ensure_column

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
    _ensure_column(db, "sample", "added_once", "TEXT")
    with pytest.raises(sqlite3.OperationalError):
        _ensure_column(db, "missing_later_table", "value", "TEXT")
    db.rollback()

    # A committed earlier additive step remains, and replay is a safe no-op.
    _ensure_column(db, "sample", "added_once", "TEXT")
    columns = [row["name"] for row in db.execute("PRAGMA table_info(sample)")]
    assert columns.count("added_once") == 1


def test_ensure_column_does_not_hide_invalid_migration():
    from src.adapters.sqlite.core import _ensure_column

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    with pytest.raises(sqlite3.OperationalError):
        _ensure_column(db, "missing_table", "new_column", "TEXT")


def test_schema_contract_requires_critical_indexes():
    from src.adapters.sqlite.core import schema_contract_ok

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE sms_messages(id INTEGER, idempotency_key TEXT,
          provider TEXT, next_status_check_at TEXT, delivery_status TEXT);
        CREATE TABLE wallet_transactions(id INTEGER, idempotency_key TEXT);
        """
    )
    assert schema_contract_ok(db) is False


def test_readiness_detects_old_tehran_job_without_live_lease(secure_app):
    from src.adapters.sqlite.core import get_db
    from src.api.health import _readiness_checks
    from src.common.utils import iran_now

    db = get_db()
    old = (iran_now().replace(tzinfo=None) - timedelta(hours=3)).isoformat(
        sep=" ", timespec="seconds"
    )
    db.execute(
        """INSERT INTO operational_job_runs
           (job_key, lease_name, owner_id, fencing_token, status, started_at)
           VALUES ('stuck:test', 'scheduler:test', 'dead-worker', 1, 'RUNNING', ?)""",
        (old,),
    )
    db.commit()

    assert _readiness_checks()["worker"] is False


def test_ready_logs_internal_failure_without_disclosing_it(secure_app, monkeypatch, caplog):
    from src.api import health

    app, _ = secure_app
    monkeypatch.setattr(
        health,
        "_readiness_checks",
        lambda: (_ for _ in ()).throw(RuntimeError("private-detail")),
    )
    with caplog.at_level(logging.ERROR):
        response = app.test_client().get("/health/ready")

    assert response.status_code == 503
    assert response.get_json() == {"status": "not_ready"}
    assert "readiness check failed" in caplog.text
    assert "private-detail" not in response.get_data(as_text=True)


def test_backup_deadline_removes_partial_artifacts(tmp_path):
    from src.services.backup_integrity import BackupIntegrityService, BackupTimeoutError

    source = tmp_path / "source.db"
    db = sqlite3.connect(source)
    db.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
    db.executemany("INSERT INTO sample(value) VALUES (?)", [("x" * 2000,)] * 1000)
    db.commit()
    db.close()

    ticks = iter((0.0, 2.0, 2.0, 2.0))
    service = BackupIntegrityService(clock=lambda: next(ticks, 2.0))
    with pytest.raises(BackupTimeoutError):
        service.create(source, tmp_path / "backups", deadline_seconds=1)

    assert list((tmp_path / "backups").iterdir()) == []


def test_backup_manifest_failure_removes_published_database(
    tmp_path, monkeypatch
):
    from src.services.backup_integrity import BackupIntegrityService

    source = tmp_path / "source.db"
    db = sqlite3.connect(source)
    db.execute("CREATE TABLE sample(value TEXT)")
    db.execute("INSERT INTO sample VALUES ('safe')")
    db.commit()
    db.close()
    original_write_text = Path.write_text

    def fail_manifest_write(path, *args, **kwargs):
        if path.name.endswith(".manifest.json.tmp"):
            raise OSError("manifest disk failure")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_manifest_write)
    backup_dir = tmp_path / "backups"
    with pytest.raises(OSError, match="manifest disk failure"):
        BackupIntegrityService().create(source, backup_dir, prefix="atomic")

    assert list(backup_dir.glob("atomic_*.db")) == []
    assert list(backup_dir.glob("atomic_*.manifest.json")) == []


def test_accounting_query_error_has_distinct_api_contract(tmp_path):
    from src.adapters.accounting_bridge import AccountingBridgeQueryError
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "typed-errors.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "typed-error-contract",
            "START_SCHEDULER": False,
        }
    )

    @app.get("/patients/api/query-error")
    def query_error():
        raise AccountingBridgeQueryError("internal schema detail")

    response = app.test_client().get("/patients/api/query-error")
    assert response.status_code == 503
    assert response.get_json() == {
        "error": {
            "code": "ACCOUNTING_BRIDGE_READ_FAILED",
            "message": "خواندن دیتابیس حسابداری ممکن نیست؛ ساختار یا سلامت فایل را بررسی کنید.",
        }
    }
    assert "internal schema detail" not in response.get_data(as_text=True)


def test_accounting_bridge_does_not_misclassify_programming_errors(monkeypatch):
    from src.adapters import accounting_bridge

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE patients(id INTEGER)")
    monkeypatch.setattr(accounting_bridge, "_connect_ro", lambda: db)
    monkeypatch.setattr(
        accounting_bridge,
        "_patient_name_expression",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("programming defect")
        ),
    )

    with pytest.raises(RuntimeError, match="programming defect"):
        accounting_bridge.search_patients("x")


def test_scheduler_heartbeats_during_long_callback(monkeypatch):
    from src.adapters.sqlite.operational_lease_repo import Lease
    from src.services import scheduler as scheduler_module

    lease = Lease("lease", "owner", 9, "a", "h", "e")

    class FakeLeaseRepository:
        renewals = 0

        def begin_job(self, _job_key, _lease):
            return True

        def renew(self, current, **_kwargs):
            type(self).renewals += 1
            return current

        def finish_job(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        scheduler_module, "OperationalLeaseRepository", FakeLeaseRepository
    )
    scheduler = scheduler_module.Scheduler(app=Flask(__name__))
    scheduler.LEASE_HEARTBEAT_SECONDS = 0.01

    def callback():
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            if FakeLeaseRepository.renewals:
                return True
            time.sleep(0.005)
        return False

    assert scheduler._run_once(
        job_name="long-job",
        period_key="once",
        lease=lease,
        callback=callback,
    ) is True
    assert FakeLeaseRepository.renewals >= 1


def test_scheduler_renews_lease_before_every_job(monkeypatch):
    from datetime import datetime

    from src.adapters.sqlite.operational_lease_repo import Lease
    from src.services import scheduler as scheduler_module

    # Hermetic clock: the weekly verified-backup job only enrols on Saturday
    # 03:xx Tehran, which would inflate the fixed job count to 9. Pin a
    # non-backup instant so the expected count (8) is deterministic regardless
    # of the wall clock the suite happens to run on.
    fixed_now = datetime(2026, 8, 19, 12, 0, 0)  # Wednesday, noon

    initial = Lease("lease", "owner", 7, "a", "h0", "e0")

    class FakeLeases:
        instance = None

        def __init__(self):
            self.renewed = []
            self.released = None
            FakeLeases.instance = self

        def acquire(self, *_args, **_kwargs):
            return initial

        def renew(self, lease, **_kwargs):
            renewed = Lease(
                lease.lease_name,
                lease.owner_id,
                lease.fencing_token,
                lease.acquired_at,
                f"h{len(self.renewed) + 1}",
                f"e{len(self.renewed) + 1}",
            )
            self.renewed.append(renewed)
            return renewed

        def release(self, lease):
            self.released = lease

    seen = []
    monkeypatch.setattr(scheduler_module, "OperationalLeaseRepository", FakeLeases)
    scheduler = scheduler_module.Scheduler()
    monkeypatch.setattr(scheduler_module, "iran_now", lambda: fixed_now)
    monkeypatch.setattr(
        scheduler,
        "_run_once",
        lambda **kwargs: seen.append(kwargs["lease"]) or True,
    )

    scheduler._tick()

    leases = FakeLeases.instance
    assert len(leases.renewed) == len(seen) == 8
    assert seen == leases.renewed
    assert leases.released == leases.renewed[-1]
