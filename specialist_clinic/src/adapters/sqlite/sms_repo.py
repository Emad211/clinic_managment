"""Repository for SMS templates, campaigns, messages, and key/value settings."""
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class SmsRepository:

    # ---- settings (key/value) ----
    def get_setting(self, key: str, default=None):
        db = get_db()
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key: str, value: str):
        db = get_db()
        db.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, datetime('now','+3 hours','+30 minutes'))
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value),
        )
        db.commit()

    # ---- templates ----
    def list_templates(self) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute("SELECT * FROM sms_templates ORDER BY id").fetchall()]

    def get_template(self, tid: int) -> dict | None:
        db = get_db()
        row = db.execute("SELECT * FROM sms_templates WHERE id=?", (tid,)).fetchone()
        return dict(row) if row else None

    def add_template(self, name: str, body: str) -> int:
        db = get_db()
        cur = db.execute("INSERT INTO sms_templates (name, body) VALUES (?, ?)", (name, body))
        db.commit()
        return cur.lastrowid

    # ---- campaigns ----
    def create_campaign(self, *, name, body, segment, template_id=None, scheduled_at=None,
                        campaign_type='info', credit_amount=0, credit_expires_days=None,
                        holdout_percent=0, created_by=None) -> int:
        db = get_db()
        cur = db.execute(
            """INSERT INTO sms_campaigns
               (name, body, segment, template_id, scheduled_at, status,
                campaign_type, credit_amount, credit_expires_days, holdout_percent, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, body, segment, template_id, scheduled_at,
             'scheduled' if scheduled_at else 'draft',
             campaign_type, credit_amount or 0, credit_expires_days, holdout_percent or 0, created_by),
        )
        db.commit()
        return cur.lastrowid

    def get_campaign(self, cid: int) -> dict | None:
        db = get_db()
        row = db.execute("SELECT * FROM sms_campaigns WHERE id=?", (cid,)).fetchone()
        return dict(row) if row else None

    def list_campaigns(self) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute("SELECT * FROM sms_campaigns ORDER BY id DESC").fetchall()]

    def update_campaign_status(self, cid: int, status: str, **counts):
        db = get_db()
        fields = ["status=?"]
        params = [status]
        for k in ("total_recipients", "sent_count", "failed_count"):
            if k in counts:
                fields.append(f"{k}=?")
                params.append(counts[k])
        params.append(cid)
        db.execute(f"UPDATE sms_campaigns SET {', '.join(fields)} WHERE id=?", params)
        db.commit()

    def due_campaigns(self) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            """SELECT * FROM sms_campaigns
               WHERE status='scheduled' AND scheduled_at <= datetime('now','+3 hours','+30 minutes')
               ORDER BY scheduled_at ASC""").fetchall()]

    # ---- campaign audience (incrementality / holdout split) ----
    def record_audience(self, campaign_id: int, rows: list[tuple]):
        """rows = [(patient_link_id, accounting_patient_id, grp), ...]."""
        db = get_db()
        db.executemany(
            """INSERT INTO campaign_audience (campaign_id, patient_link_id, accounting_patient_id, grp)
               VALUES (?, ?, ?, ?)""",
            [(campaign_id, plid, aid, grp) for (plid, aid, grp) in rows])
        db.commit()

    def get_audience(self, campaign_id: int) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            """SELECT patient_link_id, accounting_patient_id, grp, assigned_at
               FROM campaign_audience WHERE campaign_id=?""", (campaign_id,)).fetchall()]

    # ---- messages (log) ----
    def add_message(self, *, campaign_id, patient_link_id, recipient, body, status='pending') -> int:
        db = get_db()
        cur = db.execute(
            """INSERT INTO sms_messages (campaign_id, patient_link_id, recipient, body, status)
               VALUES (?, ?, ?, ?, ?)""",
            (campaign_id, patient_link_id, recipient, body, status),
        )
        db.commit()
        return cur.lastrowid

    def mark_message(self, msg_id: int, status: str, provider_msgid=None, error=None):
        db = get_db()
        db.execute(
            "UPDATE sms_messages SET status=?, provider_msgid=?, error=?, sent_at=? WHERE id=?",
            (status, provider_msgid, error,
             iran_now().strftime('%Y-%m-%d %H:%M:%S') if status == 'sent' else None, msg_id),
        )
        db.commit()

    def list_messages(self, campaign_id: int = None, limit: int = 200) -> list[dict]:
        db = get_db()
        if campaign_id:
            rows = db.execute(
                "SELECT * FROM sms_messages WHERE campaign_id=? ORDER BY id DESC LIMIT ?",
                (campaign_id, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM sms_messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
