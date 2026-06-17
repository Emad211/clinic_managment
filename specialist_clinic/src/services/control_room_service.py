"""Patient Control Room: a prioritized, cohort-segmented view of who needs
attention now — fusing clinical control, disengagement, overdue care and (for
managers) revenue value into one explainable, clinical-first priority score, with
one-click recall per cohort.

Performance: a handful of set-based queries over the whole panel (NOT the heavy
per-patient rule engine), plus one batched revenue call to the accounting bridge.
Thresholds come from the editable clinical_indicators table, so the Control Room
stays consistent with the rest of the engine.
"""
from datetime import datetime

from src.adapters.sqlite.core import get_db
from src.adapters import accounting_bridge
from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
from src.services.clinical_rules_service import evaluate as eval_indicator
from src.common.utils import iran_now, format_jalali_date

LAPSED_DAYS = 120

# Vitals assessed for control; their editable danger/warn thresholds decide level.
CONTROL_VITALS = ['hba1c', 'fbs', 'bp_systolic', 'bp_diastolic', 'ldl', 'egfr', 'uacr']

COHORT_DEFS = [
    ('uncontrolled_lapsed', '🔴 کنترل‌نشده و بی‌مراجعه'),
    ('valuable_drifting', '💰 ارزشمندِ در حالِ ریزش'),
    ('overdue_care', '📋 مراقبتِ سررسیده'),
    ('uncontrolled', '⚕️ کنترل‌نشده (همه)'),
]


class ControlRoomService:
    def __init__(self):
        self.rules = ClinicalRulesRepository()

    def panel(self, show_value: bool = True) -> dict:
        db = get_db()
        now = iran_now()
        ind = {k: (self.rules.get(k) or {}) for k in CONTROL_VITALS}

        # one pass: latest of each control vital + recency, per active patient
        sel = ",\n                ".join(
            f"(SELECT v.value FROM vital_readings v WHERE v.patient_link_id=p.id AND v.type='{k}' "
            f"ORDER BY v.measured_at DESC LIMIT 1) AS {k}" for k in CONTROL_VITALS)
        rows = db.execute(f"""
            SELECT p.id, p.full_name, p.phone_number, p.accounting_patient_id, p.enrolled_at,
                   COALESCE(p.sms_opt_out, 0) AS opt_out,
                   {sel},
                   (SELECT MAX(v.measured_at) FROM vital_readings v WHERE v.patient_link_id=p.id) AS last_vital
            FROM patient_links p WHERE p.is_active=1
        """).fetchall()

        conds = {}
        for r in db.execute("""SELECT pc.patient_link_id pid, c.code, c.name
                               FROM patient_conditions pc JOIN conditions c ON c.id=pc.condition_id
                               WHERE pc.is_active=1"""):
            conds.setdefault(r['pid'], []).append(r['name'])

        fu = {r['pid']: r['c'] for r in db.execute(
            """SELECT patient_link_id pid, COUNT(*) c FROM followup_tasks
               WHERE status='open' GROUP BY patient_link_id""")}

        upcoming = {r['pid'] for r in db.execute(
            """SELECT DISTINCT patient_link_id pid FROM appointments
               WHERE status='scheduled'
                 AND scheduled_at >= datetime('now','+3 hours','+30 minutes')""")}

        # revenue per patient (value dimension) — one batched bridge call
        rev = {}
        median_rev = 0
        if show_value and accounting_bridge.is_available():
            aid_pairs = [(int(r['accounting_patient_id']),
                          (str(r['enrolled_at'])[:10] if r['enrolled_at'] else None))
                         for r in rows if r['accounting_patient_id']]
            by_aid = accounting_bridge.revenue_by_patient(aid_pairs)
            for r in rows:
                aid = r['accounting_patient_id']
                if aid and int(aid) in by_aid:
                    rev[r['id']] = by_aid[int(aid)]
            vals = sorted(v for v in rev.values() if v > 0)
            median_rev = vals[len(vals) // 2] if vals else 0

        patients = []
        for r in rows:
            pid = r['id']
            flags, warns = [], []
            for k in CONTROL_VITALS:
                val = r[k]
                if val is None:
                    continue
                meta = ind.get(k) or {}
                lvl = eval_indicator(meta, val)
                if lvl == 'danger':
                    flags.append({'label': meta.get('label', k), 'value': val})
                elif lvl == 'warn':
                    warns.append({'label': meta.get('label', k), 'value': val})
            assessable = any(r[k] is not None for k in CONTROL_VITALS)
            control = ('uncontrolled' if flags else 'borderline' if warns
                       else 'controlled' if assessable else 'unknown')

            days = None
            if r['last_vital']:
                try:
                    days = (now - datetime.strptime(str(r['last_vital'])[:10], '%Y-%m-%d')).days
                except ValueError:
                    days = None
            lapsed = (days is None) or (days > LAPSED_DAYS)
            open_fu = fu.get(pid, 0)
            value = rev.get(pid, 0)

            # ---- priority score: clinical-first, value as seasoning ----
            bd, score = [], 0
            if flags:
                pts = 3 * len(flags); score += pts; bd.append(('کنترل‌نشده', pts))
            if warns:
                score += len(warns); bd.append(('مرزی', len(warns)))
            if assessable and lapsed:
                score += 2; bd.append(('بی‌مراجعه', 2))
            elif not assessable:
                score += 1; bd.append(('بدون قرائتِ پایه', 1))
            if open_fu:
                pts = min(open_fu, 3); score += pts; bd.append((f'{open_fu} پیگیریِ باز', pts))
            if show_value and median_rev > 0 and value > median_rev:
                score += 1; bd.append(('بیمارِ ارزشمند', 1))
            if pid in upcoming:
                score = max(0, score - 2); bd.append(('نوبتِ پیش‌رو', -2))

            if score <= 0:
                continue

            patients.append({
                'id': pid, 'name': r['full_name'], 'phone': r['phone_number'],
                'opt_out': bool(r['opt_out']), 'control': control,
                'flags': flags, 'warns': warns, 'lapsed': lapsed, 'days': days,
                'open_fu': open_fu, 'value': value, 'score': score,
                'breakdown': bd, 'conditions': conds.get(pid, []),
                'upcoming': pid in upcoming,
                'last_fa': format_jalali_date(r['last_vital']) if r['last_vital'] else '—',
            })

        patients.sort(key=lambda x: -x['score'])

        def in_cohort(p, key):
            if key == 'uncontrolled_lapsed':
                return p['control'] == 'uncontrolled' and p['lapsed']
            if key == 'valuable_drifting':
                return median_rev > 0 and p['value'] > median_rev and p['lapsed']
            if key == 'overdue_care':
                return p['open_fu'] > 0
            if key == 'uncontrolled':
                return p['control'] == 'uncontrolled'
            return False

        cohorts = []
        for key, label in COHORT_DEFS:
            if key == 'valuable_drifting' and not show_value:
                continue
            ids = [p['id'] for p in patients if in_cohort(p, key)]
            cohorts.append({'key': key, 'label': label, 'count': len(ids), 'ids': ids})

        return {'patients': patients, 'cohorts': cohorts, 'median_rev': median_rev,
                'total': len(patients), 'show_value': show_value}

    def cohort_ids(self, cohort_key: str, show_value: bool = True) -> list[int]:
        """Recompute a cohort's patient ids server-side (don't trust posted ids)."""
        data = self.panel(show_value=show_value)
        return next((c['ids'] for c in data['cohorts'] if c['key'] == cohort_key), [])
