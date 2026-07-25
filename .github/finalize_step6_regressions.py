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

replace_once(
    "specialist_clinic/tests/test_clinical_engine_v2_manager_ui.py",
    '''    html = compared.get_data(as_text=True)
    assert "آزمون هر ۱۰ بیمار با موفقیت انجام شد" in html
''',
    '''    html = compared.get_data(as_text=True)
    with manager_ui_app.app_context():
        diagnostic_report = ClinicalEngineActivationRepository().get_json("last_report")
        from src.adapters.sqlite.clinical_reconciliation_repo import ClinicalReconciliationRepository
        from src.adapters.sqlite.core import get_db
        db = get_db()
        projections = {}
        for national_id in ("TEST0008", "TEST0010"):
            patient = db.execute(
                "SELECT id FROM patient_links WHERE national_id=?", (national_id,)
            ).fetchone()
            projections[national_id] = {}
            for collection_key in ("conditions", "medications"):
                projection = ClinicalReconciliationRepository().projection(
                    int(patient["id"]), collection_key, as_of_at="2026-07-22 08:00:00"
                )
                event = projection.reconciliation_event or {}
                projections[national_id][collection_key] = {
                    "state": projection.state,
                    "verification": projection.verification.value,
                    "warnings": list(projection.warnings),
                    "current_hash": projection.content_hash[:12],
                    "event_hash": str(event.get("content_hash") or "")[:12],
                    "current_count": projection.item_count,
                    "event_count": event.get("item_count"),
                    "current_conflict": projection.conflict_snapshot_hash[:12],
                    "event_conflict": str(event.get("conflict_snapshot_hash") or "")[:12],
                }
    diagnostic = {
        "failed_checks": [
            key for key, value in (diagnostic_report.get("checks") or {}).items()
            if not value
        ],
        "projections": projections,
    }
    if "آزمون هر ۱۰ بیمار با موفقیت انجام شد" not in html:
        raise AssertionError(diagnostic)
''',
)
