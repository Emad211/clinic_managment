"""Background scheduler: appointment reminders, scheduled campaigns,
follow-up generation, and weekly DB backup. Runs in a daemon thread.

All DB access happens inside an app context so get_db() works off-request.
Diagnostics go through `logging` (a rotating file in the frozen .exe, where stdout is
lost, plus the console in dev) — see src/common/logging_setup.py.
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
        # Small initial delay so the app finishes booting.
        time.sleep(20)
        while self.running:
            try:
                with self.app.app_context():
                    self._tick()
            except Exception:
                logger.exception("[scheduler] tick error")
            time.sleep(120)  # every 2 minutes

    def _tick(self):
        now = iran_now()
        today = now.strftime('%Y-%m-%d')

        # 1) Engagement engine: collect every due reminder + follow-up and dispatch
        #    it to SMS and/or the worklist per the editable engagement_events table.
        #    This REPLACES the old appointment-reminder and follow-up-generation
        #    passes. Safe to run every tick — the dispatch ledger + cooldown + daily
        #    cap make it idempotent, and SMS deferred during quiet hours is retried
        #    on a later tick once inside the allowed window.
        self._run_engagement()

        # 1b) Read-only invoice-sync: pull recently-closed accounting invoices into the
        #     local ledger (ADR-0003 D3+). Read-only — never writes the accounting DB.
        self._sync_invoices()

        # 2) Due scheduled campaigns (manual broadcasts)
        self._run_due_campaigns()

        # 3) Weekly backup (Saturday ~3 AM)
        if now.weekday() == 5 and now.hour == 3 and self._last_backup_day != today:
            self._backup()
            self._last_backup_day = today

    def _run_engagement(self):
        """Run the unified engagement engine: due reminders + follow-ups -> SMS/worklist."""
        try:
            from src.services.engagement_service import EngagementService
            EngagementService().run_all()
        except Exception:
            logger.exception("[scheduler] engagement error")

    def _sync_invoices(self):
        """Read-only invoice-sync consumer (ADR-0003 D3+): record recently-closed
        accounting invoices into the local ledger. Fail-loud — on error the cursor is
        NOT advanced (the exception is logged, the tick continues)."""
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

    def _backup(self):
        """Weekly snapshot of THIS app's DB (specialist.db; the accounting DB is never
        touched). Uses the SQLite Online Backup API for a consistent copy even while the
        app holds the DB open — `shutil.copy2` of a live DB could capture a torn write.
        pages=-1 copies the whole (small, single-clinic) DB in ONE step, which is atomic
        w.r.t. concurrent same-process writers (avoids the page-by-page restart loop).
        Writes to a temp file and os.replace()s it in, so a crash mid-copy never leaves a
        half-written file under a valid backup name."""
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
                    src.backup(out, pages=-1)   # whole-DB consistent snapshot
                finally:
                    out.close()
            finally:
                src.close()
            os.replace(tmp, dest)   # publish only after a clean, complete copy
            tmp = None
            # keep last 4
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
                    tmp.unlink()   # drop a half-written temp so it can't pass as a backup
                except Exception:
                    pass


scheduler = Scheduler()


def init_scheduler(app):
    scheduler.init_app(app)
    scheduler.start()
    return scheduler
