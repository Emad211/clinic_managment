from datetime import datetime
import sqlite3

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.api.auth import login_required
from src.common.utils import iran_now, jalali_to_gregorian_str
from src.security.permissions import Permission, has_permission, permission_required
from src.services.activity_logger import log_activity
from src.services.appointment_service import AppointmentService
from src.services.clinical_alert_service import ClinicalAlertService
from src.services.clinical_care_loop_service import (
    ClinicalCareLoopConflict,
    ClinicalCareLoopService,
    ClinicalCareLoopValidationError,
    DISPOSITION_LABELS,
    OUTCOME_LABELS,
    STATUS_LABELS,
)
from src.services.followup_service import FollowupService, REASON_LABELS
from src.services.followup_booking_service import (
    FollowupBookingError,
    FollowupBookingService,
)
from src.services.followup_projection_service import FollowupProjectionService
from src.services.encounter_plan_commitment_service import (
    COMMITMENT_LABELS as PLAN_COMMITMENT_LABELS,
    EVIDENCE_LABELS as PLAN_EVIDENCE_LABELS,
    OUTCOME_LABELS as PLAN_OUTCOME_LABELS,
    EncounterPlanCommitmentConflict,
    EncounterPlanCommitmentService,
    EncounterPlanCommitmentValidationError,
)
from src.services.followup_contact_service import (
    CHANNEL_LABELS as CONTACT_CHANNEL_LABELS,
    OUTCOME_LABELS as CONTACT_OUTCOME_LABELS,
    FollowupContactConflict,
    FollowupContactService,
    FollowupContactValidationError,
)


bp = Blueprint("followups", __name__, url_prefix="/followups")


def _task_source(task_id: int) -> str:
    row = get_db().execute(
        "SELECT COALESCE(source_engine,'') AS source_engine "
        "FROM followup_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    return str(row["source_engine"] or "admin") if row else "missing"


def _clinical_task(task_id: int) -> bool:
    return _task_source(task_id) == "clinical_v2"


def _observed_at(raw: str | None):
    value = (raw or "").strip()
    if not value:
        return None
    gregorian = jalali_to_gregorian_str(value)
    return f"{gregorian} 12:00:00" if gregorian else value


@bp.route("/")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def worklist():
    reason = request.args.get("reason") or None
    q = (request.args.get("q") or "").strip()
    repo = FollowupRepository()
    projection = FollowupProjectionService(tasks=repo)
    tasks = projection.open_tasks(query=q or None, reason=reason)
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
        contact_channel_labels=CONTACT_CHANNEL_LABELS,
        contact_outcome_labels=CONTACT_OUTCOME_LABELS,
        plan_commitment_labels=PLAN_COMMITMENT_LABELS,
        plan_evidence_labels=PLAN_EVIDENCE_LABELS,
        plan_outcome_labels=PLAN_OUTCOME_LABELS,
        active_reason=reason,
        q=q,
        hub_pending=EngagementRepository().count_pending(),
        alert_pending=(
            len(ClinicalAlertService().list_open())
            if has_permission(Permission.CLINICAL_ALERT_VIEW)
            else 0
        ),
        active_page="sms",
    )


@bp.route("/generate", methods=["POST"])
@permission_required(Permission.CLINICAL_TASK_TRANSITION)
def generate():
    """Synchronize due worklist routes through the canonical engagement engine."""
    result = FollowupService().generate()
    total = result["worklist"]
    alerts_created = int(result.get("clinical_alerts") or 0)
    flash(
        f"{total} پیگیری و {alerts_created} هشدار بالینی جدید ساخته شد"
        if total or alerts_created
        else "پیگیری یا هشدار جدیدی نبود",
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


@bp.post("/<int:task_id>/contact")
@permission_required(Permission.FOLLOWUP_CONTACT_RECORD)
def record_contact(task_id: int):
    raw_next = (request.form.get("next_contact_at") or "").strip()
    next_contact = None
    if raw_next:
        parsed = jalali_to_gregorian_str(raw_next) or raw_next
        next_contact = f"{parsed} 09:00:00" if len(parsed) == 10 else parsed
    try:
        event = FollowupContactService().record(
            task_id=task_id,
            channel=request.form.get("channel") or "PHONE",
            outcome=request.form.get("outcome") or "OTHER",
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=request.form.get("idempotency_key") or "",
            note=request.form.get("note"),
            next_contact_at=next_contact,
        )
    except (LookupError, ValueError, FollowupContactConflict,
            FollowupContactValidationError, sqlite3.IntegrityError) as exc:
        flash(f"ثبت تماس انجام نشد: {exc}", "error")
    else:
        log_activity(
            "followup_contact_record",
            f"task={task_id} contact={event['id']} outcome={event['outcome']}",
            patient_link_id=int(event["patient_link_id"]),
        )
        flash("نتیجهٔ تماس به‌صورت افزایشی ثبت شد.", "success")
    return redirect(request.referrer or url_for("followups.worklist"))


@bp.route("/<int:task_id>/resolve", methods=["POST"])
@login_required
def resolve(task_id):
    source = _task_source(task_id)
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
    status = request.form.get("status", "done")
    call_log = request.form.get("call_log") or None
    FollowupRepository().resolve(task_id, status, call_log)
    log_activity("followup_resolve", f"بستن پیگیری اداری ({status})")
    return redirect(request.referrer or url_for("followups.worklist"))


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
        patient = get_db().execute(
            "SELECT patient_link_id FROM followup_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        log_activity(
            "encounter_plan_commitment_transition",
            f"task={task_id} event={event['event_type']} status={event['status']}",
            patient_link_id=int(patient["patient_link_id"]),
        )
        flash("رویداد تعهد طرح به‌صورت افزایشی ثبت شد.", "success")
    return redirect(request.referrer or url_for("followups.worklist"))


@bp.post("/<int:task_id>/clinical/outcome")
@permission_required(Permission.CLINICAL_OUTCOME_RECORD)
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
    except (
        LookupError,
        ClinicalCareLoopValidationError,
        ValueError,
        sqlite3.IntegrityError,
    ) as exc:
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
@permission_required(Permission.CLINICAL_TASK_TRANSITION)
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
    except (
        LookupError,
        ClinicalCareLoopValidationError,
        ValueError,
        sqlite3.IntegrityError,
    ) as exc:
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
    """Atomically record BOOKED without falsely completing any follow-up."""
    scheduled_date = jalali_to_gregorian_str(
        request.form.get("scheduled_date", "")
    )
    if not scheduled_date:
        flash("تاریخ ویزیت الزامی است", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
    scheduled_time = (request.form.get("scheduled_time") or "09:00").strip()
    scheduled_at = f"{scheduled_date} {scheduled_time}:00"
    task_ids = sorted(
        {int(value) for value in request.form.getlist("task_ids") if str(value).isdigit()}
    )
    if not task_ids:
        flash("پیگیری بازی برای این بیمار انتخاب نشده است", "error")
        return redirect(request.referrer or url_for("followups.worklist"))

    marks = ",".join("?" for _ in task_ids)
    rows = get_db().execute(
        f"SELECT id, source_engine FROM followup_tasks WHERE id IN ({marks})",
        task_ids,
    ).fetchall()
    if len(rows) != len(task_ids):
        flash("یکی از پیگیری‌ها دیگر وجود ندارد.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
    if any(row["source_engine"] == "clinical_v2" for row in rows) and not has_permission(
        Permission.CLINICAL_TASK_TRANSITION
    ):
        flash("مجوز زمان‌بندی پیگیری بالینی ثبت نشده است.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
    if any(row["source_engine"] == "encounter_plan" for row in rows) and not has_permission(
        Permission.FOLLOWUP_PLAN_TRANSITION
    ):
        flash("مجوز زمان‌بندی تعهد طرح Encounter ثبت نشده است.", "error")
        return redirect(request.referrer or url_for("followups.worklist"))

    try:
        result = FollowupBookingService().book(
            patient_link_id=pid,
            task_ids=task_ids,
            scheduled_at=scheduled_at,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            idempotency_key=request.form.get("booking_idempotency_key") or "",
        )
    except (FollowupBookingError, ValueError, LookupError, sqlite3.IntegrityError) as exc:
        flash(f"رزرو نوبت انجام نشد: {exc}", "error")
    else:
        log_activity(
            "followup_to_visit",
            (
                f"appointment={result['appointment_id']} "
                f"admin_booked={result['admin_booked']} "
                f"clinical_scheduled={result['clinical_scheduled']} "
                f"duplicate={result['duplicate']} patient={pid}"
            ),
            patient_link_id=pid,
        )
        flash(
            (
                f"نوبت #{result['appointment_id']} ثبت شد؛ "
                "پیگیری‌ها تا حضور یا ثبت نتیجه باز می‌مانند."
            ),
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
