from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "specialist_clinic/src/adapters/sqlite/encounter_plan_commitment_repo.py"
text = path.read_text(encoding="utf-8")

# Idempotent replay must be resolved before optimistic-concurrency validation.
old = '''        current = self.current_for_task(task_id)
        if not current:
            raise LookupError("plan commitment task not found")
        if int(current["current_event_id"]) != int(expected_current_event_id):
            raise EncounterPlanCommitmentConflict("STALE_PLAN_COMMITMENT")
        event = str(event_type or "").strip().upper()
'''
new = '''        current = self.current_for_task(task_id)
        if not current:
            raise LookupError("plan commitment task not found")
        key = str(idempotency_key or "").strip()
        prior = db.execute(
            "SELECT * FROM care_plan_commitment_events WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        if prior:
            if prior["commitment_id"] != current["commitment_id"]:
                raise EncounterPlanCommitmentConflict(
                    "commitment idempotency scope mismatch"
                )
            return dict(prior)
        if int(current["current_event_id"]) != int(expected_current_event_id):
            raise EncounterPlanCommitmentConflict("STALE_PLAN_COMMITMENT")
        event = str(event_type or "").strip().upper()
'''
if new not in text:
    if old not in text:
        raise AssertionError("A10 repository stale/idempotency anchor missing")
    text = text.replace(old, new, 1)
text = text.replace(
    '            "idempotency_key": str(idempotency_key),',
    '            "idempotency_key": key,',
    1,
)
# Remove the later duplicate idempotency query.
old = '''        prior = db.execute(
            "SELECT * FROM care_plan_commitment_events WHERE idempotency_key=?",
            (payload["idempotency_key"],),
        ).fetchone()
        if prior:
            if prior["commitment_id"] != payload["commitment_id"]:
                raise EncounterPlanCommitmentConflict(
                    "commitment idempotency scope mismatch"
                )
            return dict(prior)
'''
if old not in text:
    raise AssertionError("A10 duplicate idempotency block missing")
text = text.replace(old, "", 1)

# followup_tasks is an identity/projection anchor only. Operational state is exclusively
# projected from care_plan_commitment_events; no shadow UPDATE is permitted.
start = text.index('            if event == "ASSIGNED":\n')
end = text.index('            if commit:\n                db.commit()\n', start)
text = text[:start] + text[end:]

path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
