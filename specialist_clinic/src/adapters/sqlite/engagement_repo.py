"""Repository for the engagement engine: the editable event->channel routing
table (`engagement_events`) and the idempotency/cooldown ledger
(`engagement_dispatch`)."""
from src.adapters.sqlite.core import get_db

# Manager-editable fields on an engagement event.
EDITABLE_FIELDS = ('label', 'category', 'channel', 'sms_template', 'lead_days',
                   'cooldown_days', 'priority', 'is_active')

CHANNELS = {'sms': 'پیامک', 'worklist': 'ورک‌لیست (تماس)', 'both': 'هردو', 'off': 'خاموش'}


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
