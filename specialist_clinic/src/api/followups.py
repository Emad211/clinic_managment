from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.api.auth import login_required, manager_required
from src.common.utils import iran_now, jalali_to_gregorian_str
from src.services.activity_logger import log_activity
from src.services.appointment_service import AppointmentService
from src.services.clinical_care_loop_service import (
    ClinicalCareLoopConflict,
    ClinicalCareLoopService,
    ClinicalCareLoopValidationError,
    DISPOSITION_LABELS,
    OUTCOME_LABELS,
    STATUS_LABELS,
)
from src.services.followup_service import FollowupService, REASON_LABELS


bp = Blueprint("followups", __name__, url_prefix="/followups")


def _clinical_task(task_id: int) -> bool:
    row = get_db().execute(
        "SELECT source_engine FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    return bool(row and row["source_engine"] == "clinical_v2")


def _observed_at(raw: str | None):
    value = (raw or "").strip()
    if not value:
        return None
    gregorian = jalali_to_gregorian_str(value)
    return f"{gregorian} 12:00:00" if gregorian else value


@bp.route("/")
@login_required
def worklist():
    reason = request.args.get("reason") or None
    q = (request.args.get("q") or "").strip()
    repo = FollowupRepository()
    tasks = repo.search_open(q) if q else repo.list_open(reason)
    today = iran_now().date()
    for task in tasks:
        task["reason_fa"] = REASON_LABELS.get(
            task["reason"], task["reason"]
        )
        if task.get("source_engine") == "clinical_v2":
            task["status_fa"] = STATUS_LABELS.get(
                task.get("current_status"), task.get("current_status")
            )
            due = task.get("current_due_at") or task.get("due_date")
            try:
                due_date = datetime.fromisoformat(str(due)).date() if due else None
            except ValueError:
                due_date = None
            task["overdue_days"] = (
                max((today - due_date).days, 0) if due_date else 0
            )
            task["is_overdue"] = bool(due_date and due_date < today)

    groups = {}
    for task in tasks:
        pid = task["patient_link_id"]
        group = groups.get(pid)
        if group is None:
            group = {
                "patient_link_id": pid,
                "patient_name": task.get("patient_name"),
                "phone_number": task.get("phone_number"),
                "national_id": task.get("national_id"),
                "open_count": 0,
                "next_due": None,
                "tasks": [],
            }
            groups[pid] = group
        group["open_count"] += 1
        current_due = task.get("current_due_at") or task.get("due_date")
        group["tasks"].append(
            {
                **task,
                "current_due": current_due,
            }
        )
        if current_due and (
            group["next_due"] is None or current_due < group["next_due"]
        ):
            group["next_due"] = current_due

    return render_template(
        "followups/worklist.html",
        tasks=tasks,
        patient_groups=list(groups.values()),
        counts=repo.counts_by_reason(),
        reason_labels=REASON_LABELS,
        status_labels=STATUS_LABELS,
        outcome_labels=OUTCOME_LABELS,
        disposition_labels=DISPOSITION_LABELS,
        active_reason=reason,
        q=q,
        hub_pending=EngagementRepository().count_pending(),
        active_page="sms",
    )


@bp.route("/generate", methods=["POST"])
@login_required
def generate():
    """Synchronize due worklist routes through the canonical engagement engine."""
    result = FollowupService().generate()
    total = result["worklist"]
    flash(
        f"{total} پیگیریِ جدید ساخته شد"
        if total
        else "پیگیریِ جدیدِ سررسیده‌ای نبود",
        "success",
    )
    if result["issues"]:
        flash(
            f"{len(result['issues'])} مسیر بالینی به علت خطا یا دادهٔ ناکافی task نساخت.",
            "warning",
        )
    log_activity(
        "followup_generate",
        f"همگام‌سازی ورک‌لیست؛ {total} پیگیری جدید",
    )
    return redirect(url_for("followups.worklist"))


@bp.route("/<int:task_id>/resolve", methods=["POST"])
@login_required
def resolve(task_id):
    if _clinical_task(task_id):
        flash(
            "پیگیری بالینی فقط از مسیر lifecycle و با شواهد outcome بسته می‌شود.",
            "error",
        )
        return redirect(request.referrer or url_for("followups.worklist"))
    status = request.form.get("status", "done")
    call_log = request.form.get("call_log") or None
    FollowupRepository().resolve(task_id, status, call_log)
    log_activity("followup_resolve", f"بستن پیگیری اداری ({status})")
    return redirect(request.referrer or url_for("followups.worklist"))


@bp.post("/<int:task_id>/clinical/outcome")
@manager_required
def clinical_outcome(task_id: int):
    try:
        event = ClinicalCareLoopService().record_outcome(
            task_id,
            outcome_type=request.form.get("outcome_type") or "OTHER",
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            fact_key=request.form.get("fact_key"),
            value=request.form.get("value"),
            unit=request.form.get("unit"),
            verification=request.form.get("verification") or "CONFIRMED",
            observed_at=_observed_at(request.form.get("observed_at")),
            source_system="clinician",
            note=request.form.get("note"),
        )
    except (LookupError, ClinicalCareLoopValidationError, ValueError) as exc:
        flash(f"ثبت outcome انجام نشد: {exc}", "error")
    else:
        log_activity(
            "clinical_task_outcome",
            f"outcome={event['id']} task={task_id}",
            patient_link_id=get_db().execute(
                "SELECT patient_link_id FROM followup_tasks WHERE id=?",
                (task_id,),
            ).fetchone()["patient_link_id"],
        )
        flash("شاهد نتیجه به‌صورت افزایشی ثبت شد.", "success")
    return redirect(request.referrer or url_for("followups.worklist"))


@bp.post("/<int:task_id>/clinical/transition")
@manager_required
def clinical_transition(task_id: int):
    due = request.form.get("due_at")
    if due:
        due = jalali_to_gregorian_str(due) or due
    try:
        event = ClinicalCareLoopService().transition(
            task_id,
            transition=request.form.get("transition") or "",
            expected_current_event_id=int(
                request.form.get("expected_current_event_id") or 0
            ),
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            assigned_to=request.form.get("assigned_to"),
            appointment_id=request.form.get("appointment_id", type=int),
            due_at=due,
            disposition_code=request.form.get("disposition_code"),
            outcome_event_id=request.form.get("outcome_event_id", type=int),
            note=request.form.get("note"),
        )
    except ClinicalCareLoopConflict:
        flash("وضعیت پیگیری هم‌زمان تغییر کرده است؛ صفحه را تازه کنید.", "error")
    except (LookupError, ClinicalCareLoopValidationError, ValueError) as exc:
        flash(f"تغییر lifecycle ثبت نشد: {exc}", "error")
    else:
        log_activity(
            "clinical_task_transition",
            f"task={task_id} event={event['event_type']} status={event['status']}",
            patient_link_id=get_db().execute(
                "SELECT patient_link_id FROM followup_tasks WHERE id=?",
                (task_id,),
            ).fetchone()["patient_link_id"],
        )
        flash("رویداد lifecycle پیگیری بالینی ثبت شد.", "success")
    return redirect(request.referrer or url_for("followups.worklist"))


@bp.route("/patient/<int:pid>/to-visit", methods=["POST"])
@login_required
def patient_to_visit(pid):
    """Create one appointment; admin tasks close, clinical tasks become SCHEDULED."""
    scheduled_date = jalali_to_gregorian_str(
        request.form.get("scheduled_date", "")
    )
    if not scheduled_date:
        flash("تاریخ ویزیت الزامی است", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
    scheduled_time = (request.form.get("scheduled_time") or "09:00").strip()
    scheduled_at = f"{scheduled_date} {scheduled_time}:00"

    repo = FollowupRepository()
    available = {
        int(task["id"]): task
        for task in repo.list_for_patient(pid)
        if task.get("status") == "open"
    }
    posted = request.form.getlist("task_ids", type=int)
    task_ids = [task_id for task_id in posted if task_id in available]
    if not task_ids:
        flash("پیگیریِ بازی برای این بیمار نیست", "error")
        return redirect(request.referrer or url_for("followups.worklist"))

    clinical_ids = [
        task_id
        for task_id in task_ids
        if available[task_id].get("source_engine") == "clinical_v2"
    ]
    if clinical_ids and g.user["role"] != "manager":
        flash("زمان‌بندی پیگیری بالینی فقط برای مدیر مجاز است.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))

    appointment_id = AppointmentService().schedule(
        pid,
        scheduled_at=scheduled_at,
        appt_type="visit",
        notes="ویزیت ناشی از ورک‌لیست؛ پیگیری بالینی تا ثبت outcome باز می‌ماند",
        created_by=g.user["username"],
    )
    admin_ids = [task_id for task_id in task_ids if task_id not in clinical_ids]
    if admin_ids:
        repo.assign_appointment_bulk(admin_ids, appointment_id)
        for task_id in admin_ids:
            repo.resolve(task_id, "done")

    scheduled = 0
    care = ClinicalCareLoopService()
    for task_id in clinical_ids:
        task = care.current(task_id)
        try:
            care.transition(
                task_id,
                transition="schedule",
                expected_current_event_id=task["current_event_id"],
                actor_username=g.user["username"],
                actor_user_id=int(g.user["id"]),
                appointment_id=appointment_id,
                note="از ورک‌لیست به ویزیت زمان‌بندی شد",
            )
            scheduled += 1
        except ClinicalCareLoopConflict:
            flash(
                f"پیگیری {task_id} هم‌زمان تغییر کرد و زمان‌بندی نشد.",
                "warning",
            )

    log_activity(
        "followup_to_visit",
        f"admin_closed={len(admin_ids)} clinical_scheduled={scheduled} patient={pid}",
        patient_link_id=pid,
    )
    flash(
        f"{len(admin_ids)} پیگیری اداری بسته و {scheduled} پیگیری بالینی زمان‌بندی شد.",
        "success",
    )
    return redirect(url_for("followups.worklist"))


@bp.route("/add", methods=["POST"])
@login_required
def add_manual():
    pid = request.form.get("patient_link_id", type=int)
    if pid:
        FollowupRepository().create(
            pid,
            reason="manual",
            detail=request.form.get("detail") or None,
            due_date=jalali_to_gregorian_str(
                request.form.get("due_date", "")
            ),
            assigned_to=g.user["username"],
        )
        flash("پیگیری ثبت شد", "success")
    return redirect(request.referrer or url_for("followups.worklist"))
