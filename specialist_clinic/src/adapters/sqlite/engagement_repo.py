"""Repository for the engagement engine: the editable event->channel routing
table (`engagement_events`), the idempotency/cooldown ledger
(`engagement_dispatch`), and the per-patient approval queue
(`engagement_approvals`) — SMS only goes out after the physician approves."""
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now

# Manager-editable fields on an engagement event.
EDITABLE_FIELDS = ('label', 'category', 'channel', 'sms_template', 'lead_days',
                   'cooldown_days', 'priority', 'is_active')

CHANNELS = {'sms': 'پیامک', 'worklist': 'ورک‌لیست (تماس)', 'both': 'هردو', 'off': 'خاموش'}

# Allowed event_type vocabulary for manager-created (custom) events.
CUSTOM_EVENT_TYPES = ('custom_date_reminder', 'worklist_only')


class EngagementRepository:

    # ---- event config ----
    def active_events(self) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM engagement_events WHERE is_active=1 ORDER BY priority, id").fetchall()]

    def all_events(self) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM engagement_events ORDER BY priority, id").fetchall()]

    def get_event(self, event_key: str) -> dict | None:
        db = get_db()
        r = db.execute("SELECT * FROM engagement_events WHERE event_key=?", (event_key,)).fetchone()
        return dict(r) if r else None

    def create_event(self, event_key: str, channel: str, *, label=None,
                     event_type='custom_date_reminder', category='clinical',
                     sms_template=None, lead_days=0, cooldown_days=30,
                     priority=100, is_active=1) -> int | None:
        """Insert a NEW (manager-created) engagement event. Tagged is_custom=1 with
        an event_type from the small custom vocabulary. Idempotent-friendly:
        INSERT OR IGNORE on the UNIQUE event_key, so re-creating a duplicate is a
        no-op (returns None when nothing was inserted)."""
        if event_type not in CUSTOM_EVENT_TYPES:
            event_type = 'custom_date_reminder'
        db = get_db()
        cur = db.execute(
            """INSERT OR IGNORE INTO engagement_events
                 (event_key, label, category, channel, sms_template, lead_days,
                  cooldown_days, priority, is_active, is_custom, event_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (event_key, label or event_key, category, channel, sms_template,
             lead_days, cooldown_days, priority, is_active, event_type),
        )
        db.commit()
        return cur.lastrowid if cur.rowcount else None

    def update_event(self, event_id: int, fields: dict):
        sets, params = [], []
        for f in EDITABLE_FIELDS:
            if f in fields:
                sets.append(f"{f}=?")
                params.append(fields[f])
        if not sets:
            return
        params.append(event_id)
        db = get_db()
        db.execute(f"UPDATE engagement_events SET {', '.join(sets)} WHERE id=?", params)
        db.commit()

    # ---- dispatch ledger (idempotency + cooldown + daily cap) ----
    def already_dispatched(self, pid: int, event_key: str, period_key: str, channel: str) -> bool:
        db = get_db()
        return bool(db.execute(
            """SELECT 1 FROM engagement_dispatch
               WHERE patient_link_id=? AND event_key=? AND period_key=? AND channel=? LIMIT 1""",
            (pid, event_key, period_key, channel)).fetchone())

    def in_cooldown(self, pid: int, event_key: str, cooldown_days: int, channel: str = 'sms') -> bool:
        """True if this event was dispatched to this channel within `cooldown_days`."""
        if not cooldown_days:
            return False
        db = get_db()
        return bool(db.execute(
            """SELECT 1 FROM engagement_dispatch
               WHERE patient_link_id=? AND event_key=? AND channel=?
                 AND created_at >= datetime('now','+3 hours','+30 minutes', ?) LIMIT 1""",
            (pid, event_key, channel, f"-{int(cooldown_days)} days")).fetchone())

    def sms_count_today(self, pid: int) -> int:
        db = get_db()
        return db.execute(
            """SELECT COUNT(*) c FROM engagement_dispatch
               WHERE patient_link_id=? AND channel='sms'
                 AND date(created_at)=date('now','+3 hours','+30 minutes')""",
            (pid,)).fetchone()['c']

    def record_dispatch(self, pid: int, event_key: str, period_key: str, channel: str, ref_id=None):
        db = get_db()
        db.execute(
            """INSERT OR IGNORE INTO engagement_dispatch
               (patient_link_id, event_key, period_key, channel, ref_id) VALUES (?, ?, ?, ?, ?)""",
            (pid, event_key, period_key, channel, ref_id))
        db.commit()

    def recent_dispatches(self, limit: int = 100) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            """SELECT d.*, p.full_name FROM engagement_dispatch d
               JOIN patient_links p ON p.id=d.patient_link_id
               ORDER BY d.id DESC LIMIT ?""", (limit,)).fetchall()]

    # ---- approval queue (physician confirms before SMS goes out) ----
    def enqueue_approval(self, patient_link_id: int, event_key: str, channel: str,
                         due_date, message: str, period_key: str, offer=None) -> int | None:
        """Queue a candidate message for the physician to approve. Idempotent via
        INSERT OR IGNORE on UNIQUE(patient_link_id, event_key, period_key) — re-queuing
        the same patient/event/period is a no-op (returns None)."""
        db = get_db()
        cur = db.execute(
            """INSERT OR IGNORE INTO engagement_approvals
                 (patient_link_id, event_key, channel, due_date, message, offer, period_key)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (patient_link_id, event_key, channel, due_date, message, offer, period_key),
        )
        db.commit()
        return cur.lastrowid if cur.rowcount else None

    def list_pending(self) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            """SELECT a.*, p.full_name AS patient_name, p.phone_number, p.national_id
               FROM engagement_approvals a JOIN patient_links p ON p.id=a.patient_link_id
               WHERE a.status='pending'
               ORDER BY a.due_date IS NULL, a.due_date ASC, a.id DESC""").fetchall()]

    def set_status(self, approval_id: int, status: str, decided_by=None):
        """Record an approve/reject decision and who made it."""
        db = get_db()
        db.execute(
            """UPDATE engagement_approvals
               SET status=?, decided_by=?, decided_at=? WHERE id=?""",
            (status, decided_by, iran_now().strftime('%Y-%m-%d %H:%M:%S'), approval_id),
        )
        db.commit()

    def mark_sent(self, approval_id: int):
        """Stamp the moment the approved message was actually dispatched."""
        db = get_db()
        db.execute(
            "UPDATE engagement_approvals SET sent_at=? WHERE id=?",
            (iran_now().strftime('%Y-%m-%d %H:%M:%S'), approval_id),
        )
        db.commit()

    def get_approval(self, approval_id: int) -> dict | None:
        db = get_db()
        r = db.execute("SELECT * FROM engagement_approvals WHERE id=?", (approval_id,)).fetchone()
        return dict(r) if r else None

    def count_pending(self) -> int:
        db = get_db()
        return db.execute(
            "SELECT COUNT(*) c FROM engagement_approvals WHERE status='pending'").fetchone()['c']
