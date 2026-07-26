from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
repo = ROOT / "specialist_clinic/src/adapters/sqlite/encounter_plan_commitment_repo.py"
text = repo.read_text(encoding="utf-8")
text = text.replace(
    'SELECT commitment.*,link.task_id,task.reason,task.detail,',
    'SELECT commitment.*,link.task_id AS id,link.task_id,task.reason,task.detail,',
    1,
)
repo.write_text(text, encoding="utf-8")

followups = ROOT / "specialist_clinic/src/adapters/sqlite/followups_repo.py"
text = followups.read_text(encoding="utf-8")
anchor = '''        return bool(
            ClinicalCareLoopRepository().list_current(
                patient_link_id=patient_link_id,
                reason=reason,
                include_terminal=False,
            )
        )
'''
replacement = '''        if ClinicalCareLoopRepository().list_current(
            patient_link_id=patient_link_id,
            reason=reason,
            include_terminal=False,
        ):
            return True
        if reason != "encounter_plan":
            return False
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        return bool(
            EncounterPlanCommitmentRepository().list_current(
                patient_link_id=patient_link_id,
                include_terminal=False,
            )
        )
'''
if replacement not in text:
    if anchor not in text:
        raise AssertionError("A10 exists_open anchor missing")
    text = text.replace(anchor, replacement, 1)
followups.write_text(text, encoding="utf-8")
Path(__file__).unlink()
