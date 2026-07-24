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
RETIRED_CLINICAL_EVENTS = frozenset({
    'uncontrolled', 'monitoring_due', 'screening_due', 'vaccine_due', 'red_flag',
})

class EngagementRepository:

    # ---- event config ----
    def active_events(self) -> list[dict]:
        db = get_db()
        placeholders = ",".join("?" for _ in RETIRED_CLINICAL_EVENTS)
        return [dict(row) for row in db.execute(
            f"SELECT * FROM engagement_events WHERE is_active=1 "
            f"AND event_key NOT IN ({placeholders}) ORDER BY priority, id",
            tuple(sorted(RETIRED_CLINICAL_EVENTS)),
        ).fetchall()]

    def all_events(self) -> list[dict]:
        """Return only manager-editable administrative routing."""
        db = get_db()
        placeholders = ",".join("?" for _ in RETIRED_CLINICAL_EVENTS)
        return [dict(row) for row in db.execute(
            f"SELECT * FROM engagement_events WHERE event_key NOT IN ({placeholders}) "
            f"ORDER BY priority, id",
            tuple(sorted(RETIRED_CLINICAL_EVENTS)),
        ).fetchall()]

    def get_event(self, event_key: str) -> dict | None:
        if event_key in RETIRED_CLINICAL_EVENTS:
            return None
        db = get_db()
        row = db.execute(
            "SELECT * FROM engagement_events WHERE event_key=?",
            (event_key,),
        ).fetchone()
        return dict(row) if row else None

    def update_event(self, event_id: int, fields: dict):
        db = get_db()
        existing = db.execute(
            "SELECT event_key FROM engagement_events WHERE id=?", (event_id,)
        ).fetchone()
        if existing and existing["event_key"] in RETIRED_CLINICAL_EVENTS:
            fields = {**fields, "is_active": 0, "channel": "off"}
        sets, params = [], []
        for f in EDITABLE_FIELDS:
            if f in fields:
                sets.append(f"{f}=?")
                params.append(fields[f])
        if not sets:
            return
        params.append(event_id)
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

    def record_dispatch(self, pid: int, event_key: str, period_key: str, channel: str,
                        ref_id=None, status='done'):
        db = get_db()
        db.execute(
            """INSERT OR IGNORE INTO engagement_dispatch
               (patient_link_id, event_key, period_key, channel, ref_id, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pid, event_key, period_key, channel, ref_id, status))
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
            """SELECT a.*, p.full_name AS patient_name, p.phone_number, p.national_id,
                      COALESCE(e.label, a.event_key) AS event_label, e.category AS event_category
               FROM engagement_approvals a
               JOIN patient_links p ON p.id=a.patient_link_id
               LEFT JOIN engagement_events e ON e.event_key=a.event_key
               WHERE a.status='pending'
               ORDER BY a.due_date IS NULL, a.due_date ASC, a.id DESC""").fetchall()]

    def claim_approval(self, approval_id: int) -> bool:
        """Atomically claim a pending approval so double-clicks cannot double-send."""
        db = get_db()
        cur = db.execute(
            """UPDATE engagement_approvals
               SET status='submitting', send_attempts=send_attempts+1, last_error=NULL
               WHERE id=? AND status='pending'""", (approval_id,))
        db.commit()
        return cur.rowcount == 1

    def finish_approval(self, approval_id: int, status: str, *, decided_by=None,
                        sms_message_id=None, error=None, sent=False):
        now = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        db = get_db()
        db.execute(
            """UPDATE engagement_approvals SET status=?, decided_by=?, decided_at=?,
                   sms_message_id=COALESCE(?, sms_message_id), last_error=?,
                   sent_at=CASE WHEN ? THEN ? ELSE sent_at END
               WHERE id=?""",
            (status, decided_by, now if status != 'pending' else None,
             sms_message_id, error, int(bool(sent)), now, approval_id))
        db.commit()

    def operational_summary(self) -> dict:
        db = get_db()
        approval = db.execute("""SELECT
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending,
            SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) approved,
            SUM(CASE WHEN status IN ('failed','unknown') THEN 1 ELSE 0 END) failed
            FROM engagement_approvals""").fetchone()
        worklist = db.execute("""SELECT
            SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) open,
            SUM(CASE WHEN status='open' AND due_date <= date('now','+3 hours','+30 minutes')
                     THEN 1 ELSE 0 END) due
            FROM followup_tasks""").fetchone()
        delivery = db.execute("""SELECT
            SUM(CASE WHEN source_type='engagement' THEN 1 ELSE 0 END) total,
            SUM(CASE WHEN source_type='engagement' AND delivery_status='Delivered' THEN 1 ELSE 0 END) delivered,
            SUM(CASE WHEN source_type='engagement' AND delivery_status IN
                ('PendingApproval','WaitingForSend','Sending','SendToOperator','Sent') THEN 1 ELSE 0 END) in_flight
            FROM sms_messages""").fetchone()
        return {
            'pending_approvals': approval['pending'] or 0,
            'approved': approval['approved'] or 0,
            'approval_errors': approval['failed'] or 0,
            'open_worklist': worklist['open'] or 0,
            'due_worklist': worklist['due'] or 0,
            'engagement_messages': delivery['total'] or 0,
            'delivered': delivery['delivered'] or 0,
            'in_flight': delivery['in_flight'] or 0,
        }

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
