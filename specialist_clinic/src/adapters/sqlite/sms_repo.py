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

    def provider_configured(self) -> bool:
        """True if any SMS panel (Kavenegar or Mediana) has an API key set."""
        return bool((self.get_setting('kavenegar_api_key') or '').strip()
                    or (self.get_setting('mediana_api_key') or '').strip())

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
        for k in ("total_recipients", "sent_count", "failed_count", "delivered_count",
                  "pending_count", "blacklist_count"):
            if k in counts:
                fields.append(f"{k}=?")
                params.append(counts[k])
        params.append(cid)
        db.execute(f"UPDATE sms_campaigns SET {', '.join(fields)} WHERE id=?", params)
        db.commit()

    def claim_campaign(self, cid: int, token: str) -> bool:
        db = get_db()
        cur = db.execute(
            """UPDATE sms_campaigns SET claim_token=?, claim_at=datetime('now','+3 hours','+30 minutes'),
                      status='sending'
               WHERE id=? AND status NOT IN ('cancelled') AND
                     (claim_token IS NULL OR claim_at < datetime('now','+3 hours','+10 minutes','-20 minutes'))""",
            (token, cid),
        )
        db.commit()
        return cur.rowcount == 1

    def release_campaign(self, cid: int, token: str, status: str = 'done'):
        db = get_db()
        db.execute("UPDATE sms_campaigns SET claim_token=NULL, claim_at=NULL, status=? "
                   "WHERE id=? AND claim_token=?", (status, cid, token))
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
    def add_message(self, *, campaign_id, patient_link_id, recipient, body, status='pending',
                    provider=None, idempotency_key=None, delivery_status='Queued',
                    retryable=True, source_type=None, source_ref=None) -> int:
        db = get_db()
        cur = db.execute(
            """INSERT OR IGNORE INTO sms_messages
               (campaign_id, patient_link_id, recipient, body, status, provider,
                idempotency_key, delivery_status, retryable, source_type, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (campaign_id, patient_link_id, recipient, body, status, provider,
             idempotency_key, delivery_status, int(bool(retryable)), source_type, source_ref),
        )
        db.commit()
        if cur.rowcount:
            return cur.lastrowid
        row = db.execute("SELECT id FROM sms_messages WHERE idempotency_key=?",
                         (idempotency_key,)).fetchone()
        return int(row['id'])

    def get_message(self, msg_id: int) -> dict | None:
        row = get_db().execute("SELECT * FROM sms_messages WHERE id=?", (msg_id,)).fetchone()
        return dict(row) if row else None

    def get_message_by_idempotency(self, key: str) -> dict | None:
        row = get_db().execute(
            "SELECT * FROM sms_messages WHERE idempotency_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def claim_message_attempt(self, msg_id: int) -> bool:
        db = get_db()
        cur = db.execute(
            """UPDATE sms_messages
               SET delivery_status='Submitting', retryable=0, send_attempts=send_attempts+1,
                   last_attempt_at=datetime('now','+3 hours','+30 minutes')
               WHERE id=? AND delivery_status IN ('Queued','RetryableFailure')
                 AND provider_request_id IS NULL AND provider_msgid IS NULL""", (msg_id,))
        db.commit()
        return cur.rowcount == 1

    def mark_submission(self, msg_id: int, *, ok: bool, pending: bool = False,
                        provider_request_id=None, provider_msgid=None, delivery_status=None,
                        delivery_status_int=None, error=None, retryable=False):
        now = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        if ok:
            local_status, dstatus, next_check = 'sent', delivery_status or 'PendingApproval', now
        elif pending:
            local_status, dstatus, next_check = 'pending', 'SubmissionUnknown', None
        elif retryable:
            local_status, dstatus, next_check = 'failed', 'RetryableFailure', None
        else:
            local_status, dstatus, next_check = 'failed', delivery_status or 'Failed', None
        db = get_db()
        db.execute(
            """UPDATE sms_messages SET status=?, provider_request_id=?, provider_msgid=?,
                   delivery_status=?, delivery_status_int=?, error=?, retryable=?,
                   sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END,
                   next_status_check_at=? WHERE id=?""",
            (local_status, provider_request_id, provider_msgid, dstatus, delivery_status_int,
             error, int(bool(retryable)), local_status, now, next_check, msg_id),
        )
        db.commit()

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

    def list_messages_filtered(self, *, campaign_id=None, delivery_status=None, provider=None,
                               source_type=None,
                               limit=500) -> list[dict]:
        clauses, params = [], []
        if campaign_id:
            clauses.append("m.campaign_id=?"); params.append(campaign_id)
        if delivery_status:
            clauses.append("m.delivery_status=?"); params.append(delivery_status)
        if provider:
            clauses.append("m.provider=?"); params.append(provider)
        if source_type:
            clauses.append("m.source_type=?"); params.append(source_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = get_db().execute(
            "SELECT m.*, c.name campaign_name, p.full_name patient_name FROM sms_messages m "
            "LEFT JOIN sms_campaigns c ON c.id=m.campaign_id "
            "LEFT JOIN patient_links p ON p.id=m.patient_link_id" + where +
            " ORDER BY m.id DESC LIMIT ?", params).fetchall()
        return [dict(r) for r in rows]

    def due_delivery_messages(self, limit=100, message_ids=None, campaign_id=None) -> list[dict]:
        clauses = ["provider='mediana'", "delivery_status NOT IN "
                   "('Delivered','NumberBlackListed','OperatorBlackList','Canceled','Failed',"
                   "'Undelivered','StatusUnknown','SubmissionUnknown')",
                   "(provider_request_id IS NOT NULL OR provider_msgid IS NOT NULL)"]
        params = []
        if message_ids:
            marks = ','.join('?' for _ in message_ids)
            clauses.append(f"id IN ({marks})"); params.extend(message_ids)
        elif campaign_id:
            clauses.append("campaign_id=?"); params.append(campaign_id)
        else:
            clauses.append("(next_status_check_at IS NULL OR next_status_check_at <= datetime('now','+3 hours','+30 minutes'))")
        params.append(limit)
        return [dict(r) for r in get_db().execute(
            f"SELECT * FROM sms_messages WHERE {' AND '.join(clauses)} ORDER BY id LIMIT ?", params
        ).fetchall()]

    def apply_delivery(self, msg_id: int, status: str, status_int=None, delivered_at=None,
                       provider_msgid=None):
        terminal = status in {'Delivered', 'NumberBlackListed', 'OperatorBlackList',
                              'Canceled', 'Failed', 'Undelivered', 'StatusUnknown'}
        now = iran_now()
        row = self.get_message(msg_id) or {}
        created = row.get('sent_at') or row.get('created_at')
        age = 0
        if created:
            try: age = (now - __import__('datetime').datetime.fromisoformat(created)).total_seconds()
            except (ValueError, TypeError): pass
        if terminal:
            next_check = None
        elif age < 3600:
            next_check = (now + __import__('datetime').timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S')
        elif age < 86400:
            next_check = (now + __import__('datetime').timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
        else:
            next_check = (now + __import__('datetime').timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        delivered = delivered_at or (now.strftime('%Y-%m-%d %H:%M:%S') if status == 'Delivered' else None)
        db = get_db()
        db.execute("""UPDATE sms_messages SET delivery_status=?, delivery_status_int=?,
                   delivery_checked_at=?, next_status_check_at=?, delivered_at=COALESCE(?, delivered_at),
                   provider_msgid=COALESCE(?, provider_msgid), retryable=0 WHERE id=?""",
                   (status, status_int, now.strftime('%Y-%m-%d %H:%M:%S'), next_check,
                    delivered, provider_msgid, msg_id))
        db.commit()

    def expire_stale_delivery(self) -> list[int]:
        db = get_db()
        rows = db.execute("""SELECT id, campaign_id FROM sms_messages
            WHERE provider='mediana' AND sent_at < datetime('now','+3 hours','+30 minutes','-72 hours')
              AND delivery_status NOT IN ('Delivered','NumberBlackListed','OperatorBlackList','Canceled',
                                           'Failed','Undelivered','StatusUnknown','SubmissionUnknown')""").fetchall()
        if rows:
            db.executemany("UPDATE sms_messages SET delivery_status='StatusUnknown', "
                           "next_status_check_at=NULL WHERE id=?", [(r['id'],) for r in rows])
            db.commit()
        return [r['campaign_id'] for r in rows if r['campaign_id']]

    def refresh_campaign_counts(self, cid: int):
        db = get_db()
        row = db.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) sent,
            SUM(CASE WHEN delivery_status='Delivered' THEN 1 ELSE 0 END) delivered,
            SUM(CASE WHEN delivery_status IN ('PendingApproval','WaitingForSend','Sending','SendToOperator','Sent') THEN 1 ELSE 0 END) pending,
            SUM(CASE WHEN delivery_status IN ('NumberBlackListed','OperatorBlackList') THEN 1 ELSE 0 END) blacklist,
            SUM(CASE WHEN status='failed' AND delivery_status NOT IN ('NumberBlackListed','OperatorBlackList','RetryableFailure') THEN 1 ELSE 0 END) failed
            FROM sms_messages WHERE campaign_id=?""", (cid,)).fetchone()
        db.execute("""UPDATE sms_campaigns SET total_recipients=?, sent_count=?, delivered_count=?,
                   pending_count=?, blacklist_count=?, failed_count=? WHERE id=?""",
                   (row['total'] or 0, row['sent'] or 0, row['delivered'] or 0,
                    row['pending'] or 0, row['blacklist'] or 0, row['failed'] or 0, cid))
        db.commit()
