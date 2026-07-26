from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A10 lifecycle target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A10 lifecycle anchor missing in {relative}: {old[:220]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Imports and labels.
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''from src.services.followup_projection_service import FollowupProjectionService
''',
    '''from src.services.followup_projection_service import FollowupProjectionService
from src.services.encounter_plan_commitment_service import (
    COMMITMENT_LABELS as PLAN_COMMITMENT_LABELS,
    EVIDENCE_LABELS as PLAN_EVIDENCE_LABELS,
    OUTCOME_LABELS as PLAN_OUTCOME_LABELS,
    EncounterPlanCommitmentConflict,
    EncounterPlanCommitmentService,
    EncounterPlanCommitmentValidationError,
)
''',
)
# Add task source helper.
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''def _clinical_task(task_id: int) -> bool:
    row = get_db().execute(
        "SELECT source_engine FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    return bool(row and row["source_engine"] == "clinical_v2")
''',
    '''def _task_source(task_id: int) -> str:
    row = get_db().execute(
        "SELECT COALESCE(source_engine,'') AS source_engine "
        "FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    return str(row["source_engine"] or "admin") if row else "missing"


def _clinical_task(task_id: int) -> bool:
    return _task_source(task_id) == "clinical_v2"
''',
)
# Worklist status normalization for Plan tasks.
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''        if task.get("source_engine") == "clinical_v2":
            task["status_fa"] = STATUS_LABELS.get(
                task.get("current_status"), task.get("current_status")
            )
            due = task.get("current_due_at") or task.get("due_date")
''',
    '''        if task.get("source_engine") == "clinical_v2":
            task["status_fa"] = STATUS_LABELS.get(
                task.get("current_status"), task.get("current_status")
            )
            due = task.get("current_due_at") or task.get("due_date")
        elif task.get("source_engine") == "encounter_plan":
            task["status_fa"] = {
                "OPEN": "باز", "IN_PROGRESS": "در حال انجام",
                "SCHEDULED": "زمان‌بندی‌شده", "COMPLETED": "تکمیل‌شده",
                "CANCELLED": "لغوشده", "ENTERED_IN_ERROR": "ثبت اشتباه",
            }.get(task.get("current_status"), task.get("current_status"))
            due = task.get("current_due_at") or task.get("due_date")
        else:
            due = task.get("current_due_at") or task.get("due_date")
        if task.get("source_engine") in {"clinical_v2", "encounter_plan"}:
''',
)
# Above replacement leaves duplicated due block body intentionally shared; fix indentation token.
followups = target("specialist_clinic/src/api/followups.py")
text = followups.read_text(encoding="utf-8")
text = text.replace(
    '''        if task.get("source_engine") in {"clinical_v2", "encounter_plan"}:
            try:
''',
    '''        if task.get("source_engine") in {"clinical_v2", "encounter_plan"}:
            try:
''',
)
# Template labels.
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''        contact_outcome_labels=CONTACT_OUTCOME_LABELS,
        active_reason=reason,
''',
    '''        contact_outcome_labels=CONTACT_OUTCOME_LABELS,
        plan_commitment_labels=PLAN_COMMITMENT_LABELS,
        plan_evidence_labels=PLAN_EVIDENCE_LABELS,
        plan_outcome_labels=PLAN_OUTCOME_LABELS,
        active_reason=reason,
''',
)
# Resolve guard.
replace_once(
    "specialist_clinic/src/api/followups.py",
    '''    if _clinical_task(task_id):
        flash(
            "پیگیری بالینی فقط از مسیر lifecycle و با شواهد outcome بسته می‌شود.",
            "error",
        )
        return redirect(request.referrer or url_for("followups.worklist"))
''',
    '''    source = _task_source(task_id)
    if source == "clinical_v2":
        flash(
            "پیگیری بالینی فقط از مسیر lifecycle و با شواهد outcome بسته می‌شود.",
            "error",
        )
        return redirect(request.referrer or url_for("followups.worklist"))
    if source == "encounter_plan":
        flash(
            "تعهد طرح Encounter فقط از مسیر lifecycle و با شاهد معتبر بسته می‌شود.",
            "error",
        )
        return redirect(request.referrer or url_for("followups.worklist"))
''',
)
# Add Plan transition route before clinical outcome route.
route = '''

@bp.post("/<int:task_id>/plan/transition")
@permission_required(Permission.FOLLOWUP_PLAN_TRANSITION)
def plan_transition(task_id: int):
    transition = str(request.form.get("transition") or "").strip().lower()
    due_at = None
    raw_due = str(request.form.get("due_at") or "").strip()
    if raw_due:
        parsed = jalali_to_gregorian_str(raw_due) or raw_due
        due_time = str(request.form.get("due_time") or "09:00").strip()
        due_at = f"{parsed} {due_time}:00" if len(parsed) == 10 else parsed
    try:
        event = EncounterPlanCommitmentService().transition(
            task_id=task_id,
            transition=transition,
            expected_current_event_id=int(
                request.form.get("expected_current_event_id") or 0
            ),
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=request.form.get("idempotency_key") or "",
            due_at=due_at,
            assigned_to=request.form.get("assigned_to"),
            appointment_id=request.form.get("appointment_id", type=int),
            evidence_type=request.form.get("evidence_type"),
            evidence_ref=request.form.get("evidence_ref"),
            outcome_code=request.form.get("outcome_code"),
            note=request.form.get("note"),
        )
    except EncounterPlanCommitmentConflict:
        flash("تعهد هم‌زمان تغییر کرده است؛ صفحه را تازه کنید.", "error")
    except (
        LookupError,
        ValueError,
        EncounterPlanCommitmentValidationError,
        sqlite3.IntegrityError,
    ) as exc:
        flash(f"تغییر تعهد ثبت نشد: {exc}", "error")
    else:
        log_activity(
            "encounter_plan_commitment_transition",
            f"task={task_id} event={event['event_type']} status={event['status']}",
            patient_link_id=int(event["patient_link_id"]),
        )
        flash("رویداد تعهد طرح به‌صورت افزایشی ثبت شد.", "success")
    return redirect(request.referrer or url_for("followups.worklist"))
'''
text = followups.read_text(encoding="utf-8")
marker = '\n\n@bp.post("/<int:task_id>/clinical/outcome")\n'
if route.strip() not in text:
    if marker not in text:
        raise AssertionError("A10 plan route insertion anchor missing")
    text = text.replace(marker, route + marker, 1)
    followups.write_text(text, encoding="utf-8")

Path(__file__).unlink()
