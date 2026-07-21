from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from src.api.auth import login_required
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.appointment_service import AppointmentService
from src.services.followup_service import FollowupService, REASON_LABELS
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str

bp = Blueprint("followups", __name__, url_prefix="/followups")


@bp.route("/")
@login_required
def worklist():
    reason = request.args.get("reason") or None
    q = (request.args.get("q") or "").strip()
    repo = FollowupRepository()
    # search overrides the reason filter; both preserve the due-date ordering
    tasks = repo.search_open(q) if q else repo.list_open(reason)
    for t in tasks:
        t['reason_fa'] = REASON_LABELS.get(t['reason'], t['reason'])

    # Group flat tasks BY patient, preserving the existing due-date ordering:
    # group order = order of first appearance (i.e. by each group's earliest due,
    # since tasks already arrive earliest-due-first).
    groups = {}
    for t in tasks:
        pid = t['patient_link_id']
        g_entry = groups.get(pid)
        if g_entry is None:
            g_entry = {
                'patient_link_id': pid,
                'patient_name': t.get('patient_name'),
                'phone_number': t.get('phone_number'),
                'national_id': t.get('national_id'),
                'open_count': 0,
                'next_due': None,
                'tasks': [],
            }
            groups[pid] = g_entry
        g_entry['open_count'] += 1
        g_entry['tasks'].append({
            'id': t['id'], 'reason': t['reason'], 'reason_fa': t['reason_fa'],
            'detail': t.get('detail'), 'due_date': t.get('due_date'),
            'fulfillment': t.get('fulfillment'),
        })
        # earliest non-null due_date for the group
        due = t.get('due_date')
        if due and (g_entry['next_due'] is None or due < g_entry['next_due']):
            g_entry['next_due'] = due
    patient_groups = list(groups.values())

    counts = repo.counts_by_reason()
    from src.adapters.sqlite.engagement_repo import EngagementRepository
    return render_template("followups/worklist.html", tasks=tasks,
                           patient_groups=patient_groups, counts=counts,
                           reason_labels=REASON_LABELS, active_reason=reason, q=q,
                           hub_pending=EngagementRepository().count_pending(),
                           active_page='sms')


@bp.route("/generate", methods=["POST"])
@login_required
def generate():
    """Synchronize due worklist routes through the canonical engagement engine."""
    created = FollowupService().generate()
    total = sum(created.values())
    flash(f"{total} پیگیریِ جدید ساخته شد" if total else "پیگیریِ جدیدِ سررسیده‌ای نبود", "success")
    log_activity("followup_generate", f"همگام‌سازی ورک‌لیست؛ {total} پیگیری جدید")
    return redirect(url_for("followups.worklist"))


@bp.route("/<int:task_id>/resolve", methods=["POST"])
@login_required
def resolve(task_id):
    status = request.form.get("status", "done")
    call_log = request.form.get("call_log") or None
    FollowupRepository().resolve(task_id, status, call_log)
    log_activity("followup_resolve", f"بستن پیگیری ({status})")
    return redirect(request.referrer or url_for("followups.worklist"))


@bp.route("/patient/<int:pid>/to-visit", methods=["POST"])
@login_required
def patient_to_visit(pid):
    """Close several of a patient's open follow-ups into a single booked visit:
    create one appointment, link the selected tasks to it, and resolve them done."""
    scheduled_date = jalali_to_gregorian_str(request.form.get("scheduled_date", ""))
    if not scheduled_date:
        flash("تاریخ ویزیت الزامی است", "error")
        return redirect(request.referrer or url_for("followups.worklist"))
    scheduled_time = (request.form.get("scheduled_time") or "09:00").strip()
    scheduled_at = f"{scheduled_date} {scheduled_time}:00"

    repo = FollowupRepository()
    # Only THIS patient's OPEN tasks are eligible — scope the posted ids to them so a
    # stale/tampered form can never resolve or mis-link another patient's follow-up
    # (and we never create an orphan appointment for an empty/foreign set).
    open_ids = [t['id'] for t in repo.list_for_patient(pid) if t.get('status') == 'open']
    posted = request.form.getlist("task_ids", type=int)
    task_ids = [tid for tid in posted if tid in open_ids] if posted else open_ids
    if not task_ids:
        flash("پیگیریِ بازی برای این بیمار نیست", "error")
        return redirect(request.referrer or url_for("followups.worklist"))

    appt_id = AppointmentService().schedule(
        pid, scheduled_at=scheduled_at, appt_type='visit',
        notes='ویزیتِ ناشی از ادغامِ پیگیری‌ها (ورک‌لیست)',
        created_by=g.user["username"],
    )
    repo.assign_appointment_bulk(task_ids, appt_id)
    for tid in task_ids:
        repo.resolve(tid, 'done')
    log_activity("followup_to_visit",
                 f"{len(task_ids)} پیگیری به یک ویزیت ختم شد (بیمار {pid})")
    flash(f"{len(task_ids)} پیگیری به یک ویزیت ختم شد", "success")
    return redirect(url_for("followups.worklist"))


@bp.route("/add", methods=["POST"])
@login_required
def add_manual():
    pid = request.form.get("patient_link_id", type=int)
    if pid:
        FollowupRepository().create(
            pid, reason='manual',
            detail=request.form.get("detail") or None,
            due_date=jalali_to_gregorian_str(request.form.get("due_date", "")),
            assigned_to=g.user["username"],
        )
        flash("پیگیری ثبت شد", "success")
    return redirect(request.referrer or url_for("followups.worklist"))
