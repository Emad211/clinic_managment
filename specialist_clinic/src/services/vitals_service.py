"""Vitals logic: red-flag evaluation and control status.

Red-flag thresholds now live in the editable `clinical_indicators` table
(see clinical_rules_repo / ClinicalRulesService). The hard-coded THRESHOLDS
below are kept only as a last-resort fallback if the rules table is empty.
"""
from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
from src.services.clinical_rules_service import evaluate as _evaluate_rule

# Fallback red-flag thresholds (used only if no indicator rule is found).
THRESHOLDS = {
    'hba1c': {'high': 8.0, 'warn': 7.0},        # %
    'fbs': {'high': 180, 'warn': 130},          # mg/dL
    'bp_systolic': {'high': 140, 'warn': 130},  # mmHg
    'bp_diastolic': {'high': 90, 'warn': 80},   # mmHg
}


def _fallback_eval(vtype: str, value) -> str:
    t = THRESHOLDS.get(vtype)
    if not t or value is None:
        return 'ok'
    if value >= t['high']:
        return 'danger'
    if value >= t['warn']:
        return 'warn'
    return 'ok'


def evaluate_reading(vtype: str, value: float) -> str:
    """Return 'danger' | 'warn' | 'ok' for a single reading.

    Reads thresholds from the editable clinical_indicators rules; falls back
    to the static THRESHOLDS map if the rule is missing.
    """
    if value is None:
        return 'ok'
    try:
        from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
        indicator = ClinicalRulesRepository().get(vtype)
        if indicator:
            return _evaluate_rule(indicator, value)
    except Exception:
        pass
    return _fallback_eval(vtype, value)


class VitalsService:
    def __init__(self, repo: VitalsRepository | None = None):
        self.repo = repo or VitalsRepository()

    def control_status(self, pid: int) -> dict:
        """Overall control status from the latest readings.

        Returns {status: 'controlled'|'uncontrolled'|'unknown', flags: {type: level}}.
        """
        latest = self.repo.latest_by_type(pid)
        flags = {}
        worst = 'ok'
        order = {'ok': 0, 'warn': 1, 'danger': 2}
        for vtype, reading in latest.items():
            level = evaluate_reading(vtype, reading['value'])
            if level != 'ok':
                flags[vtype] = level
            if order[level] > order[worst]:
                worst = level
        if not latest:
            status = 'unknown'
        elif worst == 'danger':
            status = 'uncontrolled'
        elif worst == 'warn':
            status = 'borderline'
        else:
            status = 'controlled'
        return {'status': status, 'flags': flags, 'latest': latest}

    def chart_series(self, pid: int, vtype: str) -> dict:
        """Return {labels: [...jalali...], values: [...]} for a vital type trend."""
        from src.common.utils import format_jalali_date
        readings = self.repo.get_readings(pid, vtype=vtype, limit=200)
        return {
            'label': VITAL_TYPES.get(vtype, {}).get('label', vtype),
            'unit': VITAL_TYPES.get(vtype, {}).get('unit', ''),
            'labels': [format_jalali_date(r['measured_at']) for r in readings],
            'values': [r['value'] for r in readings],
        }
