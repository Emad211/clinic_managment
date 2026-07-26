from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/src/services/encounter_plan_commitment_service.py"
text = path.read_text(encoding="utf-8")
start = text.index("    def _validate_evidence(\n")
end = text.index("    def transition(\n", start)
replacement = '''    def _validate_evidence(
        self,
        *,
        task_id: int,
        commitment: dict,
        evidence_type: str,
        evidence_ref: str,
        note: str | None,
    ) -> None:
        db = self._db()
        patient_id = int(commitment["patient_link_id"])
        kind = str(commitment["commitment_type"])
        created_at = str(commitment["created_at"])
        evidence = str(evidence_type or "").strip().upper()
        reference = str(evidence_ref or "").strip()
        if evidence not in _ALLOWED_EVIDENCE[kind]:
            raise EncounterPlanCommitmentValidationError(
                "evidence type is not allowed for commitment type"
            )
        if not reference:
            raise EncounterPlanCommitmentValidationError(
                "completion evidence reference is required"
            )
        if evidence == "CONTACT_EVENT":
            row = db.execute(
                """SELECT 1 FROM followup_contact_events
                   WHERE id=? AND task_id=? AND patient_link_id=?
                     AND datetime(occurred_at)>=datetime(?)""",
                (int(reference), int(task_id), patient_id, created_at),
            ).fetchone()
        elif evidence == "APPOINTMENT":
            row = db.execute(
                """SELECT 1 FROM appointments
                   WHERE id=? AND patient_link_id=? AND status='done'
                     AND datetime(scheduled_at)>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        elif evidence == "ENCOUNTER_DOCUMENT":
            row = db.execute(
                """SELECT 1 FROM care_encounter_document_events
                   WHERE id=? AND patient_link_id=? AND document_status='SIGNED'
                     AND datetime(authored_at)>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        elif evidence == "LAB_RESULT":
            row = db.execute(
                """SELECT 1 FROM lab_results
                   WHERE id=? AND patient_link_id=?
                     AND datetime(taken_at)>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        elif evidence == "MEDICATION_EVENT":
            row = db.execute(
                """SELECT 1 FROM medication_events
                   WHERE id=? AND patient_link_id=?
                     AND datetime(COALESCE(event_date,created_at))>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        elif evidence == "VITAL_READING":
            row = db.execute(
                """SELECT 1 FROM vital_readings
                   WHERE id=? AND patient_link_id=?
                     AND datetime(measured_at)>=datetime(?)""",
                (int(reference), patient_id, created_at),
            ).fetchone()
        else:
            row = len(str(note or "").strip()) >= 12
        if not row:
            raise EncounterPlanCommitmentValidationError(
                "completion evidence is stale, incomplete, or outside task scope"
            )

'''
text = text[:start] + replacement + text[end:]
# Add explicit transition field validation before repository append.
anchor = '''        if event == "COMPLETED":
            self._validate_evidence(
'''
insert = '''        if event == "ASSIGNED" and not str(assigned_to or "").strip():
            raise EncounterPlanCommitmentValidationError(
                "assigned_to is required"
            )
        if event == "RESCHEDULED":
            if not due_at:
                raise EncounterPlanCommitmentValidationError(
                    "new due time is required"
                )
            parsed_due = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
            if parsed_due.tzinfo is not None:
                parsed_due = parsed_due.replace(tzinfo=None)
            now = self.clock()
            if now.tzinfo is not None:
                now = now.replace(tzinfo=None)
            if parsed_due < now:
                raise EncounterPlanCommitmentValidationError(
                    "new due time cannot be in the past"
                )
        if event == "SCHEDULED" and appointment_id is None:
            raise EncounterPlanCommitmentValidationError(
                "appointment is required for scheduling"
            )
        if event == "COMPLETED":
            if str(outcome_code or "").strip().upper() not in OUTCOME_LABELS:
                raise EncounterPlanCommitmentValidationError(
                    "completion outcome is required"
                )
            self._validate_evidence(
'''
if insert not in text:
    if anchor not in text:
        raise AssertionError("A10 evidence transition anchor missing")
    text = text.replace(anchor, insert, 1)
path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
