"""Repository for patient_links and their chronic-care records."""
from typing import Optional, Any
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class PatientRepository:

    # ---- patient_links ----
    def get_by_id(self, pid: int) -> Optional[dict]:
        db = get_db()
        row = db.execute("SELECT * FROM patient_links WHERE id = ?", (pid,)).fetchone()
        return dict(row) if row else None

    def get_by_national_id(self, national_id: str) -> Optional[dict]:
        db = get_db()
        row = db.execute("SELECT * FROM patient_links WHERE national_id = ?", (national_id,)).fetchone()
        return dict(row) if row else None

    def list_patients(self, query: str = "") -> list[dict]:
        db = get_db()
        q = (query or "").strip()
        if q:
            like = f"%{q}%"
            rows = db.execute(
                """SELECT * FROM patient_links
                   WHERE is_active=1 AND (full_name LIKE ? OR COALESCE(national_id,'') LIKE ? OR COALESCE(phone_number,'') LIKE ?)
                   ORDER BY id DESC""",
                (like, like, like),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM patient_links WHERE is_active=1 ORDER BY id DESC LIMIT 500"
            ).fetchall()
        return [dict(r) for r in rows]

    def create(self, *, national_id, accounting_patient_id, full_name, phone_number,
               gender, birthdate, address, enrolled_by) -> int:
        db = get_db()
        cur = db.execute(
            """INSERT INTO patient_links
               (national_id, accounting_patient_id, full_name, phone_number, gender, birthdate, address, enrolled_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (national_id, accounting_patient_id, full_name, phone_number, gender, birthdate, address, enrolled_by),
        )
        db.commit()
        return cur.lastrowid

    def update_contact(self, pid: int, *, phone_number, address, notes):
        db = get_db()
        db.execute(
            "UPDATE patient_links SET phone_number=?, address=?, notes=?, updated_at=? WHERE id=?",
            (phone_number, address, notes, iran_now().strftime('%Y-%m-%d %H:%M:%S'), pid),
        )
        db.commit()

    # ---- conditions ----
    def list_condition_catalog(self) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute("SELECT * FROM conditions WHERE is_active=1 ORDER BY id").fetchall()]

    def get_patient_conditions(self, pid: int) -> list[dict]:
        db = get_db()
        rows = db.execute(
            """SELECT pc.*, c.name AS condition_name, c.code AS condition_code
               FROM patient_conditions pc JOIN conditions c ON c.id = pc.condition_id
               WHERE pc.patient_link_id = ? AND pc.is_active = 1
               ORDER BY pc.id DESC""",
            (pid,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_condition(self, pid: int, condition_id: int, stage: str = None,
                      onset_date: str = None, notes: str = None) -> int:
        db = get_db()
        cur = db.execute(
            "INSERT INTO patient_conditions (patient_link_id, condition_id, stage, onset_date, notes) VALUES (?, ?, ?, ?, ?)",
            (pid, condition_id, stage, onset_date, notes),
        )
        db.commit()
        return cur.lastrowid

    def remove_condition(self, pc_id: int):
        db = get_db()
        db.execute("UPDATE patient_conditions SET is_active=0 WHERE id=?", (pc_id,))
        db.commit()

    # ---- medications ----
    def get_medications(self, pid: int, active_only: bool = True) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM patient_medications WHERE patient_link_id = ?"
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY is_active DESC, id DESC"
        return [dict(r) for r in db.execute(sql, (pid,)).fetchall()]

    def get_medication(self, med_id: int) -> Optional[dict]:
        db = get_db()
        row = db.execute("SELECT * FROM patient_medications WHERE id=?", (med_id,)).fetchone()
        return dict(row) if row else None

    def add_medication(self, pid: int, *, drug_name, dose, schedule, start_date,
                       refill_due_date, notes, drug_class=None, created_by=None) -> int:
        db = get_db()
        cur = db.execute(
            """INSERT INTO patient_medications
               (patient_link_id, drug_name, dose, schedule, start_date, refill_due_date, notes, drug_class)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, drug_name, dose, schedule, start_date, refill_due_date, notes, drug_class),
        )
        med_id = cur.lastrowid
        self._log_med_event(pid, med_id, drug_name, 'start', dose=dose,
                            event_date=start_date, created_by=created_by)
        db.commit()
        return med_id

    def stop_medication(self, med_id: int, end_date: str = None, created_by=None):
        db = get_db()
        med = self.get_medication(med_id)
        db.execute("UPDATE patient_medications SET is_active=0, end_date=? WHERE id=?",
                   (end_date, med_id))
        if med:
            self._log_med_event(med['patient_link_id'], med_id, med['drug_name'], 'stop',
                                dose=med.get('dose'), event_date=end_date, created_by=created_by)
        db.commit()

    def change_dose(self, med_id: int, new_dose: str, change_date: str = None,
                    note: str = None, created_by=None):
        db = get_db()
        med = self.get_medication(med_id)
        if not med:
            return
        db.execute("UPDATE patient_medications SET dose=? WHERE id=?", (new_dose, med_id))
        self._log_med_event(med['patient_link_id'], med_id, med['drug_name'], 'dose_change',
                            dose=new_dose, event_date=change_date, note=note, created_by=created_by)
        db.commit()

    # ---- medication events (start / stop / dose-change timeline) ----
    def _log_med_event(self, pid, med_id, drug_name, event_type, *, dose=None,
                       event_date=None, note=None, created_by=None):
        from src.common.utils import today_str
        db = get_db()
        db.execute(
            """INSERT INTO medication_events
               (patient_link_id, medication_id, drug_name, event_type, dose, event_date, note, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, med_id, drug_name, event_type, dose, event_date or today_str(), note, created_by),
        )

    def get_medication_events(self, pid: int, med_id: int = None) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM medication_events WHERE patient_link_id=?"
        params = [pid]
        if med_id is not None:
            sql += " AND medication_id=?"
            params.append(med_id)
        sql += " ORDER BY event_date, id"
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    # ---- allergies ----
    def get_allergies(self, pid: int) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM allergies WHERE patient_link_id=? ORDER BY id DESC", (pid,)).fetchall()]

    def add_allergy(self, pid: int, *, substance, reaction, severity) -> int:
        db = get_db()
        cur = db.execute(
            "INSERT INTO allergies (patient_link_id, substance, reaction, severity) VALUES (?, ?, ?, ?)",
            (pid, substance, reaction, severity),
        )
        db.commit()
        return cur.lastrowid

    def delete_allergy(self, allergy_id: int):
        db = get_db()
        db.execute("DELETE FROM allergies WHERE id=?", (allergy_id,))
        db.commit()
