"""Clinical rule evaluation: direction-aware red-flag logic driven by the
editable clinical_indicators table."""
from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate(indicator: dict, value) -> str:
    """Return 'danger' | 'warn' | 'ok' for a value against one indicator rule.

    Honors direction: 'high' = larger is worse, 'low' = smaller is worse.
    """
    val = _num(value)
    if val is None or not indicator:
        return 'ok'
    warn = _num(indicator.get('warn'))
    danger = _num(indicator.get('danger'))
    direction = (indicator.get('direction') or 'high').lower()
    if direction == 'low':
        if danger is not None and val <= danger:
            return 'danger'
        if warn is not None and val <= warn:
            return 'warn'
        return 'ok'
    # default: high is worse
    if danger is not None and val >= danger:
        return 'danger'
    if warn is not None and val >= warn:
        return 'warn'
    return 'ok'


class ClinicalRulesService:
    def __init__(self, repo: ClinicalRulesRepository | None = None):
        self.repo = repo or ClinicalRulesRepository()

    def evaluate_key(self, key: str, value) -> str:
        return evaluate(self.repo.get(key) or {}, value)

    def map(self):
        return self.repo.as_map()

    def for_conditions(self, codes):
        return self.repo.for_conditions(codes)
