from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Duplicate booking metrics classify Plan separately from administrative work.
booking = ROOT / "specialist_clinic/src/services/followup_booking_service.py"
text = booking.read_text(encoding="utf-8")
text = text.replace(
    '''                    "admin_booked": sum(
                        1
                        for task_id in normalized_ids
                        if not self._is_clinical(db, task_id)
                    ),
''',
    '''                    "admin_booked": sum(
                        1 for task_id in normalized_ids
                        if self._task_kind(db, task_id) == "admin"
                    ),
''',
    1,
)
booking.write_text(text, encoding="utf-8")

# Service-level appointment ownership/status validation.
service = ROOT / "specialist_clinic/src/services/encounter_plan_commitment_service.py"
text = service.read_text(encoding="utf-8")
old = '''        if event == "SCHEDULED" and appointment_id is None:
            raise EncounterPlanCommitmentValidationError(
                "appointment is required for scheduling"
            )
'''
new = '''        if event == "SCHEDULED":
            if appointment_id is None:
                raise EncounterPlanCommitmentValidationError(
                    "appointment is required for scheduling"
                )
            appointment = self._db().execute(
                """SELECT 1 FROM appointments
                   WHERE id=? AND patient_link_id=? AND status='scheduled'""",
                (int(appointment_id), int(current["patient_link_id"])),
            ).fetchone()
            if not appointment:
                raise EncounterPlanCommitmentValidationError(
                    "scheduled appointment does not belong to commitment patient"
                )
'''
if new not in text:
    if old not in text:
        raise AssertionError("A10 schedule service guard anchor missing")
    text = text.replace(old, new, 1)
service.write_text(text, encoding="utf-8")

# SQLite guard protects direct repository callers too.
schema = ROOT / "specialist_clinic/src/adapters/sqlite/encounter_plan_commitment_schema.py"
text = schema.read_text(encoding="utf-8")
anchor = '''        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_first_event
'''
insert = '''        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_appointment_scope
        BEFORE INSERT ON care_plan_commitment_events
        WHEN NEW.appointment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM care_plan_commitments commitment
            JOIN appointments appointment
              ON appointment.id=NEW.appointment_id
            WHERE commitment.commitment_id=NEW.commitment_id
              AND appointment.patient_link_id=commitment.patient_link_id
        )
        BEGIN SELECT RAISE(ABORT,'plan commitment appointment scope mismatch'); END;

        CREATE TRIGGER IF NOT EXISTS trg_plan_commitment_first_event
'''
if insert not in text:
    if anchor not in text:
        raise AssertionError("A10 appointment DB guard anchor missing")
    text = text.replace(anchor, insert, 1)
schema.write_text(text, encoding="utf-8")
Path(__file__).unlink()
