from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old in text:
        print(f"applying regression patch: {path} :: {old.splitlines()[0].strip()}")
        text = text.replace(old, new, 1)
    elif new not in text:
        raise AssertionError(
            f"regression patch point missing in {path}: {old[:180]!r}"
        )
    else:
        print(f"regression patch already present: {path}")
    target.write_text(text, encoding="utf-8")


# An existing open task blocks duplicate semantic work even when a later run has
# new evidence, a new due date or another evaluation context. Recurrence is allowed
# only after the current task reaches a terminal event.
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

# SILENT -> ACTIVE is a governed mutation covered by the audit checkpoint. Reissue
# the selected-rollout seal after promotion so the unchanged package/report and the
# newly ACTIVE ruleset are bound to a fresh checkpoint before global activation.
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

# Keep the UI acceptance test diagnostic compact and limited to the exact positive
# controls; this is synthetic release evidence and contains no real patient data.
replace_once(
    "specialist_clinic/tests/test_clinical_engine_v2_manager_ui.py",
    '''    html = compared.get_data(as_text=True)
    assert "آزمون هر ۱۰ بیمار با موفقیت انجام شد" in html
''',
    '''    html = compared.get_data(as_text=True)
    with manager_ui_app.app_context():
        diagnostic_report = ClinicalEngineActivationRepository().get_json("last_report")
    diagnostic = {
        "status": diagnostic_report.get("status"),
        "failed_checks": [
            key for key, value in (diagnostic_report.get("checks") or {}).items()
            if not value
        ],
        "failure_codes": [
            item.get("code") for item in (diagnostic_report.get("failures") or [])
        ],
        "positive_controls": {
            row.get("national_id"): {
                "run_status": row.get("v2_run_status"),
                "rule_codes": row.get("v2_rule_codes"),
                "errors": row.get("v2_errors"),
            }
            for row in (diagnostic_report.get("patients") or [])
            if row.get("national_id") in {"TEST0008", "TEST0010"}
        },
    }
    assert "آزمون هر ۱۰ بیمار با موفقیت انجام شد" in html, diagnostic
''',
)
