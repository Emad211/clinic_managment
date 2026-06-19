"""Per-patient clinical analytics — rules-driven, per-disease, risk + med effect.

Indicators, thresholds, targets and risk weights are read from the editable
clinical_indicators table (see clinical_rules_repo / /manager/rules), so the
manager can tune the whole engine without code changes.
"""
from datetime import datetime, timedelta

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.vitals_repo import VitalsRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.wallet_repo import WalletRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository, CATEGORY_LABELS
from src.adapters import accounting_bridge
from src.services.vitals_service import VitalsService
from src.services.clinical_rules_service import evaluate as eval_rule
from src.common.utils import format_jalali_date

# Backward-compatible static targets (the patient detail page imports this).
TARGETS = {'hba1c': 7.0, 'fbs': 130, 'bp_systolic': 130, 'bp_diastolic': 80}

_CATEGORY_ORDER = ['glycemic', 'bp', 'lipid', 'kidney', 'anthro', 'other']


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], '%Y-%m-%d')
    except ValueError:
        return None


def _mean(xs):
    return round(sum(xs) / len(xs), 1) if xs else None


def _level_from(points: float, danger_count: int) -> tuple[str, str]:
    """Map weighted risk points + danger count to a (level, fa-label) pair.

    Single source of truth for the risk-tier thresholds, reused by both the
    aggregate _risk score and the per-disease builder.
    """
    if points >= 5 or danger_count >= 2:
        return 'high', 'پرخطر'
    if points >= 3 or danger_count == 1:
        return 'medium', 'متوسط'
    if points >= 1:
        return 'low', 'کم'
    return 'ok', 'پایدار'


class AnalyticsService:
    def __init__(self):
        self.vitals = VitalsRepository()
        self.patients = PatientRepository()
        self.vitals_service = VitalsService()
        self.rules = ClinicalRulesRepository()

    def patient_analytics(self, pid: int) -> dict:
        patient = self.patients.get_by_id(pid)
        if not patient:
            return {'patient': None}

        conditions = self.patients.get_patient_conditions(pid)
        condition_codes = [c.get('condition_code') for c in conditions if c.get('condition_code')]
        # Per-disease dashboard: only indicators relevant to this patient's diseases
        indicators_meta = self.rules.for_conditions(condition_codes)

        indicators, charts = [], {}
        for ind in indicators_meta:
            key = ind['key']
            readings = self.vitals.get_readings(pid, vtype=key, limit=200)  # ascending
            latest = readings[-1] if readings else None
            previous = readings[-2] if len(readings) > 1 else None
            delta = (latest['value'] - previous['value']) if (latest and previous) else None
            level = eval_rule(ind, latest['value']) if latest else 'none'
            bar_pct = self._bar_pct(ind, latest['value']) if latest else None
            indicators.append({
                'key': key, 'label': ind['label'], 'unit': ind['unit'],
                'category': ind['category'],
                'category_label': CATEGORY_LABELS.get(ind['category'], ind['category']),
                'conditions': ind.get('conditions'),
                'direction': ind['direction'],
                'latest': latest['value'] if latest else None,
                'previous': previous['value'] if previous else None,
                'delta': round(delta, 1) if delta is not None else None,
                'level': level,
                'target': ind.get('target'), 'goal_low': ind.get('goal_low'),
                'goal_high': ind.get('goal_high'), 'risk_weight': ind.get('risk_weight', 0),
                'count': len(readings), 'bar_pct': bar_pct,
                'last_date': format_jalali_date(latest['measured_at']) if latest else None,
            })
            if readings:
                charts[key] = {
                    'label': ind['label'], 'unit': ind['unit'], 'category': ind['category'],
                    'labels': [format_jalali_date(r['measured_at']) for r in readings],
                    'dates': [str(r['measured_at'])[:10] for r in readings],
                    'values': [r['value'] for r in readings],
                    'target': ind.get('target'),
                }

        # Objective medication timeline (overlaid as chart markers)
        med_events = self.patients.get_medication_events(pid)
        events_payload = [{
            'drug_name': e['drug_name'], 'event_type': e['event_type'], 'dose': e['dose'],
            'date': str(e['event_date'])[:10] if e['event_date'] else None,
            'date_fa': format_jalali_date(e['event_date']),
        } for e in med_events]

        risk = self._risk(pid, indicators)
        per_disease = self._per_disease(conditions, indicators)
        control = self.vitals_service.control_status(pid)

        meds = self.patients.get_medications(pid, active_only=False)
        db = get_db()
        refill_due = db.execute(
            """SELECT COUNT(*) c FROM patient_medications
               WHERE patient_link_id=? AND is_active=1 AND refill_due_date IS NOT NULL
                 AND refill_due_date <= date('now','+3 hours','+30 minutes','+7 days')""",
            (pid,)).fetchone()['c']

        appts = AppointmentRepository().list_for_patient(pid)
        done = sum(1 for a in appts if a['status'] == 'done')
        no_show = sum(1 for a in appts if a['status'] == 'no_show')
        upcoming = [a for a in appts if a['status'] == 'scheduled']

        visits = []
        if patient.get('accounting_patient_id'):
            visits = accounting_bridge.get_visit_history(patient['accounting_patient_id'], limit=100)

        followups = [f for f in FollowupRepository().list_for_patient(pid) if f['status'] == 'open']

        return {
            'patient': patient,
            'indicators': indicators,
            'by_category': self._group_by_category(indicators),
            'charts': charts,
            'med_events': events_payload,
            'control': control,
            'conditions': conditions,
            'allergies': self.patients.get_allergies(pid),
            'medications': meds,
            'refill_due': refill_due,
            'appointments': {'done': done, 'no_show': no_show, 'upcoming': upcoming, 'total': len(appts)},
            'visits_count': len(visits),
            'last_visit': format_jalali_date(visits[0]['visit_date']) if visits else None,
            'risk': risk,
            'per_disease': per_disease,
            'followups': followups,
            'wallet_balance': WalletRepository().get_balance(pid),
        }

    # ---- progress-to-danger bar (0..100) for indicator tiles ----
    def _bar_pct(self, ind: dict, value) -> int | None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        ref = ind.get('danger') if ind.get('danger') is not None else ind.get('warn')
        if ref in (None, 0):
            return None
        direction = (ind.get('direction') or 'high').lower()
        pct = (ref / v * 100) if direction == 'low' else (v / ref * 100)
        return int(max(6, min(100, round(pct))))

    # ---- per-disease grouping ----
    def _group_by_category(self, indicators) -> list[dict]:
        groups = {}
        for i in indicators:
            g = groups.setdefault(i['category'], {
                'category': i['category'],
                'label': CATEGORY_LABELS.get(i['category'], i['category']),
                'indicators': [],
            })
            g['indicators'].append(i)
        return [groups[c] for c in _CATEGORY_ORDER if c in groups] + \
               [g for c, g in groups.items() if c not in _CATEGORY_ORDER]

    # ---- weighted risk score, connected to dominant factor ----
    def _risk(self, pid: int, indicators) -> dict:
        db = get_db()
        cat_points, total = {}, 0.0
        danger_count = warn_count = 0
        severe_kidney = False
        for i in indicators:
            w = i.get('risk_weight') or 0
            if i['level'] == 'danger':
                pts = w
                danger_count += 1
                if i['key'] in ('egfr', 'uacr'):
                    severe_kidney = True
            elif i['level'] == 'warn':
                pts = w * 0.5
                warn_count += 1
            else:
                pts = 0
            if pts:
                cat_points[i['category']] = cat_points.get(i['category'], 0) + pts
                total += pts

        # Behavioral / adherence factors (automation, no doctor input needed)
        behav, behav_notes = 0, []
        lapsed = db.execute(
            """SELECT NOT EXISTS(SELECT 1 FROM vital_readings v WHERE v.patient_link_id=?
                 AND v.measured_at >= datetime('now','+3 hours','+30 minutes','-120 days')) AS x""",
            (pid,)).fetchone()['x']
        if lapsed:
            behav += 2
            behav_notes.append('بیش از ۴ ماه بدون ثبت شاخص')
        refill_overdue = db.execute(
            """SELECT COUNT(*) c FROM patient_medications WHERE patient_link_id=? AND is_active=1
                 AND refill_due_date IS NOT NULL
                 AND refill_due_date < date('now','+3 hours','+30 minutes')""",
            (pid,)).fetchone()['c']
        if refill_overdue:
            behav += 1
            behav_notes.append(f'{refill_overdue} داروی نیازمند تمدید نسخه')
        no_show = db.execute(
            "SELECT COUNT(*) c FROM appointments WHERE patient_link_id=? AND status='no_show'",
            (pid,)).fetchone()['c']
        if no_show >= 2:
            behav += 1
            behav_notes.append('غیبت مکرر در نوبت‌ها')
        if behav:
            cat_points['adherence'] = behav
            total += behav

        # Treatment-safety flags (e.g. high hypoglycemia risk) elevate the headline
        # risk independently of vitals control, so an insulin patient with high hypo
        # risk is not shown as falsely reassuring "low".
        try:
            from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
            flags = ClinicalFlagsRepository().get_flags(pid)
        except Exception:
            flags = {}
        safety = 0
        if (flags.get('hypo_risk') or '') == 'high':
            safety += 2
            behav_notes.append('ریسک بالای هیپوگلیسمی')
        if flags.get('frailty') == 'complex':
            safety += 1
            behav_notes.append('سالمند فراژیل (احتیاط در تشدید درمان)')
        if safety:
            cat_points['safety'] = safety
            total += safety

        if severe_kidney:
            level, label = 'high', 'پرخطر'
        else:
            level, label = _level_from(total, danger_count)

        def cat_label(c):
            if c == 'adherence':
                return 'پایبندی درمان'
            if c == 'safety':
                return 'ایمنی درمان'
            return CATEGORY_LABELS.get(c, c)

        breakdown = [{'category': c, 'label': cat_label(c), 'points': round(p, 1)}
                     for c, p in sorted(cat_points.items(), key=lambda kv: -kv[1])]
        dominant = breakdown[0]['label'] if breakdown else None

        return {
            'level': level, 'label': label, 'points': round(total, 1),
            'danger_count': danger_count, 'warn_count': warn_count,
            'dominant': dominant, 'breakdown': breakdown, 'behavior_notes': behav_notes,
        }

    # ---- per-disease overview (status + risk + top indicators per condition) ----
    def _per_disease(self, conditions, indicators) -> list[dict]:
        """One entry per chronic condition: worst status + risk tier + the top
        (≤3) risk-weighted indicators that have data for that disease.

        Pure Python over already-fetched indicators — no SQL. An indicator
        applies to a condition when its `conditions` field is 'all' or its
        comma-split list contains the condition code.
        """
        _level_rank = {'danger': 3, 'warn': 2, 'ok': 1}
        out = []
        for c in conditions:
            code = c.get('condition_code')
            if not code:
                continue
            mine = []  # this disease's indicators that have data
            for i in indicators:
                if i.get('latest') is None:
                    continue
                applies = i.get('conditions') or ''
                codes = {p.strip() for p in applies.split(',') if p.strip()}
                if applies == 'all' or code in codes:
                    mine.append(i)

            # worst status among this disease's indicators-with-data
            status = 'none'
            if mine:
                worst = max(mine, key=lambda i: _level_rank.get(i.get('level'), 0))
                status = worst.get('level') if worst.get('level') in _level_rank else 'ok'

            # per-disease weighted points (mirror _risk: danger=w, warn=0.5w)
            points, danger_count = 0.0, 0
            for i in mine:
                w = i.get('risk_weight') or 0
                if i.get('level') == 'danger':
                    points += w
                    danger_count += 1
                elif i.get('level') == 'warn':
                    points += w * 0.5
            risk_level, risk_label = _level_from(points, danger_count)

            # top ≤3 risk-weighted indicators (risk_weight>0, with data), desc
            top = sorted(
                [i for i in mine if (i.get('risk_weight') or 0) > 0],
                key=lambda i: -(i.get('risk_weight') or 0),
            )[:3]

            out.append({
                'condition_code': code,
                'condition_name': c.get('condition_name') or code,
                'status': status,
                'risk_level': risk_level,
                'risk_label': risk_label,
                'indicators': top,
            })
        return out

    # ---- on-demand medication effect (doctor-driven) ----
    def medication_effect(self, pid: int, med_id: int, indicator_key: str,
                          window_days: int = 90) -> dict:
        med = self.patients.get_medication(med_id) if med_id else None
        if not med or not indicator_key:
            return {'ok': False, 'error': 'invalid'}
        start = _parse_date(med.get('start_date'))
        if not start:
            return {'ok': False, 'error': 'no_start_date'}
        window_days = max(7, min(int(window_days or 90), 730))
        pre_from = start - timedelta(days=window_days)
        post_to = start + timedelta(days=window_days)

        readings = self.vitals.get_readings(pid, vtype=indicator_key, limit=500)
        pre_vals, post_vals = [], []
        for r in readings:
            d = _parse_date(r['measured_at'])
            if not d:
                continue
            if pre_from <= d < start:
                pre_vals.append(r['value'])
            elif start <= d <= post_to:
                post_vals.append(r['value'])

        pre, post = _mean(pre_vals), _mean(post_vals)
        delta = round(post - pre, 1) if (pre is not None and post is not None) else None
        ind = self.rules.get(indicator_key) or {}
        improved = None
        if delta is not None:
            improved = (delta > 0) if (ind.get('direction') == 'low') else (delta < 0)
        return {
            'ok': True, 'drug_name': med['drug_name'],
            'indicator': ind.get('label', indicator_key), 'unit': ind.get('unit', ''),
            'pre': pre, 'post': post, 'delta': delta,
            'n_pre': len(pre_vals), 'n_post': len(post_vals),
            'improved': improved, 'window_days': window_days,
            'start_fa': format_jalali_date(med.get('start_date')),
        }
