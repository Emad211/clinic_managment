from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise AssertionError(
            f"regression patch point missing in {path}: {old[:180]!r}"
        )
    target.write_text(text, encoding="utf-8")


# An existing open task blocks duplicate semantic work independent of a later run's
# evidence, context or due date. Recurrence is allowed only after a terminal event.
followup = Path("specialist_clinic/src/adapters/sqlite/clinical_followup_repo.py")
text = followup.read_text(encoding="utf-8")
query_pattern = re.compile(
    r"(?P<prefix>\s+root\.patient_link_id=\?\n"
    r"\s+AND root\.clinical_semantic_key=\?)\n"
    r"\s+AND root\.clinical_context_hash=\?\n"
    r"\s+AND COALESCE\(root\.clinical_due_period,''\)=COALESCE\(\?, ''\)"
)
text, query_count = query_pattern.subn(r"\g<prefix>", text, count=1)
params_pattern = re.compile(
    r'(?P<prefix>\s+task\["patient_link_id"\],\n'
    r'\s+task\["clinical_semantic_key"\],)\n'
    r'\s+task\["clinical_context_hash"\],\n'
    r'\s+task\.get\("due_period"\),'
)
text, params_count = params_pattern.subn(r"\g<prefix>", text, count=1)
if query_count != 1 or params_count != 1:
    already = (
        "AND root.clinical_semantic_key=?\n"
        "                          AND EXISTS (" in text
        and 'task["clinical_semantic_key"],\n            )' in text
    )
    if not already:
        raise AssertionError(
            f"semantic-task dedupe patch failed query={query_count} params={params_count}"
        )
followup.write_text(text, encoding="utf-8")

# The recurrence regression must close the first task through the append-only event
# lifecycle. Mutating followup_tasks.status is a retired pre-step-5 shortcut.
replace_once(
    "specialist_clinic/tests/test_clinical_engine_v2_followups.py",
    '''    db.execute(
        """UPDATE followup_tasks
           SET status='done', resolved_at='2026-07-22 12:00:00'"""
    )
    db.commit()
''',
    '''    from src.services.clinical_care_loop_service import ClinicalCareLoopService

    first_task = db.execute(
        "SELECT id FROM followup_tasks ORDER BY id LIMIT 1"
    ).fetchone()
    care_loop = ClinicalCareLoopService()
    current = care_loop.current(int(first_task["id"]))
    care_loop.transition(
        int(first_task["id"]),
        transition="not_done",
        expected_current_event_id=int(current["current_event_id"]),
        actor_username="pytest-clinician",
        actor_user_id=None,
        disposition_code="NO_LONGER_NEEDED",
        note="First due period closed before recurrence.",
    )
''',
)

# SILENT -> ACTIVE mutates governed ruleset state. Reissue the selected seal so the
# unchanged package/report and the newly ACTIVE ruleset bind to a fresh checkpoint.
replace_once(
    "specialist_clinic/src/services/clinical_engine/activation.py",
    '''        self.rules.promote_silent_ruleset(
            ruleset_id,
            promoted_by=promoted_by,
        )
        log_activity(
''',
    '''        self.rules.promote_silent_ruleset(
            ruleset_id,
            promoted_by=promoted_by,
        )
        self.activate("on_selected", activated_by=promoted_by)
        log_activity(
''',
)

# Synthetic controls must carry stable source provenance before their immutable
# reconciliation event is recorded. A later generic provenance backfill must be a
# no-op, otherwise candidate-set hashes would truthfully invalidate the review.
replace_once(
    "specialist_clinic/src/adapters/sqlite/demo_cohort_repo.py",
    '''                """INSERT INTO patient_conditions
                   (patient_link_id, condition_id, stage, onset_date, notes,
                    diagnosed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    patient_id,
                    condition_id,
                    condition.get("stage"),
                    condition.get("onset"),
                    condition.get("notes"),
                    condition.get("onset") or now,
                ),
''',
    '''                """INSERT INTO patient_conditions
                   (patient_link_id, condition_id, stage, onset_date, notes,
                    diagnosed_at, source_system, source_record_id,
                    source_assertion, verification, recorded_by)
                   VALUES (?, ?, ?, ?, ?, ?, 'system', ?, 'PRESENT',
                           'CONFIRMED', ?)""",
                (
                    patient_id,
                    condition_id,
                    condition.get("stage"),
                    condition.get("onset"),
                    condition.get("notes"),
                    condition.get("onset") or now,
                    f"demo-condition:{patient_id}:{condition['code']}",
                    actor,
                ),
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/demo_cohort_repo.py",
    '''        for medication in patient["meds"]:
''',
    '''        for medication_index, medication in enumerate(patient["meds"], start=1):
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/demo_cohort_repo.py",
    '''                """INSERT INTO patient_medications
                   (patient_link_id, drug_name, dose, schedule, start_date,
                    refill_due_date, is_active, end_date, notes, drug_class,
                    drug_catalog_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    patient_id,
                    catalog["generic_fa"],
                    final_dose,
                    medication["schedule"],
                    medication["start"],
                    "2026-10-22",
                    0 if medication["stop"] else 1,
                    medication["stop"],
                    medication.get("notes"),
                    catalog["drug_class_key"],
                    int(catalog["id"]),
                ),
''',
    '''                """INSERT INTO patient_medications
                   (patient_link_id, drug_name, dose, schedule, start_date,
                    refill_due_date, is_active, end_date, notes, drug_class,
                    drug_catalog_id, source_system, source_record_id,
                    source_assertion, verification, recorded_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'system', ?,
                           'PRESENT', 'CONFIRMED', ?)""",
                (
                    patient_id,
                    catalog["generic_fa"],
                    final_dose,
                    medication["schedule"],
                    medication["start"],
                    "2026-10-22",
                    0 if medication["stop"] else 1,
                    medication["stop"],
                    medication.get("notes"),
                    catalog["drug_class_key"],
                    int(catalog["id"]),
                    f"demo-medication:{patient_id}:{medication_index}",
                    actor,
                ),
''',
)
