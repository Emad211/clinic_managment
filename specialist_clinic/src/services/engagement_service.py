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
from src.common.utils import iran_now, today_str

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
                events.append({'event_key': 'appointment_reminder',
                               'period_key': f"appt:{r['id']}", 'detail': 'یادآوری نوبت'})

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
        res = {'sms': 0, 'worklist': 0, 'skipped': 0}
        if not patient:
            return res
        events, cfg = self.collect_due_events(pid)
        opted_out = bool(patient['sms_opt_out'])
        has_phone = bool(patient['phone_number'])
        quiet = self._quiet_now()
        cap = self._daily_cap()
        sent_today = self.repo.sms_count_today(pid)

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
                res['worklist'] += 1

            # --- sms channel ---
            if not worklist_only and channel in ('sms', 'both'):
                if opted_out or not has_phone:
                    res['skipped'] += 1
                elif quiet:
                    res['skipped'] += 1  # deferred until inside the quiet window
                elif sent_today >= cap:
                    res['skipped'] += 1
                elif self.repo.already_dispatched(pid, ev['event_key'], pk, 'sms'):
                    pass  # already sent for this period
                elif self.repo.in_cooldown(pid, ev['event_key'], conf.get('cooldown_days') or 0):
                    res['skipped'] += 1
                else:
                    body = sanitize(personalize(conf.get('sms_template') or '', name=patient['full_name']))
                    if body.strip():
                        if not dry_run:
                            send_single(pid, patient['phone_number'], body, message_type='Informational')
                            self.repo.record_dispatch(pid, ev['event_key'], pk, 'sms', None)
                        sent_today += 1
                        res['sms'] += 1
        return res

    def run_all(self, dry_run: bool = False, worklist_only: bool = False) -> dict:
        db = get_db()
        rows = db.execute("SELECT id FROM patient_links WHERE is_active=1").fetchall()
        agg = {'sms': 0, 'worklist': 0, 'skipped': 0, 'patients': 0}
        for r in rows:
            res = self.dispatch_patient(r['id'], dry_run=dry_run, worklist_only=worklist_only)
            for k in ('sms', 'worklist', 'skipped'):
                agg[k] += res[k]
            agg['patients'] += 1
        return agg
