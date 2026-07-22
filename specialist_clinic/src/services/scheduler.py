"""Background scheduler: engagement, clinical worklists, campaigns and backups.

All DB access happens inside an app context so get_db() works off-request.
Diagnostics go through rotating application logging.
"""
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from src.common.utils import iran_now

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.thread = None
        self._last_followup_day = None
        self._last_backup_day = None

    def init_app(self, app):
        self.app = app
        self.db_path = Path(app.config['DATABASE_PATH'])
        self.backup_dir = Path(app.config['BACKUP_FOLDER'])
        try:
            self.backup_dir.mkdir(exist_ok=True)
        except Exception:
            logger.exception("[scheduler] could not create backup dir")

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("[scheduler] started")

    def _loop(self):
        time.sleep(20)
        while self.running:
            try:
                with self.app.app_context():
                    self._tick()
            except Exception:
                logger.exception("[scheduler] tick error")
            time.sleep(120)

    def _tick(self):
        now = iran_now()
        today = now.strftime('%Y-%m-%d')

        # Clinical v2 due rules are distinct from administrative engagement
        # events.  Project them once per Tehran day from exact current runs.  A
        # failed pass is deliberately retried on the next tick.
        if self._last_followup_day != today:
            if self._run_clinical_followups():
                self._last_followup_day = today

        # Unified administrative engagement: reminders, lapsed/refill worklist
        # events and SMS approval queue. Safe to run every tick via its dispatch
        # ledger, cooldown and daily cap.
        self._run_engagement()

        # Read-only accounting invoice consumer.
        self._sync_invoices()

        # Scheduled campaigns and delivery reconciliation.
        self._run_due_campaigns()
        self._reconcile_sms_delivery()

        # Weekly consistent backup (Saturday ~03:00 Tehran).
        if now.weekday() == 5 and now.hour == 3 and self._last_backup_day != today:
            self._backup()
            self._last_backup_day = today

    def _run_clinical_followups(self) -> bool:
        try:
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
        except Exception:
            logger.exception("[scheduler] clinical-v2 followup projection error")
            return False

    def _run_engagement(self):
        """Run administrative due reminders/follow-ups -> SMS/worklist."""
        try:
            from src.services.engagement_service import EngagementService
            EngagementService().run_all()
        except Exception:
            logger.exception("[scheduler] engagement error")
            try:
                from src.adapters.sqlite.sms_repo import SmsRepository
                SmsRepository().set_setting(
                    'engagement_last_error',
                    'اجرای خودکار ناموفق بود؛ جزئیات در گزارش برنامه ثبت شده است.')
            except Exception:
                pass

    def _sync_invoices(self):
        """Read-only invoice-sync consumer; never advances cursor on failure."""
        try:
            from src.services.invoice_sync_service import InvoiceSyncService
            res = InvoiceSyncService().run()
            if res.get('new'):
                logger.info("[scheduler] invoice-sync: %s new (%s pending link), cursor=%s",
                            res['new'], res['pending_link'], res['cursor'])
        except Exception:
            logger.exception("[scheduler] invoice-sync error (cursor not advanced)")

    def _run_due_campaigns(self):
        try:
            from src.adapters.sqlite.sms_repo import SmsRepository
            from src.services.sms.campaign_service import run_campaign
            for c in SmsRepository().due_campaigns():
                run_campaign(c['id'])
        except Exception:
            logger.exception("[scheduler] campaign error")

    def _reconcile_sms_delivery(self):
        try:
            from src.services.sms.delivery_service import DeliveryService
            DeliveryService().reconcile()
        except Exception:
            logger.exception("[scheduler] SMS delivery reconciliation error")

    def _backup(self):
        """Create an atomic SQLite online-backup snapshot and retain the latest four."""
        tmp = None
        try:
            if not self.db_path.exists():
                return
            ts = iran_now().strftime('%Y%m%d_%H%M%S')
            dest = self.backup_dir / f"backup_auto_{ts}.db"
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            src = sqlite3.connect(str(self.db_path))
            try:
                out = sqlite3.connect(str(tmp))
                try:
                    src.backup(out, pages=-1)
                finally:
                    out.close()
            finally:
                src.close()
            os.replace(tmp, dest)
            tmp = None
            backups = sorted(self.backup_dir.glob('backup_auto_*.db'),
                             key=lambda f: f.stat().st_mtime, reverse=True)
            for old in backups[4:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception:
            logger.exception("[scheduler] backup error")
            if tmp is not None:
                try:
                    tmp.unlink()
                except Exception:
                    pass


scheduler = Scheduler()


def init_scheduler(app):
    scheduler.init_app(app)
    scheduler.start()
    return scheduler
