"""Repository for vital_readings and lab_results."""
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now

# Display metadata for vital types
VITAL_TYPES = {
    'bp_systolic': {'label': 'فشار سیستول', 'unit': 'mmHg'},
    'bp_diastolic': {'label': 'فشار دیاستول', 'unit': 'mmHg'},
    'fbs': {'label': 'قند ناشتا (FBS)', 'unit': 'mg/dL'},
    'hba1c': {'label': 'HbA1c', 'unit': '%'},
    'weight': {'label': 'وزن', 'unit': 'kg'},
    'bmi': {'label': 'BMI', 'unit': ''},
    'pulse': {'label': 'ضربان قلب', 'unit': 'bpm'},
}


class VitalsRepository:

    def add_reading(self, pid: int, *, vtype, value, unit=None, measured_at=None,
                    source='clinic', notes=None, recorded_by=None) -> int:
        db = get_db()
        if not measured_at:
            measured_at = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        if unit is None:
            unit = VITAL_TYPES.get(vtype, {}).get('unit')
        cur = db.execute(
            """INSERT INTO vital_readings
               (patient_link_id, type, value, unit, measured_at, source, notes, recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, vtype, value, unit, measured_at, source, notes, recorded_by),
        )
        db.commit()
        return cur.lastrowid

    def get_readings(self, pid: int, vtype: str = None, limit: int = 200) -> list[dict]:
        db = get_db()
        if vtype:
            rows = db.execute(
                "SELECT * FROM vital_readings WHERE patient_link_id=? AND type=? ORDER BY measured_at ASC LIMIT ?",
                (pid, vtype, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM vital_readings WHERE patient_link_id=? ORDER BY measured_at DESC LIMIT ?",
                (pid, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_readings_canonical(self, pid: int, key: str, limit: int = 200) -> list[dict]:
        """Time series for one canonical indicator key across BOTH capture channels
        (vital_readings.type AND lab_results.test_key), oldest→newest (ADR-0005). Drop-in
        for get_readings(vtype=key) but lab-aware. Each row: {value, measured_at, unit, source}."""
        rows = get_db().execute(
            """SELECT value, measured_at, unit, source FROM (
                 SELECT value, measured_at, unit, source FROM vital_readings
                   WHERE patient_link_id=? AND type=?
                 UNION ALL
                 SELECT value, taken_at AS measured_at, unit, 'lab' AS source FROM lab_results
                   WHERE patient_link_id=? AND test_key=?
               ) ORDER BY measured_at ASC LIMIT ?""",
            (pid, key, pid, key, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_by_type(self, pid: int) -> dict:
        """Most recent observation per canonical key across BOTH capture channels:
        vital_readings (by `type`) and catalog-keyed lab_results (by `test_key`). They are
        one canonical concept on a shared vocabulary (hba1c, fbs, ldl, egfr, …), so a
        lab-entered HbA1c counts the same as a clinic-entered one (ADR-0005). Returns
        {key: {type, value, unit, measured_at, source}} — the latest per key wins."""
        db = get_db()
        rows = db.execute(
            """SELECT key, value, unit, measured_at, source FROM (
                 SELECT type AS key, value, unit, measured_at, source
                   FROM vital_readings WHERE patient_link_id=?
                 UNION ALL
                 SELECT test_key AS key, value, unit, taken_at AS measured_at, 'lab' AS source
                   FROM lab_results WHERE patient_link_id=? AND test_key IS NOT NULL AND test_key <> ''
               )
               WHERE key IS NOT NULL
               ORDER BY measured_at""",
            (pid, pid),
        ).fetchall()
        latest = {}
        for r in rows:  # ascending measured_at -> last write per key is the most recent
            latest[r['key']] = {'type': r['key'], 'value': r['value'], 'unit': r['unit'],
                                'measured_at': r['measured_at'], 'source': r['source']}
        return latest

    def delete_reading(self, reading_id: int):
        db = get_db()
        db.execute("DELETE FROM vital_readings WHERE id=?", (reading_id,))
        db.commit()

    # ---- lab results ----
    def add_lab(self, pid: int, *, test_name, value, test_key=None, unit=None, ref_low=None,
                ref_high=None, taken_at=None, notes=None, recorded_by=None) -> int:
        db = get_db()
        if not taken_at:
            taken_at = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        cur = db.execute(
            """INSERT INTO lab_results
               (patient_link_id, test_name, test_key, value, unit, ref_low, ref_high, taken_at, notes, recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, test_name, test_key, value, unit, ref_low, ref_high, taken_at, notes, recorded_by),
        )
        db.commit()
        return cur.lastrowid

    def get_labs(self, pid: int, limit: int = 100) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM lab_results WHERE patient_link_id=? ORDER BY taken_at DESC LIMIT ?",
            (pid, limit)).fetchall()]

    def delete_lab(self, lab_id: int):
        db = get_db()
        db.execute("DELETE FROM lab_results WHERE id=?", (lab_id,))
        db.commit()
