"""Repository for clinical decision inputs: flag_catalog, patient_flags, drug_classes.

These are the categorical/boolean inputs (ADA §2) the risk/treatment/follow-up
engines need beyond numeric vitals. See docs/treatment_engine_plan.md.
"""
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now

CATEGORY_LABELS = {
    'cardiac': 'قلبی-عروقی',
    'renal': 'کلیه',
    'risk': 'ریسک',
    'hepatic': 'کبد',
    'repro': 'باروری',
    'lifestyle': 'سبک زندگی',
    'functional': 'وضعیت عملکردی',
    'history': 'سابقه',
    'exam': 'معاینات',
    'other': 'سایر',
}
_CATEGORY_ORDER = ['cardiac', 'renal', 'risk', 'hepatic', 'repro', 'lifestyle',
                   'functional', 'history', 'exam', 'other']


def _parse_options(opt: str) -> list[dict]:
    """'HFrEF|EF کاهش‌یافته,unknown|نامشخص' -> [{value,label}, ...]"""
    out = []
    for part in (opt or '').split(','):
        part = part.strip()
        if not part:
            continue
        if '|' in part:
            v, l = part.split('|', 1)
        else:
            v = l = part
        out.append({'value': v.strip(), 'label': l.strip()})
    return out


class ClinicalFlagsRepository:

    # ---- catalog ----
    def catalog(self, active_only: bool = True) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM flag_catalog"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY display_order, id"
        rows = [dict(r) for r in db.execute(sql).fetchall()]
        for r in rows:
            r['option_list'] = _parse_options(r.get('options'))
            r['category_label'] = CATEGORY_LABELS.get(r['category'], r['category'])
        return rows

    def catalog_grouped(self) -> list[dict]:
        groups = {}
        for f in self.catalog():
            g = groups.setdefault(f['category'], {
                'category': f['category'],
                'label': CATEGORY_LABELS.get(f['category'], f['category']),
                'flags': [],
            })
            g['flags'].append(f)
        return [groups[c] for c in _CATEGORY_ORDER if c in groups] + \
               [g for c, g in groups.items() if c not in _CATEGORY_ORDER]

    # ---- per-patient values ----
    def get_flags(self, pid: int) -> dict:
        db = get_db()
        rows = db.execute(
            "SELECT flag_key, value FROM patient_flags WHERE patient_link_id=?", (pid,)
        ).fetchall()
        return {r['flag_key']: r['value'] for r in rows}

    def set_flag(self, pid: int, flag_key: str, value, recorded_by=None):
        db = get_db()
        now = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        if value is None or value == '':
            db.execute("DELETE FROM patient_flags WHERE patient_link_id=? AND flag_key=?",
                       (pid, flag_key))
        else:
            db.execute(
                """INSERT INTO patient_flags (patient_link_id, flag_key, value, recorded_by, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(patient_link_id, flag_key)
                   DO UPDATE SET value=excluded.value, recorded_by=excluded.recorded_by, updated_at=excluded.updated_at""",
                (pid, flag_key, str(value), recorded_by, now),
            )
        db.commit()

    def set_flags(self, pid: int, values: dict, recorded_by=None):
        for k, v in values.items():
            self.set_flag(pid, k, v, recorded_by=recorded_by)

    # ---- drug classes ----
    def drug_classes(self, active_only: bool = True) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM drug_classes"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY display_order, id"
        return [dict(r) for r in db.execute(sql).fetchall()]

    def drug_class_map(self) -> dict:
        return {c['class_key']: c['label'] for c in self.drug_classes(active_only=False)}
