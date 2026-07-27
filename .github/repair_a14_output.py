from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "specialist_clinic"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"A14 output repair anchor missing in {path}: {old[:160]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


doctor = S / "tests/test_doctor_queue.py"
replace_once(
    doctor,
    '''def _enroll_patient(spec_db, national_id, full_name="بیمار آزمون"):
    """Insert a patient_links row in the specialist DB; return the inserted id."""
    conn = sqlite3.connect(spec_db)
    cur = conn.execute(
        "INSERT INTO patient_links (national_id, full_name, enrolled_by) VALUES (?, ?, 'test')",
        (national_id, full_name),
    )
    conn.commit()
    link_id = cur.lastrowid
    conn.close()
    return link_id
''',
    '''def _complete_enrollment(spec_db, patient_link_id, accounting_patient_id):
    """Install the explicit immutable specialist cutover used by current queue identity."""
    conn = sqlite3.connect(spec_db)
    when = "2026-06-20 00:00:00"
    conn.execute(
        "UPDATE patient_links SET accounting_patient_id=? WHERE id=?",
        (int(accounting_patient_id), int(patient_link_id)),
    )
    digest = hashlib.sha256(
        f"doctor-queue-test-enrollment:{int(patient_link_id)}:{int(accounting_patient_id)}".encode()
    ).hexdigest()
    conn.execute(
        """INSERT INTO specialist_program_enrollments
           (patient_link_id, accounting_patient_id, effective_at,
            accounting_snapshot_at, accounting_invoice_cutoff_id,
            history_policy, created_by, content_hash, created_at)
           VALUES (?, ?, ?, ?, 0, 'VISIBLE_EXCLUDED', 'test', ?, ?)""",
        (int(patient_link_id), int(accounting_patient_id), when, when, digest, when),
    )
    conn.commit()
    conn.close()


def _enroll_patient(
    spec_db, national_id, full_name="بیمار آزمون", accounting_patient_id=None
):
    """Create the local mirror and, when supplied, its explicit accounting cutover."""
    conn = sqlite3.connect(spec_db)
    cur = conn.execute(
        """INSERT INTO patient_links
           (national_id, accounting_patient_id, full_name, enrolled_by)
           VALUES (?, ?, ?, 'test')""",
        (national_id, accounting_patient_id, full_name),
    )
    conn.commit()
    link_id = cur.lastrowid
    conn.close()
    if accounting_patient_id is not None:
        # The local row already owns the accounting identity; only append the cutover.
        conn = sqlite3.connect(spec_db)
        when = "2026-06-20 00:00:00"
        digest = hashlib.sha256(
            f"doctor-queue-test-enrollment:{int(link_id)}:{int(accounting_patient_id)}".encode()
        ).hexdigest()
        conn.execute(
            """INSERT INTO specialist_program_enrollments
               (patient_link_id, accounting_patient_id, effective_at,
                accounting_snapshot_at, accounting_invoice_cutoff_id,
                history_policy, created_by, content_hash, created_at)
               VALUES (?, ?, ?, ?, 0, 'VISIBLE_EXCLUDED', 'test', ?, ?)""",
            (int(link_id), int(accounting_patient_id), when, when, digest, when),
        )
        conn.commit()
        conn.close()
    return link_id
''',
)

replace_once(
    doctor,
    '        _enroll_patient(spec_db, nid, "بیمارِ ثبت‌شده")\n',
    '        _enroll_patient(\n'
    '            spec_db, nid, "بیمارِ ثبت‌شده", accounting_patient_id=pid\n'
    '        )\n',
)
replace_once(
    doctor,
    '        _enroll_patient(spec_db, nid, "ثبت‌شده ۲")\n',
    '        _enroll_patient(\n'
    '            spec_db, nid, "ثبت‌شده ۲", accounting_patient_id=pid\n'
    '        )\n',
)

# The save scenarios create their local mirror before the accounting fixture; append
# the explicit cutover as soon as the canonical accounting patient id exists.
replace_once(
    doctor,
    '        acc_pid = _acc_add_patient(conn, "بیمارِ ذخیره", national_id=nid)\n'
    '        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date=_active_day())\n',
    '        acc_pid = _acc_add_patient(conn, "بیمارِ ذخیره", national_id=nid)\n'
    '        _complete_enrollment(spec_db, pid, acc_pid)\n'
    '        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date=_active_day())\n',
)
replace_once(
    doctor,
    '        acc_pid = _acc_add_patient(conn, "بیمارِ چندشاخص", national_id=nid)\n'
    '        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date=_active_day())\n',
    '        acc_pid = _acc_add_patient(conn, "بیمارِ چندشاخص", national_id=nid)\n'
    '        _complete_enrollment(spec_db, pid, acc_pid)\n'
    '        inv_id = _acc_add_invoice(conn, acc_pid, status="open", work_date=_active_day())\n',
)

ui = S / "tests/test_ui_information_architecture.py"
replace_once(
    ui,
    '    assert page.count(\'class="hub-nav-btn\') == 6\n',
    '    assert page.count("hub-nav-btn") == 6\n',
)

print("A14 output aligned with canonical enrollment and UI tokens")
