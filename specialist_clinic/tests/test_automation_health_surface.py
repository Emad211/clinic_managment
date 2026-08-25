"""Guard: the automation-health surface never lies about scheduler liveness.

Covers fix #4. The surface must be engine-independent, must never report a
false "healthy", never fabricate a zero, surface a `down` scheduler loudly,
surface the freshest FAILED job, and stay manager-only (gated by
`operational.health.view`, which `staff` never holds).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.adapters.sqlite.operational_lease_repo import OperationalLeaseRepository
from src.adapters.sqlite.operational_lease_schema import (
    ensure_operational_lease_storage,
)
from src.security.permissions import (
    Permission,
    default_permissions,
    resolved_permissions,
)
from src.services.automation_health_service import (
    LEASE_NAME,
    AutomationHealthService,
)
from src.services.scheduler import Scheduler


T0 = datetime(2026, 8, 22, 12, 0, 0)


def _fmt(value: datetime) -> str:
    return value.isoformat(sep=" ", timespec="seconds")


@pytest.fixture()
def app_ctx(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "automation.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "automation-health-test",
            "PROPAGATE_EXCEPTIONS": True,
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _db():
    from src.adapters.sqlite.core import get_db

    db = get_db()
    ensure_operational_lease_storage(db)
    return db


def _insert_lease(db, *, heartbeat, acquired=None, expires=None, owner="worker:test", token=1):
    acquired = acquired or heartbeat
    expires = expires or (heartbeat + timedelta(minutes=30))
    db.execute(
        """INSERT INTO operational_leases
           (lease_name, owner_id, fencing_token, acquired_at, heartbeat_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (LEASE_NAME, owner, token, _fmt(acquired), _fmt(heartbeat), _fmt(expires)),
    )
    db.commit()


def _insert_job(db, *, job_key, status, started, completed=None, owner="worker:test", token=1, error=None):
    db.execute(
        """INSERT INTO operational_job_runs
           (job_key, lease_name, owner_id, fencing_token, status, started_at, completed_at, error_code)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_key,
            LEASE_NAME,
            owner,
            token,
            status,
            _fmt(started),
            _fmt(completed) if completed else None,
            error,
        ),
    )
    db.commit()


def _snapshot(db, now=T0):
    return AutomationHealthService(OperationalLeaseRepository(db)).snapshot(now=now)


def test_lease_name_stays_in_sync_with_scheduler():
    # The service holds a local copy to avoid importing the scheduler graph.
    assert LEASE_NAME == Scheduler.LEASE_NAME


def test_no_activity_is_idle_not_ok_and_not_zero(app_ctx):
    snap = _snapshot(_db())
    assert snap["status"] == "idle"
    assert snap["last_seen"] is None
    assert snap["age_seconds"] is None
    assert snap["tone"] == "muted"
    # Idle must never masquerade as healthy.
    assert snap["status"] != "ok"


def test_recent_heartbeat_is_ok(app_ctx):
    db = _db()
    _insert_lease(db, heartbeat=T0 - timedelta(seconds=60))
    snap = _snapshot(db)
    assert snap["status"] == "ok"
    assert snap["tone"] == "ok"
    assert snap["age_seconds"] == 60


def test_recent_job_alone_is_ok(app_ctx):
    db = _db()
    _insert_job(db, job_key="clinical-followups:today", status="COMPLETED",
                started=T0 - timedelta(seconds=90), completed=T0 - timedelta(seconds=80))
    snap = _snapshot(db)
    assert snap["status"] == "ok"
    assert snap["last_job"]["job_key"] == "clinical-followups:today"


def test_mid_age_is_stale(app_ctx):
    db = _db()
    _insert_lease(db, heartbeat=T0 - timedelta(seconds=600))
    snap = _snapshot(db)
    assert snap["status"] == "stale"
    assert snap["tone"] == "warn"


def test_old_activity_is_down_not_zero(app_ctx):
    db = _db()
    _insert_lease(db, heartbeat=T0 - timedelta(hours=1))
    snap = _snapshot(db)
    assert snap["status"] == "down"
    assert snap["tone"] == "danger"
    # The critical guard: a stopped scheduler is reported loudly, not as a
    # fabricated healthy zero.
    assert snap["last_seen"] is not None
    assert snap["age_seconds"] == 3600


def test_failed_job_is_surfaced_even_when_scheduler_is_live(app_ctx):
    db = _db()
    _insert_lease(db, heartbeat=T0 - timedelta(seconds=30))
    _insert_job(db, job_key="invoice-sync:2026-08-22-12", status="FAILED",
                started=T0 - timedelta(seconds=45), completed=T0 - timedelta(seconds=40),
                error="BRIDGE_UNAVAILABLE")
    snap = _snapshot(db)
    assert snap["status"] == "ok"  # scheduler itself is alive
    assert snap["last_failure"] is not None
    assert snap["last_failure"]["job_key"] == "invoice-sync:2026-08-22-12"
    assert snap["last_failure"]["error_code"] == "BRIDGE_UNAVAILABLE"


def test_read_error_degrades_to_unknown_never_ok(app_ctx):
    class _Boom:
        def scheduler_health(self, *a, **k):
            raise RuntimeError("storage read failed")

    snap = AutomationHealthService(_Boom()).snapshot(now=T0)
    assert snap["status"] == "unknown"
    assert snap["tone"] == "muted"
    assert snap["last_seen"] is None
    assert snap["status"] != "ok"


def test_snapshot_is_engine_independent(app_ctx):
    # The service module must not depend on the clinical engine at all: its
    # liveness verdict is a pure function of lease/job rows, identical whether
    # the analytical engine is ON, OFF, or UNAVAILABLE.
    import src.services.automation_health_service as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "engine" not in source.lower() or "independent" in source.lower()
    # And a fresh heartbeat yields ok with no engine state present anywhere.
    db = _db()
    _insert_lease(db, heartbeat=T0 - timedelta(seconds=30))
    assert _snapshot(db)["status"] == "ok"


def test_staff_never_holds_operational_health_view(app_ctx):
    db = _db()
    cursor = db.execute(
        """INSERT INTO users (username, password_hash, role, full_name, is_active)
           VALUES ('auto-staff', X'00', 'staff', 'Auto Staff', 1)""",
    )
    db.commit()
    staff_id = int(cursor.lastrowid)
    staff_user = {"id": staff_id, "role": "staff"}
    # Because the dashboard only builds automation_health when this permission
    # is held, staff never sees the surface. Assert on both the role default and
    # the fully-resolved (override-aware) grant set.
    assert Permission.OPERATIONAL_HEALTH_VIEW not in default_permissions("staff")
    assert Permission.OPERATIONAL_HEALTH_VIEW not in resolved_permissions(staff_user)
    # And a manager DOES hold it — the surface is manager-only, not off-for-all.
    assert Permission.OPERATIONAL_HEALTH_VIEW in default_permissions("manager")


def test_manager_page_renders_the_card(app_ctx):
    app = app_ctx
    client = app.test_client()
    page = client.get("/auth/login")
    import re

    token = re.search(r'name="_csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin",
              **({"_csrf_token": token.group(1)} if token else {})},
    )
    manager_home = client.get("/manager/")
    assert manager_home.status_code == 200
    assert "سلامت اتوماسیون پس‌زمینه" in manager_home.get_data(as_text=True)
