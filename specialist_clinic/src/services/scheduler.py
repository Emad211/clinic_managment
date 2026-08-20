"""Leased background scheduler with durable job idempotency and verified backups.

Every scheduled mutation runs while one SQLite lease and fencing token are current.
Multiple desktop processes may start, but only the lease owner can begin or finish a
job key. Backup snapshots are accepted only after SQLite integrity verification and an
atomic SHA-256 manifest is written beside the database file.
"""
from __future__ import annotations

import logging
import os
import socket
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
    LEASE_HEARTBEAT_SECONDS = 60

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
        heartbeat_stop = threading.Event()
        heartbeat_errors: list[Exception] = []

        def heartbeat():
            while not heartbeat_stop.wait(self.LEASE_HEARTBEAT_SECONDS):
                try:
                    with self.app.app_context():
                        OperationalLeaseRepository().renew(
                            lease,
                            ttl_seconds=self.LEASE_TTL_SECONDS,
                            now=iran_now(),
                        )
                except Exception as exc:
                    heartbeat_errors.append(exc)
                    logger.exception(
                        "[scheduler] lease heartbeat failed job=%s", job_name
                    )
                    return

        heartbeat_thread = threading.Thread(
            target=heartbeat,
            name=f"lease-heartbeat:{job_name}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result = callback()
            if heartbeat_errors:
                raise LeaseLost("lease heartbeat failed during job")
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
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)
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
            def run(**kwargs):
                nonlocal lease
                lease = leases.renew(
                    lease,
                    ttl_seconds=self.LEASE_TTL_SECONDS,
                    now=iran_now(),
                )
                return self._run_once(lease=lease, **kwargs)

            if run(
                job_name="clinical-followups",
                period_key=today,
                callback=self._run_clinical_followups,
            ):
                self._last_followup_day = today
            run(
                job_name="clinical-audit-checkpoint",
                period_key=today,
                callback=self._seal_clinical_audit,
            )

            period = self._bucket(now)
            run(
                job_name="clinical-alerts",
                period_key=period,
                callback=self._run_clinical_alerts,
            )
            run(
                job_name="administrative-engagement",
                period_key=period,
                callback=self._run_engagement,
            )
            run(
                job_name="invoice-sync",
                period_key=period,
                callback=self._sync_invoices,
            )
            run(
                job_name="specialist-financial-reconciliation",
                period_key=period,
                callback=self._reconcile_specialist_finance,
            )
            run(
                job_name="due-campaigns",
                period_key=period,
                callback=self._run_due_campaigns,
            )
            run(
                job_name="sms-delivery-reconciliation",
                period_key=period,
                callback=self._reconcile_sms_delivery,
            )

            if now.weekday() == 5 and now.hour == 3:
                if run(
                    job_name="verified-backup",
                    period_key=today,
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

    def _seal_clinical_audit(self):
        from src.services.clinical_audit_integrity import (
            ClinicalAuditIntegrityService,
        )

        checkpoint = ClinicalAuditIntegrityService().seal(
            created_by=f"scheduler:{self.owner_id}"
        )
        logger.info(
            "[scheduler] clinical audit checkpoint id=%s hash=%s",
            checkpoint["id"],
            checkpoint["checkpoint_hash"][:12],
        )
        return True

    def _run_clinical_alerts(self):
        from src.services.clinical_alert_service import ClinicalAlertService

        service = ClinicalAlertService()
        generated = service.generate_all()
        escalated = service.escalate_due(now=iran_now())
        if generated["created"] or escalated:
            logger.warning(
                "[scheduler] clinical alerts created=%s escalated=%s",
                generated["created"],
                len(escalated),
            )
        if generated["issues"]:
            logger.error(
                "[scheduler] clinical alerts had %s projection issue(s)",
                len(generated["issues"]),
            )
            return False
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
        if result.get("outreach_failed"):
            logger.error(
                "[scheduler] invoice outreach retry failures=%s",
                result["outreach_failed"],
            )
            return False
        return True

    def _reconcile_specialist_finance(self):
        from src.services.specialist_financial_reconciliation_service import (
            SpecialistFinancialReconciliationService,
        )

        result = SpecialistFinancialReconciliationService().reconcile_all()
        if result["changed"]:
            logger.info(
                "[scheduler] specialist finance snapshots changed=%s observed=%s",
                result["changed"],
                result["observed"],
            )
        if result["issues"]:
            logger.error(
                "[scheduler] specialist finance reconciliation issues=%s",
                len(result["issues"]),
            )
            return False
        return True

    def _run_due_campaigns(self):
        from src.adapters.sqlite.sms_repo import SmsRepository
        from src.services.sms.campaign_service import run_campaign

        failures = 0
        for campaign in SmsRepository().due_campaigns():
            result = run_campaign(campaign["id"])
            failures += int(bool(result.get("error")))
        if failures:
            logger.error("[scheduler] due campaigns failed=%s", failures)
            return False
        return True

    def _reconcile_sms_delivery(self):
        from src.services.sms.delivery_service import DeliveryService

        result = DeliveryService().reconcile()
        if result["errors"]:
            logger.error(
                "[scheduler] SMS delivery reconciliation errors=%s providers=%s",
                result["errors"],
                result.get("provider_errors") or {},
            )
            return False
        return True

    def _backup(self):
        """Create, verify and attest one atomic SQLite online-backup snapshot."""
        if not self.db_path.exists():
            logger.error(
                "[scheduler] backup source database is missing path=%s",
                self.db_path,
            )
            return False
        try:
            from src.services.backup_integrity import BackupIntegrityService

            verified = BackupIntegrityService().create(
                self.db_path,
                self.backup_dir,
                prefix="backup_auto",
                keep=4,
                deadline_seconds=600,
            )
            logger.info(
                "[scheduler] verified backup created file=%s bytes=%s sha256=%s",
                verified.database_path.name,
                verified.size_bytes,
                verified.sha256[:12],
            )
            return True
        except Exception:
            logger.exception("[scheduler] backup error")
            return False


scheduler = Scheduler()


def init_scheduler(app):
    scheduler.init_app(app)
    scheduler.start()
    return scheduler
