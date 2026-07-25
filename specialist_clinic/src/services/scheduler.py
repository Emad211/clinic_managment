"""Leased background scheduler with durable job idempotency and verified backups.

Every scheduled mutation runs while one SQLite lease and fencing token are current.
Multiple desktop processes may start, but only the lease owner can begin or finish a
job key. Backup snapshots are accepted only after SQLite integrity verification and an
atomic SHA-256 manifest is written beside the database file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from src.adapters.sqlite.operational_lease_repo import (
    Lease,
    LeaseLost,
    OperationalLeaseRepository,
)
from src.common.utils import iran_now


logger = logging.getLogger(__name__)


class Scheduler:
    LEASE_NAME = "specialist-clinic:scheduler"
    LEASE_TTL_SECONDS = 1800

    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.thread = None
        self._last_followup_day = None
        self._last_backup_day = None
        self.owner_id = (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
        )

    def init_app(self, app):
        self.app = app
        self.db_path = Path(app.config["DATABASE_PATH"])
        self.backup_dir = Path(app.config["BACKUP_FOLDER"])
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.exception("[scheduler] could not create backup dir")

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("[scheduler] started owner=%s", self.owner_id)

    def stop(self):
        self.running = False
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=3)

    def _loop(self):
        time.sleep(20)
        while self.running:
            try:
                with self.app.app_context():
                    self._tick()
            except Exception:
                logger.exception("[scheduler] tick error")
            time.sleep(120)

    @staticmethod
    def _bucket(now, minutes: int = 2) -> str:
        return f"{now.strftime('%Y-%m-%dT%H')}:{now.minute // minutes:02d}"

    def _run_once(
        self,
        *,
        job_name: str,
        period_key: str,
        lease: Lease,
        callback,
    ) -> bool:
        """Run one durable idempotency key while the fencing token is current."""
        repo = OperationalLeaseRepository()
        job_key = f"{job_name}:{period_key}"
        try:
            should_run = repo.begin_job(job_key, lease)
        except LeaseLost:
            logger.warning("[scheduler] lease lost before job=%s", job_name)
            return False
        if not should_run:
            return True
        try:
            result = callback()
            if result is False:
                raise RuntimeError(f"{job_name}_reported_failure")
        except Exception as exc:
            logger.exception("[scheduler] job failed: %s", job_name)
            try:
                repo.finish_job(
                    job_key,
                    lease,
                    succeeded=False,
                    error_code=type(exc).__name__,
                )
            except LeaseLost:
                logger.warning(
                    "[scheduler] lease lost while recording failure job=%s",
                    job_name,
                )
            return False
        try:
            repo.finish_job(job_key, lease, succeeded=True)
        except LeaseLost:
            logger.warning(
                "[scheduler] stale worker could not finish job=%s", job_name
            )
            return False
        return True

    def _tick(self):
        now = iran_now()
        today = now.strftime("%Y-%m-%d")
        leases = OperationalLeaseRepository()
        lease = leases.acquire(
            self.LEASE_NAME,
            owner_id=self.owner_id,
            ttl_seconds=self.LEASE_TTL_SECONDS,
            now=now,
        )
        if lease is None:
            logger.debug("[scheduler] another process owns the lease")
            return
        try:
            if self._run_once(
                job_name="clinical-followups",
                period_key=today,
                lease=lease,
                callback=self._run_clinical_followups,
            ):
                self._last_followup_day = today

            period = self._bucket(now)
            self._run_once(
                job_name="administrative-engagement",
                period_key=period,
                lease=lease,
                callback=self._run_engagement,
            )
            self._run_once(
                job_name="invoice-sync",
                period_key=period,
                lease=lease,
                callback=self._sync_invoices,
            )
            self._run_once(
                job_name="due-campaigns",
                period_key=period,
                lease=lease,
                callback=self._run_due_campaigns,
            )
            self._run_once(
                job_name="sms-delivery-reconciliation",
                period_key=period,
                lease=lease,
                callback=self._reconcile_sms_delivery,
            )

            if now.weekday() == 5 and now.hour == 3:
                if self._run_once(
                    job_name="verified-backup",
                    period_key=today,
                    lease=lease,
                    callback=self._backup,
                ):
                    self._last_backup_day = today
        finally:
            leases.release(lease)

    def _run_clinical_followups(self) -> bool:
        from src.services.followup_engine import ClinicalV2FollowupService

        result = ClinicalV2FollowupService().generate_all()
        if result["created"]:
            logger.info(
                "[scheduler] clinical-v2 followups: %s task(s) created",
                result["created"],
            )
        if result["issues"]:
            logger.warning(
                "[scheduler] clinical-v2 followups: %s evaluation issue(s); "
                "no unsafe task was created for those cases",
                len(result["issues"]),
            )
        return True

    def _run_engagement(self):
        from src.services.engagement_service import EngagementService

        EngagementService().run_all()
        return True

    def _sync_invoices(self):
        from src.services.invoice_sync_service import InvoiceSyncService

        result = InvoiceSyncService().run()
        if result.get("new"):
            logger.info(
                "[scheduler] invoice-sync: %s new (%s pending link), cursor=%s",
                result["new"],
                result["pending_link"],
                result["cursor"],
            )
        return True

    def _run_due_campaigns(self):
        from src.adapters.sqlite.sms_repo import SmsRepository
        from src.services.sms.campaign_service import run_campaign

        for campaign in SmsRepository().due_campaigns():
            run_campaign(campaign["id"])
        return True

    def _reconcile_sms_delivery(self):
        from src.services.sms.delivery_service import DeliveryService

        DeliveryService().reconcile()
        return True

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _sqlite_integrity(path: Path) -> str:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            return str(row[0] if row else "missing")
        finally:
            connection.close()

    def _backup(self):
        """Create, verify and attest one atomic SQLite online-backup snapshot."""
        tmp = None
        manifest_tmp = None
        if not self.db_path.exists():
            return True
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            now = iran_now()
            ts = now.strftime("%Y%m%d_%H%M%S_%f")
            destination = self.backup_dir / f"backup_auto_{ts}.db"
            tmp = destination.with_suffix(".db.tmp")
            source = sqlite3.connect(str(self.db_path), timeout=30)
            try:
                output = sqlite3.connect(str(tmp), timeout=30)
                try:
                    source.backup(output, pages=-1)
                    output.commit()
                finally:
                    output.close()
            finally:
                source.close()

            integrity = self._sqlite_integrity(tmp)
            if integrity.lower() != "ok":
                raise RuntimeError(f"backup_integrity_failed:{integrity[:80]}")
            digest = self._file_sha256(tmp)
            size = tmp.stat().st_size
            os.replace(tmp, destination)
            tmp = None

            manifest = {
                "schema_version": "1.0",
                "backup_file": destination.name,
                "sha256": digest,
                "size_bytes": size,
                "integrity_check": "ok",
                "created_at": now.isoformat(sep=" ", timespec="seconds"),
            }
            manifest_path = destination.with_suffix(".manifest.json")
            manifest_tmp = manifest_path.with_suffix(".json.tmp")
            manifest_tmp.write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            os.replace(manifest_tmp, manifest_path)
            manifest_tmp = None

            backups = sorted(
                self.backup_dir.glob("backup_auto_*.db"),
                key=lambda file: file.stat().st_mtime,
                reverse=True,
            )
            for old in backups[4:]:
                try:
                    old.unlink()
                    old.with_suffix(".manifest.json").unlink(missing_ok=True)
                except Exception:
                    logger.warning(
                        "[scheduler] could not rotate old backup %s", old.name
                    )
            logger.info(
                "[scheduler] verified backup created file=%s bytes=%s sha256=%s",
                destination.name,
                size,
                digest[:12],
            )
            return True
        except Exception:
            logger.exception("[scheduler] backup error")
            for candidate in (tmp, manifest_tmp):
                if candidate is not None:
                    try:
                        candidate.unlink(missing_ok=True)
                    except Exception:
                        pass
            return False


scheduler = Scheduler()


def init_scheduler(app):
    scheduler.init_app(app)
    scheduler.start()
    return scheduler
