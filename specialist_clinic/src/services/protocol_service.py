"""Clinical decision support: find patients due for standard periodic checks."""
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now, add_months


class ProtocolService:

    def list_protocols(self) -> list[dict]:
        db = get_db()
        rows = db.execute(
            """SELECT cp.*, c.name AS condition_name, c.code AS condition_code
               FROM care_protocols cp LEFT JOIN conditions c ON c.id=cp.condition_id
               WHERE cp.is_active=1 ORDER BY cp.condition_id, cp.interval_months""").fetchall()
        return [dict(r) for r in rows]

    def due_for_protocol(self, protocol: dict) -> list[dict]:
        """Patients with the protocol's condition whose last 'checkup' done appointment
        is older than the interval (or who never had one).
        """
        db = get_db()
        cutoff = add_months(iran_now(), -int(protocol['interval_months'])).strftime('%Y-%m-%d %H:%M:%S')
        rows = db.execute(
            """SELECT p.id, p.full_name, p.phone_number,
                      (SELECT MAX(a.scheduled_at) FROM appointments a
                         WHERE a.patient_link_id=p.id AND a.status='done' AND a.appt_type='checkup') AS last_checkup
               FROM patient_links p
               JOIN patient_conditions pc ON pc.patient_link_id=p.id AND pc.is_active=1
               WHERE p.is_active=1 AND pc.condition_id = ?
            """, (protocol['condition_id'],)).fetchall()
        due = []
        for r in rows:
            last = r['last_checkup']
            if last is None or last < cutoff:
                d = dict(r)
                due.append(d)
        return due

    def summary(self) -> list[dict]:
        """For each protocol, attach the count + list of due patients."""
        result = []
        for p in self.list_protocols():
            due = self.due_for_protocol(p)
            p = dict(p)
            p['due_count'] = len(due)
            p['due_patients'] = due
            result.append(p)
        return result
