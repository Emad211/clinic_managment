from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "specialist_clinic/tests/test_visit_invites.py"
text = PATH.read_text(encoding="utf-8")

old_first = '''        nid = "1110000001"
        pid = _enroll(nid, "بیمارِ دعوت", phone_number="09120000011")

        acc_db = os.path.join(tmp_dir, "acc_b.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ دعوت", national_id=nid, phone="09120000011")
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)

        rv = client.post(
            f"/doctor-queue/{inv_id}/invite",
            data={"event_key": "lab_consult_invite", "national_id": nid},
            follow_redirects=False)
'''
new_first = '''        nid = "1110000001"
        from src.common.utils import today_str
        work_date = today_str()

        acc_db = os.path.join(tmp_dir, "acc_b.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ دعوت", national_id=nid, phone="09120000011")
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date=work_date)
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)
        from src.services.patient_service import PatientService
        pid = PatientService().enroll_from_accounting(acc_pid, "admin")
        started = client.post(f"/doctor-queue/{inv_id}/start")
        assert started.status_code == 302

        rv = client.post(
            f"/doctor-queue/{inv_id}/invite",
            data={"event_key": "lab_consult_invite", "national_id": "TAMPERED"},
            follow_redirects=False)
'''
old_second = '''        nid = "1110000002"
        pid = _enroll(nid, "بیمارِ قند", phone_number="09120000012")
        acc_db = os.path.join(tmp_dir, "acc_b2.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ قند", national_id=nid, phone="09120000012")
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date="2026-06-20")
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)

        client.post(f"/doctor-queue/{inv_id}/invite",
                    data={"event_key": "bp_glucose_invite", "national_id": nid})
'''
new_second = '''        nid = "1110000002"
        from src.common.utils import today_str
        work_date = today_str()
        acc_db = os.path.join(tmp_dir, "acc_b2.db")
        _make_acc_db(acc_db)
        conn = sqlite3.connect(acc_db)
        acc_pid = _acc_add_patient(conn, "بیمارِ قند", national_id=nid, phone="09120000012")
        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date=work_date)
        _acc_add_visit(conn, inv_id, acc_pid)
        conn.close()
        _set_acc_path(acc_db)
        from src.services.patient_service import PatientService
        pid = PatientService().enroll_from_accounting(acc_pid, "admin")
        assert client.post(f"/doctor-queue/{inv_id}/start").status_code == 302

        client.post(f"/doctor-queue/{inv_id}/invite",
                    data={"event_key": "bp_glucose_invite", "national_id": "TAMPERED"})
'''

for old, new in ((old_first, new_first), (old_second, new_second)):
    if new in text:
        continue
    if old not in text:
        raise AssertionError("visit invite compatibility anchor missing")
    text = text.replace(old, new, 1)

PATH.write_text(text, encoding="utf-8")
Path(__file__).unlink()
