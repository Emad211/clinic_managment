"""Repository for the patient-record aggregate: surgery history, medical
(comorbidity) history, free-text clinical notes, and the prescription log.

These are the descriptive, non-vital parts of the chronic-disease record (the
"پرونده و داده" tab). Numeric/vital data lives in vitals_repo; clinical decision
flags in flags_repo. All SQL for these four tables lives here (one repo per
aggregate). Tables are defined in schema.sql; assume they exist.
"""
import json

from src.adapters.sqlite.core import get_db

# clinical_notes.kind vocabulary (kept in sync with schema.sql + the record UI).
NOTE_KINDS = ('symptom', 'exam', 'lifestyle', 'general')
# prescriptions.mode vocabulary.
RX_MODES = ('free', 'insurance')


class RecordRepository:

    # ---- surgery history ----
    def list_surgeries(self, pid: int) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            """SELECT * FROM surgery_history WHERE patient_link_id=?
               ORDER BY performed_on IS NULL, performed_on DESC, id DESC""",
            (pid,)).fetchall()]

    def add_surgery(self, pid: int, title: str, performed_on=None, note=None) -> int:
        """performed_on is a gregorian 'YYYY-MM-DD' string (or None)."""
        db = get_db()
        cur = db.execute(
            """INSERT INTO surgery_history (patient_link_id, title, performed_on, note)
               VALUES (?, ?, ?, ?)""",
            (pid, title, performed_on, note),
        )
        db.commit()
        return cur.lastrowid

    def delete_surgery(self, id: int):
        db = get_db()
        db.execute("DELETE FROM surgery_history WHERE id=?", (id,))
        db.commit()

    # ---- medical / comorbidity history ----
    def list_history(self, pid: int) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            """SELECT * FROM medical_history WHERE patient_link_id=?
               ORDER BY since IS NULL, since DESC, id DESC""",
            (pid,)).fetchall()]

    def add_history(self, pid: int, title: str, note=None, since=None) -> int:
        """since is a gregorian 'YYYY-MM-DD' string (or None)."""
        db = get_db()
        cur = db.execute(
            """INSERT INTO medical_history (patient_link_id, title, note, since)
               VALUES (?, ?, ?, ?)""",
            (pid, title, note, since),
        )
        db.commit()
        return cur.lastrowid

    def delete_history(self, id: int):
        db = get_db()
        db.execute("DELETE FROM medical_history WHERE id=?", (id,))
        db.commit()

    # ---- clinical notes (symptom | exam | lifestyle | general) ----
    def list_notes(self, pid: int, kind: str = None) -> list[dict]:
        db = get_db()
        sql = "SELECT * FROM clinical_notes WHERE patient_link_id=?"
        params = [pid]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY recorded_at DESC, id DESC"
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    def add_note(self, pid: int, kind: str, body: str, recorded_by=None) -> int:
        """kind in symptom|exam|lifestyle|general."""
        db = get_db()
        cur = db.execute(
            """INSERT INTO clinical_notes (patient_link_id, kind, body, recorded_by)
               VALUES (?, ?, ?, ?)""",
            (pid, kind, body, recorded_by),
        )
        db.commit()
        return cur.lastrowid

    def delete_note(self, id: int):
        db = get_db()
        db.execute("DELETE FROM clinical_notes WHERE id=?", (id,))
        db.commit()

    # ---- prescription log ----
    def add_prescription(self, pid: int, kind: str, items, mode='free', insurer=None,
                         portal_rx_id=None, prescriber_user_id=None,
                         followup_task_id=None) -> int:
        """Log an issued prescription.

        `items` may be a list/dict (serialized to JSON) or an already-serialized
        string. `mode` in free|insurance; `kind` is the prescription kind (e.g. the
        disease / refill context). Free prescriptions are non-insurance baseline
        scripts the app prints itself; insurance ones come via the prescribing bridge.
        """
        if not isinstance(items, str):
            items = json.dumps(items, ensure_ascii=False)
        db = get_db()
        cur = db.execute(
            """INSERT INTO prescriptions
                 (patient_link_id, kind, items, mode, insurer, portal_rx_id,
                  prescriber_user_id, followup_task_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, kind, items, mode, insurer, portal_rx_id,
             prescriber_user_id, followup_task_id),
        )
        db.commit()
        return cur.lastrowid

    def list_prescriptions(self, pid: int) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM prescriptions WHERE patient_link_id=? ORDER BY issued_at DESC, id DESC",
            (pid,)).fetchall()]
