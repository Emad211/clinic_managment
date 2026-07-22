"""Rule engine: builds a patient fact-bundle and evaluates the editable
clinical_rules (trigger_json DSL). Powers risk/treatment/follow-up and every
other ADA rule category. Output is SUGGESTION-ONLY (physician confirms).
"""
import json
import logging
from datetime import datetime

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.vitals_repo import VitalsRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
from src.services.vitals_service import evaluate_reading


logger = logging.getLogger(__name__)

# action_type -> UI section
SECTION = {
    'redflag': 'redflags',
    'safety_alert': 'safety',
    'suggest_med': 'treatment',
    'flag_risk': 'risk',
    'set_target': 'assessment',
    'classify': 'assessment',
    'create_followup': 'monitoring',
    'schedule_screening': 'monitoring',
    'vaccine': 'vaccination',
    'educate': 'lifestyle',
}
SECTION_LABELS = {
    'redflags': '🚨 هشدارهای فوری',
    'risk': '⚠️ ریسک',
    'treatment': '💊 پیشنهادهای درمان',
    'safety': '🛑 ایمنی و منع دارو',
    'assessment': '🎯 ارزیابی و اهداف',
    'monitoring': '📅 پایش و غربالگری',
    'vaccination': '💉 واکسیناسیون',
    'lifestyle': '🍎 سبک زندگی و آموزش',
}
SECTION_ORDER = ['redflags', 'safety', 'risk', 'treatment', 'assessment',
                 'monitoring', 'vaccination', 'lifestyle']
_SEVERITY_RANK = {'urgent': 0, 'warn': 1, 'info': 2}


def _age_from_birthdate(bd, as_of_at: datetime | None = None) -> int | None:
    """Robust age: handles gregorian or Jalali year in birthdate string."""
    if not bd:
        return None
    digits = ''.join(ch for ch in str(bd) if ch.isdigit())
    if len(digits) < 4:
        return None
    year = int(digits[:4])
    now_g = (as_of_at or datetime.now()).year
    if year < 1500:           # Jalali year -> approximate gregorian
        year += 621
    age = now_g - year
    return age if 0 < age < 130 else None


def _truthy(v) -> bool:
    return v not in (None, '', '0', 'false', 'False', 'no', 'off')


class RuleEngine:
    def __init__(self, *, capture_shadow: bool = True):
        self.vitals = VitalsRepository()
        self.patients = PatientRepository()
        self.flags = ClinicalFlagsRepository()
        self.capture_shadow = capture_shadow

    # ---- fact bundle ----
    def build_facts(self, pid: int, *, as_of_at: datetime | None = None) -> dict:
        patient = self.patients.get_by_id(pid) or {}
        conditions = {c.get('condition_code') for c in self.patients.get_patient_conditions(pid)
                      if c.get('condition_code')}
        latest = (self.vitals.latest_by_type(pid)
                  if as_of_at is None
                  else self.vitals.latest_by_type(pid, as_of_at=as_of_at))
        indicator = {}
        for vt, reading in latest.items():
            indicator[vt] = {
                'latest': reading['value'],
                'level': evaluate_reading(vt, reading['value']),
            }
        med_classes = {m.get('drug_class') for m in self.patients.get_medications(pid, active_only=True)
                       if m.get('drug_class')}
        return {
            'age': _age_from_birthdate(patient.get('birthdate'), as_of_at),
            'conditions': conditions,
            'indicator': indicator,
            'flag': self.flags.get_flags(pid),
            'med_classes': med_classes,
        }

    # ---- trigger evaluation ----
    def _resolve(self, var: str, facts: dict):
        if var == 'age':
            return facts.get('age')
        if var == 'condition':
            return facts.get('conditions')
        if var == 'med.class':
            return facts.get('med_classes')
        if var == 'bmi':
            return facts['indicator'].get('bmi', {}).get('latest')
        if var.startswith('indicator.'):
            parts = var.split('.')
            key = parts[1]
            attr = parts[2] if len(parts) > 2 else 'latest'
            return facts['indicator'].get(key, {}).get(attr)
        if var.startswith('flag.'):
            return facts['flag'].get(var.split('.', 1)[1])
        return None

    def _leaf(self, node: dict, facts: dict) -> bool:
        cur = self._resolve(node['var'], facts)
        op = node['op']
        val = node.get('value')
        if op == 'has':
            return val in (cur or set())
        if op == 'not_has':
            return val not in (cur or set())
        if op == 'in':
            return cur in (val or [])
        if op == 'truthy':
            return _truthy(cur)
        if op == 'exists':
            return cur not in (None, '')
        if op in ('==', '!='):
            try:
                a, b = float(cur), float(val)
            except (TypeError, ValueError):
                a, b = (str(cur) if cur is not None else None), str(val)
            return (a == b) if op == '==' else (a != b)
        if cur is None or cur == '':
            return False
        if op == 'between':
            try:
                return float(val[0]) <= float(cur) <= float(val[1])
            except (TypeError, ValueError, IndexError):
                return False
        try:
            a, b = float(cur), float(val)
        except (TypeError, ValueError):
            return False
        return {'>=': a >= b, '<=': a <= b, '>': a > b, '<': a < b}.get(op, False)

    def _eval(self, node, facts: dict) -> bool:
        if node is None:
            return True
        if 'all' in node:
            return all(self._eval(c, facts) for c in node['all'])
        if 'any' in node:
            return any(self._eval(c, facts) for c in node['any'])
        if 'not' in node:
            return not self._eval(node['not'], facts)
        if 'var' in node:
            return self._leaf(node, facts)
        return False

    # ---- public API ----
    def evaluate(self, pid: int, *, as_of_at: datetime | None = None) -> list[dict]:
        """Return the list of fired rules for a patient (suggestion-only)."""
        facts = (self.build_facts(pid)
                 if as_of_at is None
                 else self.build_facts(pid, as_of_at=as_of_at))
        db = get_db()
        rows = db.execute(
            "SELECT * FROM clinical_rules WHERE is_active=1 ORDER BY priority, id"
        ).fetchall()
        fired = []
        for row in rows:
            r = dict(row)
            try:
                trig = json.loads(r['trigger_json']) if r.get('trigger_json') else None
            except (ValueError, TypeError):
                trig = None
            # rules with no trigger are reference-only; skip them from the
            # active patient panel (they belong to the manager catalog).
            if trig is None:
                continue
            try:
                if self._eval(trig, facts):
                    try:
                        r['params'] = json.loads(r['action_params_json']) if r.get('action_params_json') else {}
                    except (ValueError, TypeError):
                        r['params'] = {}
                    r['section'] = SECTION.get(r['action_type'], 'lifestyle')
                    fired.append(r)
            except Exception:
                continue
        fired.sort(key=lambda x: (_SEVERITY_RANK.get(x.get('severity'), 3), x.get('priority', 100)))
        # PR-04 dual-run seam: shadow mode records canonical facts only.  It
        # deliberately cannot affect the legacy suggestions returned to callers.
        try:
            if not self.capture_shadow:
                return fired
            from src.common.utils import iran_now
            from src.services.clinical_engine.fact_builder import ShadowFactCapture

            ShadowFactCapture().capture(
                pid, as_of_at=as_of_at or iran_now(), created_by="legacy-facade"
            )
        except Exception:
            logger.exception("Clinical Engine v2 shadow fact capture failed for patient %s", pid)
        return fired

    def grouped(self, pid: int) -> dict:
        """Fired rules grouped into UI sections, in display order."""
        fired = self.evaluate(pid)
        groups = {}
        for r in fired:
            groups.setdefault(r['section'], []).append(r)
        return {
            'sections': [
                {'key': s, 'label': SECTION_LABELS[s], 'rules': groups[s]}
                for s in SECTION_ORDER if s in groups
            ],
            'count': len(fired),
            'has_redflag': any(r['section'] == 'redflags' for r in fired),
        }
