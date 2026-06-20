"""Read-only projection for the public patient card (ADR-0004).

This is the CQRS read-side for the patient-facing card Channel. It MUST stay strictly
read-only: only SELECTs — NEVER INSERT / UPDATE / DELETE / commit / executemany — and it
NEVER emits `national_id`. A guard test (tests/test_patient_card.py) enforces all of this
by scanning this module's source. The public card blueprint calls ONLY this module.

Content is the minimum safe set agreed in ADR-0004 §6 (clinical wins the content call):
patient first-name, last everyday vitals (FBS + blood pressure) with a plain-Persian
colour status, the next appointment, and the clinic phone. It deliberately shows NO
drug names, NO diagnosis/condition, NO raw HbA1c, NO national_id/phone/address.
"""
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.patient_card_repo import PatientCardRepository
from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
from src.adapters.sqlite.sms_repo import SmsRepository
from src.services.vitals_service import evaluate_reading
from src.common.utils import iran_now

# Everyday, patient-understandable vitals only (ADR-0004 §6 — no raw HbA1c on the card).
CARD_VITALS = ('fbs', 'bp_systolic', 'bp_diastolic')

# level -> (plain-Persian status text shown to the patient, css class). No "danger" label.
_STATUS = {
    'ok':     ('در محدودهٔ هدف', 'ok'),
    'warn':   ('نیاز به پیگیری', 'warn'),
    'danger': ('لطفاً همین امروز با کلینیک تماس بگیرید', 'danger'),
}
_ORDER = {'ok': 0, 'warn': 1, 'danger': 2}


def _token_valid(row: dict | None) -> bool:
    if not row or row.get('revoked_at'):
        return False
    return (row.get('expires_at') or '') >= iran_now().strftime('%Y-%m-%d %H:%M:%S')


def card_for_token(token: str) -> dict | None:
    """Resolve a card token to a minimal, safe, READ-ONLY DTO — or None if the token is
    unknown / expired / revoked. Never returns national_id."""
    row = PatientCardRepository().get_by_token(token)
    if not _token_valid(row):
        return None
    pid = row['patient_link_id']
    db = get_db()
    p = db.execute("SELECT full_name FROM patient_links WHERE id=?", (pid,)).fetchone()
    if not p:
        return None
    first_name = ((p['full_name'] or '').strip().split(' ') or [''])[0]

    latest = VitalsRepository().latest_by_type(pid)
    vitals, worst = [], 'ok'
    for vt in CARD_VITALS:
        r = latest.get(vt)
        if not r:
            continue
        level = evaluate_reading(vt, r['value'])
        if _ORDER[level] > _ORDER[worst]:
            worst = level
        text, cls = _STATUS[level]
        meta = VITAL_TYPES.get(vt, {})
        vitals.append({'label': meta.get('label', vt), 'value': r['value'],
                       'unit': meta.get('unit', ''), 'measured_at': r['measured_at'],
                       'status_text': text, 'level': cls})

    appt = db.execute(
        "SELECT * FROM appointments WHERE patient_link_id=? AND status='scheduled' "
        "AND date(scheduled_at) >= date('now','+3 hours','+30 minutes') "
        "ORDER BY scheduled_at LIMIT 1", (pid,)).fetchone()
    next_appt = None
    if appt:
        appt = dict(appt)
        next_appt = {'scheduled_at': appt.get('scheduled_at'),
                     'type': appt.get('appt_type') or appt.get('reason') or 'ویزیتِ کنترل'}

    sms = SmsRepository()
    return {
        'first_name': first_name,
        'vitals': vitals,
        'overall_level': worst,
        'next_appointment': next_appt,
        'clinic_name': sms.get_setting('clinic_name', 'کلینیک تخصصی'),
        'clinic_phone': sms.get_setting('clinic_phone', ''),
    }
