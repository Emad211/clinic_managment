"""Read-only descriptive projection for the public patient card (ADR-0004).

This is the CQRS read-side for the patient-facing card channel. It MUST stay strictly
read-only: only SELECTs — NEVER INSERT / UPDATE / DELETE / commit / executemany — and it
NEVER emits ``national_id``.

The public card is intentionally *descriptive only*. It may show the latest permitted
measurements and their timestamps, but it must not evaluate thresholds, assign a
clinical status, declare a target met, or tell the patient what clinical action to take.
Those outputs belong exclusively to the governed Clinical Engine v2 and an authenticated
clinical workflow.
"""
from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.patient_card_repo import PatientCardRepository
from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
from src.adapters.sqlite.sms_repo import SmsRepository
from src.common.utils import iran_now

# Everyday, patient-understandable measurements only (ADR-0004 §6 — no raw HbA1c).
CARD_VITALS = ("fbs", "bp_systolic", "bp_diastolic")


def _token_valid(row: dict | None) -> bool:
    if not row or row.get("revoked_at"):
        return False
    return (row.get("expires_at") or "") >= iran_now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def card_for_token(token: str) -> dict | None:
    """Resolve a token to a minimal descriptive, read-only DTO or return ``None``."""
    row = PatientCardRepository().get_by_token(token)
    if not _token_valid(row):
        return None
    pid = row["patient_link_id"]
    db = get_db()
    patient = db.execute(
        "SELECT full_name FROM patient_links WHERE id=?", (pid,)
    ).fetchone()
    if not patient:
        return None
    first_name = ((patient["full_name"] or "").strip().split(" ") or [""])[0]

    latest = VitalsRepository().latest_by_type(pid)
    vitals = []
    for vital_type in CARD_VITALS:
        reading = latest.get(vital_type)
        if not reading:
            continue
        meta = VITAL_TYPES.get(vital_type, {})
        vitals.append(
            {
                "label": meta.get("label", vital_type),
                "value": reading["value"],
                "unit": meta.get("unit", ""),
                "measured_at": reading["measured_at"],
            }
        )

    appointment = db.execute(
        "SELECT * FROM appointments WHERE patient_link_id=? AND status='scheduled' "
        "AND date(scheduled_at) >= date('now','+3 hours','+30 minutes') "
        "ORDER BY scheduled_at LIMIT 1",
        (pid,),
    ).fetchone()
    next_appointment = None
    if appointment:
        appointment = dict(appointment)
        next_appointment = {
            "scheduled_at": appointment.get("scheduled_at"),
            "type": (
                appointment.get("appt_type")
                or appointment.get("reason")
                or "ویزیتِ کنترل"
            ),
        }

    sms = SmsRepository()
    return {
        "first_name": first_name,
        "vitals": vitals,
        "next_appointment": next_appointment,
        "clinic_name": sms.get_setting("clinic_name", "کلینیک تخصصی"),
        "clinic_phone": sms.get_setting("clinic_phone", ""),
        "projection_policy": "DESCRIPTIVE_ONLY",
    }
