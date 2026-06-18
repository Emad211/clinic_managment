from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from src.api.auth import login_required
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.followup_service import FollowupService, REASON_LABELS
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str

bp = Blueprint("followups", __name__, url_prefix="/followups")


@bp.route("/")
@login_required
def worklist():
    reason = request.args.get("reason") or None
    repo = FollowupRepository()
    tasks = repo.list_open(reason)
    for t in tasks:
        t['reason_fa'] = REASON_LABELS.get(t['reason'], t['reason'])
    counts = repo.counts_by_reason()
    return render_template("followups/worklist.html", tasks=tasks, counts=counts,
                           reason_labels=REASON_LABELS, active_reason=reason,
                           show_worklist_tab=True, active_page='followups')


@bp.route("/generate", methods=["POST"])
@login_required
def generate():
    # Worklist-only pass of the engagement engine: open the due call-tasks
    # (lapsed / uncontrolled / red-flag, and anything the manager routed to the
    # worklist) WITHOUT sending any SMS — a manual "refresh the worklist" action.
    from src.services.engagement_service import EngagementService
    res = EngagementService().run_all(worklist_only=True)
    flash(f"{res['worklist']} پیگیری جدید ساخته شد", "success")
    return redirect(url_for("followups.worklist"))


@bp.route("/<int:task_id>/resolve", methods=["POST"])
@login_required
def resolve(task_id):
    status = request.form.get("status", "done")
    call_log = request.form.get("call_log") or None
    FollowupRepository().resolve(task_id, status, call_log)
    log_activity("followup_resolve", f"بستن پیگیری ({status})")
    return redirect(request.referrer or url_for("followups.worklist"))


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
