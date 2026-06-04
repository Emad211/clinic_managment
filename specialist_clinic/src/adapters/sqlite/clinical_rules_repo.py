"""Repository for the editable clinical decision rules (clinical_indicators).

This is the data-driven core that replaces hard-coded thresholds: the manager
can view and edit every rule at /manager/rules, and the analytics engine,
vitals red-flags, per-disease dashboards and risk score all read from here.
"""
from flask import g
from src.adapters.sqlite.core import get_db

# Fallback defaults used only if the DB table is somehow empty (keeps the app
# working even before the schema seed has run). Mirrors schema.sql seeds.
_FALLBACK = {
    'hba1c': {'label': 'HbA1c', 'unit': '%', 'category': 'glycemic', 'direction': 'high',
              'warn': 7.0, 'danger': 8.0, 'target': 7.0, 'conditions': 'diabetes', 'risk_weight': 3},
    'fbs': {'label': 'قند ناشتا (FBS)', 'unit': 'mg/dL', 'category': 'glycemic', 'direction': 'high',
            'warn': 130, 'danger': 180, 'target': 130, 'conditions': 'diabetes', 'risk_weight': 2},
    'bp_systolic': {'label': 'فشار سیستول', 'unit': 'mmHg', 'category': 'bp', 'direction': 'high',
                    'warn': 130, 'danger': 140, 'target': 130, 'conditions': 'diabetes,hypertension', 'risk_weight': 2},
    'bp_diastolic': {'label': 'فشار دیاستول', 'unit': 'mmHg', 'category': 'bp', 'direction': 'high',
                     'warn': 80, 'danger': 90, 'target': 80, 'conditions': 'diabetes,hypertension', 'risk_weight': 1},
}

# Columns the manager is allowed to edit from the rules page.
EDITABLE_FIELDS = ('label', 'unit', 'category', 'direction', 'warn', 'danger',
                   'target', 'goal_low', 'goal_high', 'conditions', 'risk_weight',
                   'is_vital', 'display_order', 'is_active')

CATEGORY_LABELS = {
    'glycemic': 'قند خون',
    'bp': 'فشار خون',
    'lipid': 'چربی خون',
    'kidney': 'کلیه',
    'anthro': 'تن‌سنجی',
    'other': 'سایر',
}


class ClinicalRulesRepository:

    def all_indicators(self, active_only: bool = True) -> list[dict]:
        """All indicators ordered for display. Cached per-request on flask.g."""
        cache_key = f'_indicators_{active_only}'
        cached = getattr(g, cache_key, None) if g else None
        if cached is not None:
            return cached
        db = get_db()
        sql = "SELECT * FROM clinical_indicators"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY display_order, id"
        rows = [dict(r) for r in db.execute(sql).fetchall()]
        if not rows and active_only:
            rows = [dict(key=k, **v) for k, v in _FALLBACK.items()]
        try:
            setattr(g, cache_key, rows)
        except Exception:
            pass
        return rows

    def as_map(self, active_only: bool = True) -> dict:
        """{key: indicator} map."""
        return {i['key']: i for i in self.all_indicators(active_only)}

    def get(self, key: str) -> dict | None:
        return self.as_map(active_only=False).get(key) or self.as_map().get(key)

    def for_conditions(self, codes: list[str]) -> list[dict]:
        """Indicators that apply to a patient with the given condition codes.

        An indicator applies if its `conditions` is 'all' or shares any code.
        """
        codeset = set(c for c in (codes or []) if c)
        result = []
        for ind in self.all_indicators():
            conds = (ind.get('conditions') or 'all').strip()
            if conds == 'all':
                result.append(ind)
            elif codeset & set(c.strip() for c in conds.split(',') if c.strip()):
                result.append(ind)
        return result

    def update(self, indicator_id: int, fields: dict):
        """Update editable fields of one indicator."""
        sets, params = [], []
        for f in EDITABLE_FIELDS:
            if f in fields:
                sets.append(f"{f}=?")
                params.append(fields[f])
        if not sets:
            return
        params.append(indicator_id)
        db = get_db()
        db.execute(f"UPDATE clinical_indicators SET {', '.join(sets)} WHERE id=?", params)
        db.commit()
        self._clear_cache()

    def create(self, fields: dict) -> int:
        db = get_db()
        cols = ['key'] + [f for f in EDITABLE_FIELDS if f in fields]
        vals = [fields.get('key')] + [fields[f] for f in EDITABLE_FIELDS if f in fields]
        placeholders = ', '.join('?' for _ in cols)
        cur = db.execute(
            f"INSERT OR IGNORE INTO clinical_indicators ({', '.join(cols)}) VALUES ({placeholders})",
            vals)
        db.commit()
        self._clear_cache()
        return cur.lastrowid

    def _clear_cache(self):
        for k in ('_indicators_True', '_indicators_False'):
            if g and hasattr(g, k):
                try:
                    delattr(g, k)
                except Exception:
                    pass
