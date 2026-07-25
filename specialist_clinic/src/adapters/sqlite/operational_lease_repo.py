"""Atomic SQLite leases and durable idempotency records for background jobs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.operational_lease_schema import (
    ensure_operational_lease_storage,
)
from src.common.utils import iran_now


@dataclass(frozen=True, slots=True)
class Lease:
    lease_name: str
    owner_id: str
    fencing_token: int
    acquired_at: str
    heartbeat_at: str
    expires_at: str


class LeaseLost(RuntimeError):
    pass


def _local_naive(value: datetime | None = None) -> datetime:
    current = value or iran_now()
    if current.tzinfo is not None:
        return current.replace(tzinfo=None)
    return current


def _text(value: datetime) -> str:
    return value.isoformat(sep=" ", timespec="seconds")


class OperationalLeaseRepository:
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self):
        db = self._connection or get_db()
        ensure_operational_lease_storage(db)
        return db

    def acquire(
        self,
        lease_name: str,
        *,
        owner_id: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> Lease | None:
        name = str(lease_name or "").strip()
        owner = str(owner_id or "").strip()
        if len(name) < 3 or len(owner) < 3:
            raise ValueError("lease_name and owner_id are required")
        if not 10 <= int(ttl_seconds) <= 86400:
            raise ValueError("lease ttl must be between 10 seconds and one day")
        current = _local_naive(now)
        expiry = current + timedelta(seconds=int(ttl_seconds))
        db = self._db()
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT * FROM operational_leases WHERE lease_name=?",
                (name,),
            ).fetchone()
            if row and datetime.fromisoformat(row["expires_at"]) > current:
                db.rollback()
                return None
            # Lease rows are never deleted on normal release. Keeping the row makes
            # the fencing token monotonic across clean releases and process restarts.
            token = int(row["fencing_token"] or 0) + 1 if row else 1
            values = (
                owner,
                token,
                _text(current),
                _text(current),
                _text(expiry),
            )
            if row:
                db.execute(
                    """UPDATE operational_leases
                       SET owner_id=?, fencing_token=?, acquired_at=?,
                           heartbeat_at=?, expires_at=?
                       WHERE lease_name=?""",
                    (*values, name),
                )
            else:
                db.execute(
                    """INSERT INTO operational_leases
                       (lease_name, owner_id, fencing_token, acquired_at,
                        heartbeat_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, *values),
                )
            db.commit()
            return Lease(
                lease_name=name,
                owner_id=owner,
                fencing_token=token,
                acquired_at=_text(current),
                heartbeat_at=_text(current),
                expires_at=_text(expiry),
            )
        except Exception:
            db.rollback()
            raise

    def renew(
        self,
        lease: Lease,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> Lease:
        if not 10 <= int(ttl_seconds) <= 86400:
            raise ValueError("lease ttl must be between 10 seconds and one day")
        current = _local_naive(now)
        expiry = current + timedelta(seconds=int(ttl_seconds))
        db = self._db()
        with db:
            cursor = db.execute(
                """UPDATE operational_leases
                   SET heartbeat_at=?, expires_at=?
                   WHERE lease_name=? AND owner_id=? AND fencing_token=?
                     AND datetime(expires_at)>datetime(?)""",
                (
                    _text(current),
                    _text(expiry),
                    lease.lease_name,
                    lease.owner_id,
                    lease.fencing_token,
                    _text(current),
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLost("operational lease is no longer owned")
        return Lease(
            lease_name=lease.lease_name,
            owner_id=lease.owner_id,
            fencing_token=lease.fencing_token,
            acquired_at=lease.acquired_at,
            heartbeat_at=_text(current),
            expires_at=_text(expiry),
        )

    def release(self, lease: Lease, *, now: datetime | None = None) -> bool:
        """Expire the lease without deleting its monotonic fencing-token row."""
        current = _local_naive(now)
        db = self._db()
        with db:
            cursor = db.execute(
                """UPDATE operational_leases
                   SET heartbeat_at=?, expires_at=?
                   WHERE lease_name=? AND owner_id=? AND fencing_token=?""",
                (
                    _text(current),
                    _text(current),
                    lease.lease_name,
                    lease.owner_id,
                    lease.fencing_token,
                ),
            )
        return cursor.rowcount == 1

    def assert_current(
        self,
        lease: Lease,
        *,
        now: datetime | None = None,
    ) -> None:
        current = _text(_local_naive(now))
        row = self._db().execute(
            """SELECT 1 FROM operational_leases
               WHERE lease_name=? AND owner_id=? AND fencing_token=?
                 AND datetime(expires_at)>datetime(?)""",
            (
                lease.lease_name,
                lease.owner_id,
                lease.fencing_token,
                current,
            ),
        ).fetchone()
        if not row:
            raise LeaseLost("operational lease is no longer current")

    def begin_job(self, job_key: str, lease: Lease) -> bool:
        """Return False when the exact idempotency key already completed."""
        key = str(job_key or "").strip()
        if len(key) < 3:
            raise ValueError("job_key is required")
        db = self._db()
        current = _text(_local_naive())
        db.execute("BEGIN IMMEDIATE")
        try:
            owner = db.execute(
                """SELECT 1 FROM operational_leases
                   WHERE lease_name=? AND owner_id=? AND fencing_token=?
                     AND datetime(expires_at)>datetime(?)""",
                (
                    lease.lease_name,
                    lease.owner_id,
                    lease.fencing_token,
                    current,
                ),
            ).fetchone()
            if not owner:
                raise LeaseLost("cannot begin job without the current lease")
            existing = db.execute(
                "SELECT status FROM operational_job_runs WHERE job_key=?",
                (key,),
            ).fetchone()
            if existing and existing["status"] == "COMPLETED":
                db.rollback()
                return False
            if existing:
                db.execute(
                    """UPDATE operational_job_runs
                       SET lease_name=?, owner_id=?, fencing_token=?,
                           status='RUNNING', started_at=?, completed_at=NULL,
                           error_code=NULL WHERE job_key=?""",
                    (
                        lease.lease_name,
                        lease.owner_id,
                        lease.fencing_token,
                        current,
                        key,
                    ),
                )
            else:
                db.execute(
                    """INSERT INTO operational_job_runs
                       (job_key, lease_name, owner_id, fencing_token,
                        status, started_at)
                       VALUES (?, ?, ?, ?, 'RUNNING', ?)""",
                    (
                        key,
                        lease.lease_name,
                        lease.owner_id,
                        lease.fencing_token,
                        current,
                    ),
                )
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise

    def finish_job(
        self,
        job_key: str,
        lease: Lease,
        *,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        db = self._db()
        status = "COMPLETED" if succeeded else "FAILED"
        current = _text(_local_naive())
        with db:
            cursor = db.execute(
                """UPDATE operational_job_runs
                   SET status=?, completed_at=?, error_code=?
                   WHERE job_key=? AND owner_id=? AND fencing_token=?
                     AND status='RUNNING'
                     AND EXISTS (
                         SELECT 1 FROM operational_leases lease
                         WHERE lease.lease_name=operational_job_runs.lease_name
                           AND lease.owner_id=?
                           AND lease.fencing_token=?
                           AND datetime(lease.expires_at)>datetime(?)
                     )""",
                (
                    status,
                    current,
                    None if succeeded else str(error_code or "job_failed")[:120],
                    str(job_key),
                    lease.owner_id,
                    lease.fencing_token,
                    lease.owner_id,
                    lease.fencing_token,
                    current,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLost("job fencing token is no longer current")
