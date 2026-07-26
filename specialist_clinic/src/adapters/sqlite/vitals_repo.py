"""Repository for vital_readings and lab_results."""
from __future__ import annotations

import sqlite3

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


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
    def __init__(self, db: sqlite3.Connection | None = None):
        self._connection = db

    def _db(self) -> sqlite3.Connection:
        return self._connection or get_db()

    def add_reading(self, pid: int, *, vtype, value, unit=None, measured_at=None,
                    source='clinic', notes=None, recorded_by=None,
                    commit: bool = True) -> int:
        db = self._db()
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
        if commit:
            db.commit()
        return int(cur.lastrowid)

    def get_readings(self, pid: int, vtype: str = None, limit: int = 200) -> list[dict]:
        db = self._db()
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
        rows = self._db().execute(
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

    def latest_by_type(self, pid: int, as_of_at=None) -> dict:
        db = self._db()
        cutoff = None
        if as_of_at is not None:
            cutoff = (as_of_at.strftime('%Y-%m-%d %H:%M:%S')
                      if hasattr(as_of_at, 'strftime') else str(as_of_at))
        time_filter = "" if cutoff is None else " AND measured_at <= ?"
        lab_time_filter = "" if cutoff is None else " AND taken_at <= ?"
        params = (pid, pid) if cutoff is None else (pid, cutoff, pid, cutoff)
        rows = db.execute(
            f"""SELECT key, value, unit, measured_at, source FROM (
                 SELECT type AS key, value, unit, measured_at, source
                   FROM vital_readings WHERE patient_link_id=?{time_filter}
                 UNION ALL
                 SELECT test_key AS key, value, unit, taken_at AS measured_at, 'lab' AS source
                   FROM lab_results WHERE patient_link_id=?{lab_time_filter}
                     AND test_key IS NOT NULL AND test_key <> ''
               )
               WHERE key IS NOT NULL
               ORDER BY measured_at""",
            params,
        ).fetchall()
        latest = {}
        for r in rows:
            latest[r['key']] = {
                'type': r['key'], 'value': r['value'], 'unit': r['unit'],
                'measured_at': r['measured_at'], 'source': r['source'],
            }
        return latest

    def delete_reading(self, reading_id: int, *, commit: bool = True):
        db = self._db()
        db.execute("DELETE FROM vital_readings WHERE id=?", (reading_id,))
        if commit:
            db.commit()

    def add_lab(self, pid: int, *, test_name, value, test_key=None, unit=None,
                ref_low=None, ref_high=None, taken_at=None, notes=None,
                recorded_by=None, commit: bool = True) -> int:
        db = self._db()
        if not taken_at:
            taken_at = iran_now().strftime('%Y-%m-%d %H:%M:%S')
        cur = db.execute(
            """INSERT INTO lab_results
               (patient_link_id, test_name, test_key, value, unit, ref_low, ref_high,
                taken_at, notes, recorded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, test_name, test_key, value, unit, ref_low, ref_high,
             taken_at, notes, recorded_by),
        )
        if commit:
            db.commit()
        return int(cur.lastrowid)

    def get_labs(self, pid: int, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self._db().execute(
            "SELECT * FROM lab_results WHERE patient_link_id=? ORDER BY taken_at DESC LIMIT ?",
            (pid, limit),
        ).fetchall()]

    def delete_lab(self, lab_id: int, *, commit: bool = True):
        db = self._db()
        db.execute("DELETE FROM lab_results WHERE id=?", (lab_id,))
        if commit:
            db.commit()
