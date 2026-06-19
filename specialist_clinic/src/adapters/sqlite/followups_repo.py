"""Repository for follow-up tasks (worklist)."""
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class FollowupRepository:

    def create(self, pid: int, *, reason, detail=None, due_date=None, assigned_to=None,
               source_rule=None, source_event=None, appointment_id=None,
               fulfillment=None) -> int:
        """fulfillment in remote|in_person — how the task is meant to be closed.
        appointment_id links the task to the visit that fulfills it (or None).

        When fulfillment is None it is derived from the reason: refill (renewal /
        periodic-Rx) is remote-closeable, everything else needs an in-person visit.
        Explicit values are always respected."""
        if fulfillment is None:
            fulfillment = 'remote' if reason == 'refill' else 'in_person'
        db = get_db()
        cur = db.execute(
            """INSERT INTO followup_tasks
                 (patient_link_id, reason, detail, due_date, assigned_to, source_rule,
                  source_event, appointment_id, fulfillment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, reason, detail, due_date, assigned_to, source_rule, source_event,
             appointment_id, fulfillment),
        )
        db.commit()
        return cur.lastrowid

    def set_appointment(self, task_id: int, appointment_id):
        """Link an open task to the visit that will fulfill it."""
        db = get_db()
        db.execute("UPDATE followup_tasks SET appointment_id=? WHERE id=?",
                   (appointment_id, task_id))
        db.commit()

    def assign_appointment_bulk(self, task_ids: list, appointment_id):
        """Attach several open tasks to a single visit (merge same-due follow-ups)."""
        if not task_ids:
            return
        db = get_db()
        placeholders = ",".join("?" for _ in task_ids)
        db.execute(
            f"UPDATE followup_tasks SET appointment_id=? WHERE id IN ({placeholders})",
            [appointment_id, *task_ids],
        )
        db.commit()

    def exists_open(self, pid: int, reason: str) -> bool:
        db = get_db()
        row = db.execute(
            "SELECT 1 FROM followup_tasks WHERE patient_link_id=? AND reason=? AND status='open' LIMIT 1",
            (pid, reason),
        ).fetchone()
        return bool(row)

    def recently_handled_source(self, pid: int, source_rule: str, months: int = None) -> bool:
        """True if there's an OPEN task for this rule, or a DONE one within `months`."""
        db = get_db()
        if db.execute(
            "SELECT 1 FROM followup_tasks WHERE patient_link_id=? AND source_rule=? AND status='open' LIMIT 1",
            (pid, source_rule),
        ).fetchone():
            return True
        if months:
            row = db.execute(
                f"""SELECT 1 FROM followup_tasks WHERE patient_link_id=? AND source_rule=? AND status='done'
                    AND resolved_at >= datetime('now','+3 hours','+30 minutes','-{int(months)} months') LIMIT 1""",
                (pid, source_rule),
            ).fetchone()
        else:
            # one-time item (e.g. zoster): suppress once it has ever been done
            row = db.execute(
                "SELECT 1 FROM followup_tasks WHERE patient_link_id=? AND source_rule=? AND status='done' LIMIT 1",
                (pid, source_rule),
            ).fetchone()
        return bool(row)

    def list_open(self, reason: str = None) -> list[dict]:
        db = get_db()
        sql = """SELECT f.*, p.full_name AS patient_name, p.phone_number
                 FROM followup_tasks f JOIN patient_links p ON p.id=f.patient_link_id
                 WHERE f.status='open'"""
        params = []
        if reason:
            sql += " AND f.reason = ?"
            params.append(reason)
        sql += " ORDER BY f.due_date IS NULL, f.due_date ASC, f.id DESC"
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    def search_open(self, q: str) -> list[dict]:
        """Open tasks whose patient matches `q` by national_id OR full_name OR
        phone_number (LIKE). Returns rows enriched with patient fields."""
        db = get_db()
        like = f"%{(q or '').strip()}%"
        sql = """SELECT f.*, p.full_name AS patient_name, p.phone_number, p.national_id
                 FROM followup_tasks f JOIN patient_links p ON p.id=f.patient_link_id
                 WHERE f.status='open'
                   AND (p.national_id LIKE ? OR p.full_name LIKE ? OR p.phone_number LIKE ?)
                 ORDER BY f.due_date IS NULL, f.due_date ASC, f.id DESC"""
        return [dict(r) for r in db.execute(sql, (like, like, like)).fetchall()]

    def list_for_patient(self, pid: int) -> list[dict]:
        db = get_db()
        return [dict(r) for r in db.execute(
            "SELECT * FROM followup_tasks WHERE patient_link_id=? ORDER BY id DESC", (pid,)).fetchall()]

    def resolve(self, task_id: int, status: str, call_log: str = None):
        db = get_db()
        db.execute(
            "UPDATE followup_tasks SET status=?, call_log=COALESCE(?, call_log), resolved_at=? WHERE id=?",
            (status, call_log, iran_now().strftime('%Y-%m-%d %H:%M:%S'), task_id),
        )
        db.commit()

    def counts_by_reason(self) -> dict:
        db = get_db()
        rows = db.execute(
            "SELECT reason, COUNT(*) c FROM followup_tasks WHERE status='open' GROUP BY reason"
        ).fetchall()
        return {r['reason']: r['c'] for r in rows}
