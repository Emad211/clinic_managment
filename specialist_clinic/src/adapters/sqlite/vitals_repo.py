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

    def latest_by_type(self, pid: int) -> dict:
        """Return the most recent reading per vital type."""
        db = get_db()
        rows = db.execute(
            """SELECT v.* FROM vital_readings v
               JOIN (SELECT type, MAX(measured_at) mx FROM vital_readings WHERE patient_link_id=? GROUP BY type) t
                 ON t.type = v.type AND t.mx = v.measured_at
               WHERE v.patient_link_id=?""",
            (pid, pid),
        ).fetchall()
        return {r['type']: dict(r) for r in rows}

    def delete_reading(self, reading_id: int):
        db = get_db()
        db.execute("DELETE FROM vital_readings WHERE id=?", (reading_id,))
        db.commit()

    # ---- lab results ----
    def add_lab(self, pid: int, *, test_name, value, unit=None, ref_low=None,
                ref_high=None, taken_at=None, notes=None, recorded_by=None) -> int:
        db = get_db()
        if not taken_at:
            taken_at = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        cur = db.execute(
            """INSERT INTO lab_results
               (patient_link_id, test_name, value, unit, ref_low, ref_high, taken_at, notes, recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, test_name, value, unit, ref_low, ref_high, taken_at, notes, recorded_by),
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
