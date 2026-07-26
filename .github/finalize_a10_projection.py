from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def path(relative: str) -> Path:
    target = ROOT / relative
    if not target.exists():
        raise AssertionError(f"A10 projection target missing: {relative}")
    return target


def replace_once(relative: str, old: str, new: str) -> None:
    target = path(relative)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A10 projection anchor missing in {relative}: {old[:220]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Add list projection to the commitment repository.
repo_path = path("specialist_clinic/src/adapters/sqlite/encounter_plan_commitment_repo.py")
repo = repo_path.read_text(encoding="utf-8")
method = '''
    def list_current(
        self,
        *,
        patient_link_id: int | None = None,
        query: str | None = None,
        include_terminal: bool = False,
    ) -> list[dict]:
        sql = """SELECT commitment.*,link.task_id,task.reason,task.detail,
                        task.source_engine,task.source_event,task.source_rule,
                        task.fulfillment,patient.full_name AS patient_name,
                        patient.phone_number,patient.national_id,
                        event.id AS current_event_id,
                        event.event_type AS current_event_type,
                        event.status AS current_status,
                        event.due_at AS current_due_at,
                        event.assigned_to AS current_assigned_to,
                        event.appointment_id AS current_appointment_id,
                        event.evidence_type AS current_evidence_type,
                        event.evidence_ref AS current_evidence_ref,
                        event.outcome_code AS current_outcome_code,
                        event.note AS current_note,
                        event.recorded_at AS current_recorded_at,
                        NULL AS latest_outcome_event_id
                 FROM care_plan_commitment_task_links link
                 JOIN care_plan_commitments commitment
                   ON commitment.commitment_id=link.commitment_id
                 JOIN followup_tasks task ON task.id=link.task_id
                 JOIN patient_links patient ON patient.id=commitment.patient_link_id
                 JOIN care_plan_commitment_events event
                   ON event.commitment_id=commitment.commitment_id
                  AND event.id=(
                      SELECT head.id FROM care_plan_commitment_events head
                      WHERE head.commitment_id=commitment.commitment_id
                      ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                  )
                 WHERE 1=1"""
        params: list = []
        if patient_link_id is not None:
            sql += " AND commitment.patient_link_id=?"
            params.append(int(patient_link_id))
        if query:
            like = f"%{str(query).strip()}%"
            sql += " AND (patient.full_name LIKE ? OR COALESCE(patient.national_id,'') LIKE ? OR COALESCE(patient.phone_number,'') LIKE ?)"
            params.extend((like, like, like))
        if not include_terminal:
            sql += " AND event.status IN ('OPEN','IN_PROGRESS','SCHEDULED')"
        sql += " ORDER BY event.due_at,link.task_id DESC"
        return [dict(row) for row in self._db().execute(sql, params).fetchall()]

    def is_plan_task(self, task_id: int) -> bool:
        return self.commitment_for_task(int(task_id)) is not None
'''
if method.strip() not in repo:
    marker = "\n\n__all__ = ["
    if marker not in repo:
        raise AssertionError("A10 commitment repository export anchor missing")
    repo = repo.replace(marker, "\n" + method + marker, 1)
    repo_path.write_text(repo, encoding="utf-8")

# Administrative mutations reject both governed task kinds.
replace_once(
    "specialist_clinic/src/adapters/sqlite/followups_repo.py",
    "AND source_engine='clinical_v2' LIMIT 1",
    "AND source_engine IN ('clinical_v2','encounter_plan') LIMIT 1",
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/followups_repo.py",
    '"clinical tasks require append-only care-loop transitions"',
    '"governed follow-up tasks require append-only lifecycle transitions"',
)
# Exclude governed tasks from mutable administrative projection.
followups = path("specialist_clinic/src/adapters/sqlite/followups_repo.py")
text = followups.read_text(encoding="utf-8")
text = text.replace(
    "COALESCE(f.source_engine,'')<>'clinical_v2'",
    "COALESCE(f.source_engine,'') NOT IN ('clinical_v2','encounter_plan')",
)
text = text.replace(
    "COALESCE(source_engine,'')<>'clinical_v2'",
    "COALESCE(source_engine,'') NOT IN ('clinical_v2','encounter_plan')",
)
# list_open
old = '''        rows.extend(
            ClinicalCareLoopRepository().list_current(
                reason=reason,
                include_terminal=False,
            )
        )
        return self._sort_open(rows)
'''
new = '''        rows.extend(
            ClinicalCareLoopRepository().list_current(
                reason=reason,
                include_terminal=False,
            )
        )
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        plan_rows = EncounterPlanCommitmentRepository().list_current(
            include_terminal=False
        )
        if reason:
            plan_rows = [row for row in plan_rows if row.get("reason") == reason]
        rows.extend(plan_rows)
        return self._sort_open(rows)
'''
if new not in text:
    if old not in text:
        raise AssertionError("A10 list_open anchor missing")
    text = text.replace(old, new, 1)
# search_open
old = '''        rows.extend(
            ClinicalCareLoopRepository().list_current(
                query=query,
                include_terminal=False,
            )
        )
        return self._sort_open(rows)
'''
new = '''        rows.extend(
            ClinicalCareLoopRepository().list_current(
                query=query,
                include_terminal=False,
            )
        )
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        rows.extend(
            EncounterPlanCommitmentRepository().list_current(
                query=query,
                include_terminal=False,
            )
        )
        return self._sort_open(rows)
'''
if new not in text:
    if old not in text:
        raise AssertionError("A10 search_open anchor missing")
    text = text.replace(old, new, 1)
# list_for_patient
old = '''        clinical = ClinicalCareLoopRepository().list_current(
            patient_link_id=patient_link_id,
            include_terminal=True,
        )
        for row in clinical:
'''
new = '''        clinical = ClinicalCareLoopRepository().list_current(
            patient_link_id=patient_link_id,
            include_terminal=True,
        )
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        plan = EncounterPlanCommitmentRepository().list_current(
            patient_link_id=patient_link_id,
            include_terminal=True,
        )
        for row in plan:
            row["status"] = (
                "open" if row["current_status"] in {"OPEN","IN_PROGRESS","SCHEDULED"}
                else "done" if row["current_status"] == "COMPLETED"
                else "dismissed"
            )
        for row in clinical:
'''
if new not in text:
    if old not in text:
        raise AssertionError("A10 patient projection anchor missing")
    text = text.replace(old, new, 1)
text = text.replace(
    "return sorted([*admin, *clinical], key=lambda row: -int(row[\"id\"]))",
    "return sorted([*admin, *clinical, *plan], key=lambda row: -int(row[\"id\"]))",
)
# counts add plan rows.
old = '''        for row in ClinicalCareLoopRepository().list_current(
            include_terminal=False
        ):
            reason = row.get("reason")
            counts[reason] = counts.get(reason, 0) + 1
        return counts
'''
new = '''        for row in ClinicalCareLoopRepository().list_current(
            include_terminal=False
        ):
            reason = row.get("reason")
            counts[reason] = counts.get(reason, 0) + 1
        from src.adapters.sqlite.encounter_plan_commitment_repo import (
            EncounterPlanCommitmentRepository,
        )
        for row in EncounterPlanCommitmentRepository().list_current(
            include_terminal=False
        ):
            reason = row.get("reason")
            counts[reason] = counts.get(reason, 0) + 1
        return counts
'''
if new not in text:
    if old not in text:
        raise AssertionError("A10 counts anchor missing")
    text = text.replace(old, new, 1)
followups.write_text(text, encoding="utf-8")

# Unified projection attaches the immutable commitment root.
replace_once(
    "specialist_clinic/src/services/followup_projection_service.py",
    '''            row["task_contract"] = (
                contracts.get(int(row["id"]))
                if row.get("source_engine") == "clinical_v2"
                else None
            )
''',
    '''            row["task_contract"] = (
                contracts.get(int(row["id"]))
                if row.get("source_engine") == "clinical_v2"
                else None
            )
            row["plan_commitment"] = (
                {
                    "commitment_id": row.get("commitment_id"),
                    "document_event_id": row.get("document_event_id"),
                    "encounter_id": row.get("encounter_id"),
                    "journey_id": row.get("journey_id"),
                    "commitment_type": row.get("commitment_type"),
                    "instruction": row.get("instruction"),
                    "original_due_at": row.get("original_due_at"),
                }
                if row.get("source_engine") == "encounter_plan"
                else None
            )
''',
)

# User-facing reason vocabulary.
reason_file = path("specialist_clinic/src/services/followup_service.py")
reason_text = reason_file.read_text(encoding="utf-8")
if '"encounter_plan": "تعهد طرح ویزیت"' not in reason_text:
    anchor = 'REASON_LABELS = {'
    index = reason_text.find(anchor)
    if index < 0:
        raise AssertionError("A10 reason label anchor missing")
    insert_at = reason_text.find("\n", index) + 1
    reason_text = reason_text[:insert_at] + '    "encounter_plan": "تعهد طرح ویزیت",\n' + reason_text[insert_at:]
    reason_file.write_text(reason_text, encoding="utf-8")

Path(__file__).unlink()
