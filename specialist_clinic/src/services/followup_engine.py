"""Rule-driven follow-up generation: turns fired monitoring/screening/vaccine
rules into worklist tasks — but only when actually DUE (interval elapsed or
never done). Keeps the worklist practical, not spammy.
"""
from datetime import datetime

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.rule_engine import RuleEngine
from src.common.utils import today_str

REASON_BY_ACTION = {
    'create_followup': 'monitoring',
    'schedule_screening': 'screening',
    'vaccine': 'vaccine',
}

# Default recall interval (months) per item; None = one-time / on-demand.
ITEM_DEFAULT_MONTHS = {
    'a1c': 6, 'renal': 12, 'lipid': 12, 'eye': 12, 'foot': 12,
    'neuropathy': 12, 'masld': 12, 'renal_function': 12, 'potassium': None,
    'influenza': 12, 'tdap': 120, 'zoster': None, 'pneumococcal': None,
    'rsv': None, 'covid19': None, 'tsh': 12,
}
# Where the "last done" date comes from (vitals readings or a patient flag).
ITEM_VITALS = {'a1c': ['hba1c'], 'renal': ['egfr', 'uacr'], 'lipid': ['ldl'],
               'renal_function': ['egfr'], 'tsh': ['tsh']}
ITEM_FLAGS = {'eye': 'eye_exam_date', 'foot': 'foot_exam_date'}


def _last_done(pid: int, item: str, flags: dict):
    vts = ITEM_VITALS.get(item)
    if vts:
        ph = ','.join('?' * len(vts))
        row = get_db().execute(
            f"SELECT MAX(measured_at) m FROM vital_readings WHERE patient_link_id=? AND type IN ({ph})",
            (pid, *vts)).fetchone()
        return row['m'] if row else None
    fk = ITEM_FLAGS.get(item)
    return flags.get(fk) if fk else None


def _months_since(date_str):
    try:
        d = datetime.strptime(str(date_str)[:10], '%Y-%m-%d')
    except (ValueError, TypeError):
        return None
    now = datetime.now()
    return (now.year - d.year) * 12 + (now.month - d.month)


def due_clinical_events(pid: int) -> list[dict]:
    """Clinically-DUE monitoring/screening/vaccine/red-flag items for a patient,
    as plain data with NO side effects. Shared by the worklist generator and the
    engagement dispatcher (services/engagement_service.py).

    'Due' = the recall interval has elapsed or the item was never done. It does
    NOT dedupe against prior tasks/sends — each caller applies its own dedup (the
    worklist via recently_handled_source, the dispatcher via the engagement ledger).
    Each item: {action, rule_code, title, item, months}.
    """
    eng = RuleEngine()
    fired = eng.evaluate(pid)
    flags = eng.flags.get_flags(pid)
    out = []
    for r in fired:
        act = r.get('action_type')
        if act == 'redflag':
            out.append({'action': 'redflag', 'rule_code': r['rule_code'],
                        'title': r['title'], 'item': r['rule_code'], 'months': None})
            continue
        if act not in REASON_BY_ACTION:
            continue
        params = r.get('params') or {}
        item = params.get('item') or params.get('vaccine') or r['rule_code']
        months = params.get('interval_months')
        if months is None:
            months = ITEM_DEFAULT_MONTHS.get(item)
        if months == 0:  # "every visit" → handled by the panel, not the worklist
            continue
        last = _last_done(pid, item, flags)
        if last and months and (_months_since(last) or 0) < months:
            continue  # done recently → not due
        out.append({'action': act, 'rule_code': r['rule_code'], 'title': r['title'],
                    'item': item, 'months': months})
    return out


def generate_for_patient(pid: int) -> int:
    """Create due monitoring/screening/vaccine follow-ups for one patient (worklist)."""
    repo = FollowupRepository()
    created = 0
    for ev in due_clinical_events(pid):
        if ev['action'] == 'redflag':
            continue  # red-flags surface in the patient panel, not the worklist
        if repo.recently_handled_source(pid, ev['rule_code'], ev['months']):
            continue
        repo.create(pid, reason=REASON_BY_ACTION[ev['action']], detail=ev['title'],
                    due_date=today_str(), source_rule=ev['rule_code'])
        created += 1
    return created


def generate_all() -> int:
    """Run rule-driven follow-up generation across all active patients."""
    rows = get_db().execute("SELECT id FROM patient_links WHERE is_active=1").fetchall()
    return sum(generate_for_patient(r['id']) for r in rows)
