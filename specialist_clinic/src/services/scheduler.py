"""Background scheduler: appointment reminders, scheduled campaigns,
follow-up generation, and weekly DB backup. Runs in a daemon thread.

All DB access happens inside an app context so get_db() works off-request.
"""
import os
import shutil
import threading
import time
from pathlib import Path

from src.common.utils import iran_now


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
            pass

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[scheduler] started")

    def _loop(self):
        # Small initial delay so the app finishes booting.
        time.sleep(20)
        while self.running:
            try:
                with self.app.app_context():
                    self._tick()
            except Exception as e:
                print(f"[scheduler] tick error: {e}")
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
        except Exception as e:
            print(f"[scheduler] engagement error: {e}")

    def _run_due_campaigns(self):
        try:
            from src.adapters.sqlite.sms_repo import SmsRepository
            from src.services.sms.campaign_service import run_campaign
            for c in SmsRepository().due_campaigns():
                run_campaign(c['id'])
        except Exception as e:
            print(f"[scheduler] campaign error: {e}")

    def _backup(self):
        try:
            if not self.db_path.exists():
                return
            ts = iran_now().strftime('%Y%m%d_%H%M%S')
            shutil.copy2(self.db_path, self.backup_dir / f"backup_auto_{ts}.db")
            # keep last 4
            backups = sorted(self.backup_dir.glob('backup_auto_*.db'),
                             key=lambda f: f.stat().st_mtime, reverse=True)
            for old in backups[4:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception as e:
            print(f"[scheduler] backup error: {e}")


scheduler = Scheduler()


def init_scheduler(app):
    scheduler.init_app(app)
    scheduler.start()
    return scheduler
