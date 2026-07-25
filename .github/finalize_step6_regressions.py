from pathlib import Path


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
replace_once(
    "specialist_clinic/src/adapters/sqlite/clinical_followup_repo.py",
    '''                          root.patient_link_id=?
                          AND root.clinical_semantic_key=?
                          AND root.clinical_context_hash=?
                          AND COALESCE(root.clinical_due_period,'')=COALESCE(?, '')
                          AND EXISTS (
''',
    '''                          root.patient_link_id=?
                          AND root.clinical_semantic_key=?
                          AND EXISTS (
''',
)
replace_once(
    "specialist_clinic/src/adapters/sqlite/clinical_followup_repo.py",
    '''                task["patient_link_id"],
                task["clinical_semantic_key"],
                task["clinical_context_hash"],
                task.get("due_period"),
''',
    '''                task["patient_link_id"],
                task["clinical_semantic_key"],
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

# Keep the UI acceptance test diagnostic: a future blocked report must expose its
# exact failed checks instead of only printing a huge HTML representation.
replace_once(
    "specialist_clinic/tests/test_clinical_engine_v2_manager_ui.py",
    '''    html = compared.get_data(as_text=True)
    assert "آزمون هر ۱۰ بیمار با موفقیت انجام شد" in html
''',
    '''    html = compared.get_data(as_text=True)
    with manager_ui_app.app_context():
        diagnostic_report = ClinicalEngineActivationRepository().get_json("last_report")
    assert "آزمون هر ۱۰ بیمار با موفقیت انجام شد" in html, diagnostic_report
''',
)
