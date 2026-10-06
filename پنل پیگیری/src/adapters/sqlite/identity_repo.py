"""Identity storage and worklists. All writes target the panel DB, never accounting."""
from __future__ import annotations


RELEVANT = """EXISTS (SELECT 1 FROM acc_item a JOIN acc_item_category c
    ON c.item_type = a.item_type AND c.item_id = a.item_id
    WHERE a.acc_invoice_id = i.acc_id AND a.deleted_at IS NULL
      AND c.category IN ('visit','bs_test','bp_check'))"""
WAITING = """EXISTS (SELECT 1 FROM journey j WHERE j.origin_acc_invoice_id = i.acc_id
    AND j.status = 'awaiting_identity')"""


def person_by_nid(conn, nid):
    return conn.execute("SELECT * FROM person WHERE national_id = ?", (nid,)).fetchone()


def linked_person(conn, patient_id):
    return conn.execute("SELECT p.*, l.method FROM person_acc_link l JOIN person p ON p.id=l.person_id "
                        "WHERE l.acc_patient_id=?", (patient_id,)).fetchone()


def invoice_identity(conn, invoice_id):
    return conn.execute(
        "SELECT i.acc_id AS invoice_id, i.acc_patient_id AS patient_id, i.status, i.work_date, i.shift, "
        "a.name, a.family_name, a.national_id, a.phone, a.identity_ok, a.is_foreign, d.reason AS dismissal, "
        f"({RELEVANT}) AS relevant, ({WAITING}) AS waiting "
        "FROM acc_invoice i LEFT JOIN acc_patient a ON a.acc_id=i.acc_patient_id "
        "LEFT JOIN identity_dismissal d ON d.acc_invoice_id=i.acc_id WHERE i.acc_id=?", (invoice_id,)).fetchone()


def worklist(conn):
    return conn.execute(
        "SELECT i.acc_id AS invoice_id, i.acc_patient_id AS patient_id, i.work_date, i.shift, i.opened_by, "
        "a.name, a.family_name, a.national_id, a.phone, a.identity_ok, "
        "p.first_name, p.last_name, p.national_id AS panel_nid, p.mobile, p.id AS person_id, "
        "d.reason AS dismissal, "
        "(SELECT group_concat(DISTINCT c.category) FROM acc_item x JOIN acc_item_category c "
        " ON c.item_type=x.item_type AND c.item_id=x.item_id WHERE x.acc_invoice_id=i.acc_id "
        " AND x.deleted_at IS NULL AND c.category IN ('visit','bs_test','bp_check')) AS categories "
        "FROM acc_invoice i LEFT JOIN acc_patient a ON a.acc_id=i.acc_patient_id "
        "LEFT JOIN person_acc_link l ON l.acc_patient_id=i.acc_patient_id "
        "LEFT JOIN person p ON p.id=l.person_id "
        "LEFT JOIN identity_dismissal d ON d.acc_invoice_id=i.acc_id "
        f"WHERE d.acc_invoice_id IS NULL AND i.status<>'missing' AND ((i.status='open' AND ({RELEVANT}) AND coalesce(a.identity_ok,0)=0 AND p.id IS NULL) "
        f"OR ({WAITING})) ORDER BY i.opened_at, i.acc_id").fetchall()


def patient_rows(conn, patient_ids=None):
    if patient_ids is None:
        return conn.execute("SELECT acc_id, national_id FROM acc_patient").fetchall()
    out=[]
    ids=sorted(set(patient_ids))
    for start in range(0,len(ids),500):
        batch=ids[start:start+500]
        out.extend(conn.execute("SELECT acc_id, national_id FROM acc_patient WHERE acc_id IN (" +
                                ','.join('?' for _ in batch) + ")", batch).fetchall())
    return out


def insert_person(conn, data, actor, at):
    return conn.execute("INSERT INTO person(national_id,first_name,last_name,mobile,created_at,created_by,updated_at,updated_by) "
                        "VALUES (?,?,?,?,?,?,?,?)", (data['national_id'],data['first_name'],data['last_name'],
                        data['mobile'],at,actor,at,actor)).lastrowid


def update_person(conn, person_id, data, actor, at):
    conn.execute("UPDATE person SET first_name=?,last_name=?,mobile=?,updated_at=?,updated_by=? WHERE id=?",
                 (data['first_name'],data['last_name'],data['mobile'],at,actor,person_id))


def insert_link(conn, patient_id, person_id, method, actor, at):
    conn.execute("INSERT INTO person_acc_link VALUES (?,?,?,?,?)", (patient_id,person_id,method,at,actor))


def set_dismissal(conn, invoice_id, actor, at):
    conn.execute("INSERT INTO identity_dismissal VALUES (?, 'foreign', ?, ?) "
                 "ON CONFLICT(acc_invoice_id) DO UPDATE SET reason='foreign',by_user=excluded.by_user,at=excluded.at",
                 (invoice_id,actor,at))


def bind_clinical_records(conn, patient_id, person_id):
    conn.execute("UPDATE encounter SET person_id=? WHERE acc_patient_id=? AND person_id IS NULL",(person_id,patient_id))
    conn.execute("UPDATE walkin_entry SET person_id=? WHERE acc_patient_id=? AND person_id IS NULL",(person_id,patient_id))
    conn.execute("UPDATE measurement SET person_id=? WHERE person_id IS NULL AND (encounter_id IN "
                 "(SELECT id FROM encounter WHERE acc_patient_id=?) OR walkin_entry_id IN "
                 "(SELECT id FROM walkin_entry WHERE acc_patient_id=?))",(person_id,patient_id,patient_id))


def waiting_journeys(conn, patient_id):
    return conn.execute("SELECT j.* FROM journey j JOIN acc_invoice i ON i.acc_id=j.origin_acc_invoice_id "
                        "LEFT JOIN identity_dismissal d ON d.acc_invoice_id=i.acc_id "
                        "WHERE i.acc_patient_id=? AND j.status='awaiting_identity' AND d.acc_invoice_id IS NULL "
                        "ORDER BY j.created_at,j.id",(patient_id,)).fetchall()


def open_journey_for_template(conn, person_id, code, except_id):
    return conn.execute("SELECT id FROM journey WHERE person_id=? AND template_code=? "
                        "AND status IN ('active','awaiting_identity','needs_review') AND id<>?",(person_id,code,except_id)).fetchone()


def activate_journey(conn, journey_id, person_id):
    conn.execute("UPDATE journey SET person_id=?,status='active' WHERE id=?",(person_id,journey_id))


def cancel_journey(conn, journey_id, reason, at):
    conn.execute("UPDATE journey SET status='cancelled',close_reason=?,closed_at=? WHERE id=?",(reason,at,journey_id))
    conn.execute("UPDATE journey_step SET status='cancelled',resolved_at=? WHERE journey_id=? AND status='pending'",(at,journey_id))


def observe_invoices(conn, invoice_ids, at):
    for iid in invoice_ids:
        conn.execute("INSERT OR IGNORE INTO identity_observation(acc_invoice_id,accounting_identity_ok,observed_at) "
                     "SELECT i.acc_id,coalesce(a.identity_ok,0),? FROM acc_invoice i "
                     "LEFT JOIN acc_patient a ON a.acc_id=i.acc_patient_id "
                     f"WHERE i.acc_id=? AND ({RELEVANT})",(at,iid))


def compliance(conn, date_from, date_to):
    return conn.execute(
        "SELECT coalesce(i.opened_by,'نامشخص') AS username, coalesce(i.shift,'unknown') AS shift, "
        "count(*) AS total, sum(o.accounting_identity_ok) AS first_complete, "
        "sum(coalesce(a.identity_ok,0)) AS accounting_complete, "
        "sum(CASE WHEN p.id IS NOT NULL THEN 1 ELSE 0 END) AS panel_linked, "
        "sum(CASE WHEN d.reason IS NULL AND (coalesce(a.identity_ok,0)=1 OR p.id IS NOT NULL) THEN 1 ELSE 0 END) AS effective_complete, "
        "sum(CASE WHEN d.reason='foreign' THEN 1 ELSE 0 END) AS foreign_excluded "
        "FROM identity_observation o JOIN acc_invoice i ON i.acc_id=o.acc_invoice_id "
        "LEFT JOIN acc_patient a ON a.acc_id=i.acc_patient_id "
        "LEFT JOIN person_acc_link l ON l.acc_patient_id=i.acc_patient_id LEFT JOIN person p ON p.id=l.person_id "
        "LEFT JOIN identity_dismissal d ON d.acc_invoice_id=(SELECT min(dx.acc_invoice_id) FROM identity_dismissal dx "
        "JOIN acc_invoice ix ON ix.acc_id=dx.acc_invoice_id WHERE ix.acc_patient_id=i.acc_patient_id AND dx.reason='foreign') "
        "WHERE i.work_date BETWEEN ? AND ? AND i.status<>'missing' "
        "GROUP BY i.opened_by,i.shift ORDER BY username,shift",(date_from,date_to)).fetchall()


def person_by_id(conn, person_id):
    return conn.execute("SELECT * FROM person WHERE id=?", (person_id,)).fetchone()


def patient_dismissed(conn, patient_id):
    return conn.execute("SELECT 1 FROM identity_dismissal d JOIN acc_invoice i ON i.acc_id=d.acc_invoice_id "
                        "WHERE i.acc_patient_id=? AND d.reason='foreign' LIMIT 1", (patient_id,)).fetchone() is not None


def raw_patient(conn, patient_id):
    return conn.execute("SELECT * FROM acc_patient WHERE acc_id=?", (patient_id,)).fetchone()


def candidates(conn, mobile):
    return conn.execute("SELECT * FROM person WHERE mobile=? ORDER BY id", (mobile,)).fetchall()


def suggestion(conn, invoice_id, person_id, at):
    conn.execute("INSERT OR IGNORE INTO match_suggestion(acc_invoice_id,person_id,reason,status,created_at) "
                 "VALUES (?,?,'mobile+last_name','pending',?)", (invoice_id,person_id,at))
    return conn.execute("SELECT * FROM match_suggestion WHERE acc_invoice_id=? AND person_id=?",
                        (invoice_id,person_id)).fetchone()


def decide_suggestion(conn, invoice_id, person_id, status, actor, at):
    conn.execute("UPDATE match_suggestion SET status=?,decided_by=?,decided_at=? "
                 "WHERE acc_invoice_id=? AND person_id=?", (status,actor,at,invoice_id,person_id))


def all_invoice_ids(conn):
    return [r[0] for r in conn.execute("SELECT acc_id FROM acc_invoice")]
