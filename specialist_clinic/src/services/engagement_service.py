"""Engagement engine (event -> channel) — the dispatcher that unifies automated
reminders, clinical follow-ups, and campaign-style outreach into one configurable
layer.

For each active patient it collects the events that are DUE now (from the clinical
rule engine and from time-based queries), then routes each event to SMS and/or the
staff worklist according to the manager-editable `engagement_events` table, while
honoring guardrails:
  - per-patient SMS opt-out (`patient_links.sms_opt_out`)
  - quiet hours (default 08:00-21:00 Tehran; SMS outside the window is deferred)
  - a daily SMS cap per patient (default 1)
  - per-event cooldown (no repeat SMS within `cooldown_days`)
  - idempotency: each (patient, event, period, channel) fires at most once
    (`engagement_dispatch` UNIQUE ledger)

This is the single place reminders/follow-ups are dispatched; the scheduler and the
follow-up worklist generator are wired through it (Phase 2 step 3).
"""
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.sms_repo import SmsRepository
from src.services.followup_engine import due_clinical_events
from src.services.sms.campaign_service import send_single, personalize
from src.services.sms.compliance import sanitize
from src.common.utils import iran_now, today_str, format_jalali_date

# Guardrail defaults (manager-overridable via the settings table).
QUIET_START_DEFAULT = '08:00'
QUIET_END_DEFAULT = '21:00'
DAILY_CAP_DEFAULT = 1

# Which worklist reason a worklist-routed event maps to (reuses existing labels).
REASON_BY_EVENT = {
    'monitoring_due': 'monitoring', 'screening_due': 'screening', 'vaccine_due': 'vaccine',
    'lapsed': 'lapsed', 'uncontrolled': 'uncontrolled', 'red_flag': 'uncontrolled',
    'appointment_reminder': 'visit_due', 'refill_due': 'refill',
}


class EngagementService:
    def __init__(self):
        self.repo = EngagementRepository()
        self.fu = FollowupRepository()
        self.sms = SmsRepository()

    # ------------------------------------------------------------------ guards
    def _quiet_now(self) -> bool:
        """True if the current Tehran time is OUTSIDE the allowed sending window."""
        start = self.sms.get_setting('engagement_quiet_start', QUIET_START_DEFAULT)
        end = self.sms.get_setting('engagement_quiet_end', QUIET_END_DEFAULT)
        now = iran_now().strftime('%H:%M')
        return not (start <= now <= end)

    def _daily_cap(self) -> int:
        try:
            return int(self.sms.get_setting('engagement_daily_cap', DAILY_CAP_DEFAULT))
        except (TypeError, ValueError):
            return DAILY_CAP_DEFAULT

    def _provider_ready(self) -> bool:
        if self.sms.provider_configured():
            return True
        try:
            from flask import current_app
            return bool(current_app.config.get('TESTING'))
        except Exception:
            return False

    # ------------------------------------------------------------- collection
    def collect_due_events(self, pid: int) -> tuple[list[dict], dict]:
        """Return (events, cfg) where events is a list of due events for the patient
        and cfg maps event_key -> its engagement_events config row."""
        db = get_db()
        cfg = {e['event_key']: e for e in self.repo.active_events()}
        action_to_event = {e['source_action']: k for k, e in cfg.items() if e.get('source_action')}
        events: list[dict] = []
        month = iran_now().strftime('%Y-%m')

        # 1) Clinical, rule-driven — grouped by event category so a patient gets ONE
        #    message per category (e.g. one "screenings due"), not one SMS per item.
        #    period_key is monthly so the reminder can recur next cycle (the per-event
        #    cooldown still prevents re-nagging within `cooldown_days`).
        clinical: dict[str, list[str]] = {}
        for ev in due_clinical_events(pid):
            ek = action_to_event.get(ev['action'])
            if ek and ek in cfg:
                clinical.setdefault(ek, []).append(ev['title'])
        for ek, titles in clinical.items():
            detail = '، '.join(titles[:6]) + ('…' if len(titles) > 6 else '')
            events.append({'event_key': ek, 'period_key': f"{ek}:{month}", 'detail': detail})

        # 2) Appointment reminders (scheduled appt within lead_days)
        if 'appointment_reminder' in cfg:
            lead = int(cfg['appointment_reminder'].get('lead_days') or 0)
            for r in db.execute(
                """SELECT id, scheduled_at FROM appointments
                   WHERE patient_link_id=? AND status='scheduled'
                     AND date(scheduled_at) BETWEEN date('now','+3 hours','+30 minutes')
                         AND date('now','+3 hours','+30 minutes', ?)""",
                (pid, f"+{lead} days")).fetchall():
                scheduled = r['scheduled_at'] or ''
                day = format_jalali_date(scheduled) if scheduled else ''
                clock = scheduled[11:16] if len(scheduled) >= 16 else ''
                events.append({'event_key': 'appointment_reminder',
                               'period_key': f"appt:{r['id']}",
                               'detail': f"نوبت {day} ساعت {clock}".strip(),
                               'due_date': scheduled[:10] or None})

        # 3) Refill due (active med with refill_due_date within lead_days)
        if 'refill_due' in cfg:
            lead = int(cfg['refill_due'].get('lead_days') or 0)
            for r in db.execute(
                """SELECT id, drug_name, refill_due_date FROM patient_medications
                   WHERE patient_link_id=? AND is_active=1 AND refill_due_date IS NOT NULL
                     AND refill_due_date <= date('now','+3 hours','+30 minutes', ?)""",
                (pid, f"+{lead} days")).fetchall():
                events.append({'event_key': 'refill_due',
                               'period_key': f"refill:{r['id']}:{r['refill_due_date']}",
                               'detail': f"داروی {r['drug_name']}"})

        # 4) Lapsed (no vital reading in 120 days) — once per month
        if 'lapsed' in cfg:
            row = db.execute(
                """SELECT NOT EXISTS(SELECT 1 FROM vital_readings v WHERE v.patient_link_id=?
                     AND v.measured_at >= datetime('now','+3 hours','+30 minutes','-120 days')) x""",
                (pid,)).fetchone()
            if row['x']:
                events.append({'event_key': 'lapsed', 'period_key': f"lapsed:{month}",
                               'detail': 'بیش از ۴ ماه بدون ثبت شاخص'})

        # 5) Uncontrolled (latest hba1c / systolic at or above the editable danger line)
        if 'uncontrolled' in cfg:
            from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
            cr = ClinicalRulesRepository()
            hba1c_d = (cr.get('hba1c') or {}).get('danger') or 8
            sys_d = (cr.get('bp_systolic') or {}).get('danger') or 140
            row = db.execute(
                """SELECT 1 FROM patient_links p WHERE p.id=? AND (
                     (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='hba1c'
                        ORDER BY v.measured_at DESC LIMIT 1) >= ?
                     OR (SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='bp_systolic'
                        ORDER BY v.measured_at DESC LIMIT 1) >= ?)""",
                (pid, hba1c_d, sys_d)).fetchone()
            if row:
                events.append({'event_key': 'uncontrolled', 'period_key': f"unctrl:{month}",
                               'detail': 'آخرین شاخص‌ها خارج از محدودهٔ کنترل'})

        return events, cfg

    # --------------------------------------------------------------- dispatch
    def dispatch_patient(self, pid: int, dry_run: bool = False, worklist_only: bool = False) -> dict:
        db = get_db()
        patient = db.execute(
            "SELECT id, full_name, phone_number, sms_opt_out FROM patient_links WHERE id=?",
            (pid,)).fetchone()
        res = {'sms': 0, 'worklist': 0, 'skipped': 0, 'queued': 0}
        if not patient:
            return res
        events, cfg = self.collect_due_events(pid)
        opted_out = bool(patient['sms_opt_out'])
        has_phone = bool(patient['phone_number'])

        for ev in events:
            conf = cfg[ev['event_key']]
            channel = conf['channel']
            if channel == 'off':
                continue
            pk = ev['period_key']

            # --- worklist channel ---
            if channel in ('worklist', 'both') and not self.repo.already_dispatched(pid, ev['event_key'], pk, 'worklist'):
                reason = REASON_BY_EVENT.get(ev['event_key'], 'manual')
                if not dry_run:
                    tid = None
                    if not self.fu.exists_open(pid, reason):
                        tid = self.fu.create(pid, reason=reason, detail=ev['detail'],
                                             due_date=today_str(), source_event=ev['event_key'])
                    self.repo.record_dispatch(pid, ev['event_key'], pk, 'worklist', tid)
                    if tid is not None:
                        res['worklist'] += 1
                else:
                    res['worklist'] += 1

            # --- sms channel --- (enqueue for physician approval; SMS is sent at approve time)
            if not worklist_only and channel in ('sms', 'both'):
                if opted_out or not has_phone:
                    res['skipped'] += 1
                elif self.repo.already_dispatched(pid, ev['event_key'], pk, 'sms'):
                    pass  # already sent for this period
                elif self.repo.in_cooldown(pid, ev['event_key'], conf.get('cooldown_days') or 0):
                    res['skipped'] += 1
                else:
                    template = conf.get('sms_template') or ''
                    body = personalize(template, name=patient['full_name'])
                    body = body.replace('{detail}', ev.get('detail') or '')
                    if ev['event_key'] == 'appointment_reminder' and ev.get('detail') \
                            and '{detail}' not in template:
                        body = f"{body.rstrip()} {ev['detail']}"
                    body = sanitize(body)
                    if body.strip():
                        if not dry_run:
                            aid = self.repo.enqueue_approval(
                                pid, ev['event_key'], 'sms', ev.get('due_date'), body, pk)
                            if aid is not None:
                                res['queued'] += 1
                        else:
                            res['queued'] += 1
        return res

    def run_all(self, dry_run: bool = False, worklist_only: bool = False) -> dict:
        db = get_db()
        rows = db.execute(
            "SELECT id FROM patient_links WHERE is_active=1 "
            "AND COALESCE(enrolled_by,'') != 'seed'").fetchall()
        agg = {'sms': 0, 'worklist': 0, 'skipped': 0, 'queued': 0, 'patients': 0}
        for r in rows:
            res = self.dispatch_patient(r['id'], dry_run=dry_run, worklist_only=worklist_only)
            for k in ('sms', 'worklist', 'skipped', 'queued'):
                agg[k] += res[k]
            agg['patients'] += 1
        if not dry_run:
            import json
            self.sms.set_setting('engagement_last_run_at',
                                 iran_now().strftime('%Y-%m-%d %H:%M:%S'))
            self.sms.set_setting('engagement_last_result', json.dumps(agg, ensure_ascii=False))
            self.sms.set_setting('engagement_last_error', '')
        return agg

    # ------------------------------------------------------- approval / invite
    def approve(self, approval_id: int, decided_by: str, message: str | None = None,
                override: bool = False) -> dict:
        """Physician confirms a queued message; only NOW does the SMS actually go out.
        Re-checks opt-out/phone at approve time (auto-rejects if the patient opted out).

        Honors quiet hours like the dispatch/preview paths: approving OUTSIDE the
        allowed window (default 08:00-21:00 Tehran; settings engagement_quiet_start/
        engagement_quiet_end) is blocked with reason 'quiet' and the approval is left
        pending, so it can be approved later. Physician authority is preserved via
        override=True, which bypasses the gate and sends anyway."""
        db = get_db()
        ap = self.repo.get_approval(approval_id)
        if not ap or ap.get('status') != 'pending':
            return {'ok': False, 'reason': 'not_pending'}
        # Quiet-hours guard — don't send patient SMS outside the allowed window unless
        # the physician explicitly overrides. Leave the approval pending (no status
        # change) so it stays in the queue to be approved later or force-sent now.
        if self._quiet_now() and not override:
            return {'ok': False, 'reason': 'quiet'}
        if self.repo.sms_count_today(ap['patient_link_id']) >= self._daily_cap():
            return {'ok': False, 'reason': 'daily_cap'}
        p = db.execute(
            "SELECT id, full_name, phone_number, sms_opt_out FROM patient_links WHERE id=?",
            (ap['patient_link_id'],)).fetchone()
        if not p or not p['phone_number'] or p['sms_opt_out']:
            self.repo.set_status(approval_id, 'rejected', decided_by)
            return {'ok': False, 'reason': 'opt_out'}
        body = sanitize(message.strip()) if (message and message.strip()) else (ap['message'] or '')
        if not body.strip():
            return {'ok': False, 'reason': 'empty'}
        if not self._provider_ready():
            return {'ok': False, 'reason': 'provider_unconfigured'}
        if not self.repo.claim_approval(approval_id):
            return {'ok': False, 'reason': 'not_pending'}

        key = f"engagement:approval:{approval_id}"
        try:
            accepted = send_single(
                ap['patient_link_id'], p['phone_number'], body,
                message_type='Informational', idempotency_key=key,
                source_type='engagement', source_ref=str(approval_id))
        except Exception as exc:
            self.repo.finish_approval(approval_id, 'pending', error=str(exc))
            return {'ok': False, 'reason': 'provider_error', 'error': str(exc)}

        msg = self.sms.get_message_by_idempotency(key) or {}
        msg_id = msg.get('id')
        if accepted:
            self.repo.record_dispatch(
                ap['patient_link_id'], ap['event_key'], ap['period_key'] or '',
                'sms', msg_id, status='accepted')
            self.repo.finish_approval(
                approval_id, 'approved', decided_by=decided_by,
                sms_message_id=msg_id, sent=True)
            return {'ok': True, 'message_id': msg_id}

        error = msg.get('error') or 'سرویس‌دهنده پیام را نپذیرفت'
        delivery = msg.get('delivery_status')
        if delivery == 'SubmissionUnknown':
            final_status, reason = 'unknown', 'submission_unknown'
        elif msg.get('retryable'):
            final_status, reason = 'pending', 'retryable_failure'
        else:
            final_status, reason = 'failed', 'provider_rejected'
        self.repo.finish_approval(
            approval_id, final_status, decided_by=decided_by,
            sms_message_id=msg_id, error=error)
        if final_status != 'pending':
            self.repo.record_dispatch(
                ap['patient_link_id'], ap['event_key'], ap['period_key'] or '',
                'sms', msg_id, status=final_status)
        return {'ok': False, 'reason': reason, 'error': error, 'message_id': msg_id}

    def reject(self, approval_id: int, decided_by: str) -> None:
        self.repo.set_status(approval_id, 'rejected', decided_by)

    def enqueue_event_for_patient(self, pid: int, event_key: str, period_key: str,
                                  detail: str | None = None) -> int | None:
        """Enqueue an invoice-triggered SMS (thank-you / procedure invite) into the
        physician approval queue (Phase 2). Enrolled patients only. Respects opt-out /
        no-phone / once-per-period / cooldown, and fills the {detail} placeholder.
        Returns the new approval id, or None if skipped/guardrailed."""
        db = get_db()
        p = db.execute(
            "SELECT id, full_name, phone_number, sms_opt_out FROM patient_links WHERE id=?",
            (pid,)).fetchone()
        if not p or p['sms_opt_out'] or not p['phone_number']:
            return None
        conf = self.repo.get_event(event_key)
        if not conf or not conf.get('is_active') or conf.get('channel') == 'off':
            return None
        if self.repo.already_dispatched(pid, event_key, period_key, 'sms'):
            return None
        if self.repo.in_cooldown(pid, event_key, conf.get('cooldown_days') or 0):
            return None
        body = personalize(conf.get('sms_template') or '', name=p['full_name'])
        if detail:
            body = body.replace('{detail}', detail)
        body = sanitize(body)
        if not body.strip():
            return None
        return self.repo.enqueue_approval(pid, event_key, 'sms', None, body, period_key)

    def enqueue_invite(self, pid: int, message: str | None = None) -> int | None:
        """Queue a visit-invite SMS for physician approval (one per patient per day).
        Returns the new approval id, or None if opted-out / no phone / already queued today."""
        db = get_db()
        p = db.execute(
            "SELECT id, full_name, phone_number, sms_opt_out FROM patient_links WHERE id=?",
            (pid,)).fetchone()
        if not p or p['sms_opt_out'] or not p['phone_number']:
            return None
        ev = self.repo.get_event('visit_invite') or {}
        tmpl = message or ev.get('sms_template') or (
            'سلام {name} عزیز، برای ادامهٔ روند درمان لطفاً جهت تعیینِ نوبتِ ویزیت با کلینیک تماس بگیرید.')
        body = sanitize(personalize(tmpl, name=p['full_name']))
        pk = f"invite:{today_str()}"
        return self.repo.enqueue_approval(pid, 'visit_invite', 'sms', today_str(), body, pk)

    def enqueue_control_room_invite(self, pid: int, message: str) -> int | None:
        """Queue one cohort message per patient/body/day for physician approval."""
        import hashlib
        db = get_db()
        p = db.execute(
            "SELECT id, full_name, phone_number, sms_opt_out FROM patient_links WHERE id=?",
            (pid,)).fetchone()
        if not p or p['sms_opt_out'] or not p['phone_number']:
            return None
        body = sanitize(personalize(message, name=p['full_name']))
        if not body.strip():
            return None
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()[:12]
        period_key = f"control-room:{today_str()}:{digest}"
        return self.repo.enqueue_approval(
            pid, 'control_room_invite', 'sms', today_str(), body, period_key)
