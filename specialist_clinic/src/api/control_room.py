"""Legacy cohort Control Room with Unified Work Center compatibility.

When the Unified Work Center is enabled, it is the only operational destination. The
legacy cohort page remains available only for deployments that have not enabled the
unified read model yet.
"""
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from src.adapters.sqlite.followups_repo import FollowupRepository
from src.api.auth import login_required
from src.services.activity_logger import log_activity
from src.services.control_room_service import ControlRoomService


bp = Blueprint("control_room", __name__, url_prefix="/control-room")


def _show_value() -> bool:
    return bool(g.user and g.user["role"] == "manager")


def _unified_enabled() -> bool:
    return bool(current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_READONLY", False))


def _unified_target():
    return redirect(
        url_for(
            "unified_followups.index",
            view="manager" if _show_value() else "all",
        )
    )


@bp.route("/")
@login_required
def index():
    if _unified_enabled():
        return _unified_target()
    service = ControlRoomService()
    data = service.panel(show_value=_show_value())
    conversion = service.conversion()
    return render_template(
        "control_room.html",
        active_page="control_room",
        conversion=conversion,
        **data,
    )


@bp.route("/recall", methods=["POST"])
@login_required
def recall():
    """Create recall tasks, then continue in the active operational destination."""
    cohort = request.form.get("cohort", "")
    ids = ControlRoomService().cohort_ids(cohort, show_value=_show_value())
    repo = FollowupRepository()
    created = 0
    for patient_id in ids:
        if not repo.exists_open(patient_id, "recall"):
            repo.create(
                patient_id,
                reason="recall",
                detail="دعوت بازگشت — از مسیر سازگاری گروه‌ها",
                source_event="control_room",
            )
            created += 1
    log_activity(
        "control_room_recall",
        f"ساخت {created} کار تماس از مسیر سازگاری گروه ({cohort})",
    )
    flash(f"{created} کار تماس برای این گروه ساخته شد", "success")
    if _unified_enabled():
        return _unified_target()
    return redirect(url_for("control_room.index"))


@bp.route("/sms", methods=["POST"])
@login_required
def sms():
    """Legacy free-text cohort queue; unavailable after Unified rollout."""
    if _unified_enabled():
        # Unified messaging accepts only governed templates through Message Center or
        # Work Center. Keeping this old free-text mutation reachable would recreate a
        # second operational path and bypass the Stage-1 policy boundary.
        abort(404)

    from src.services.engagement_service import EngagementService
    from src.services.sms.compliance import sanitize

    cohort = request.form.get("cohort", "")
    body = sanitize((request.form.get("body", "") or "").strip())
    if not body:
        flash("متن پیام الزامی است")
        return redirect(url_for("control_room.index"))
    data = ControlRoomService().panel(show_value=_show_value())
    by_id = {patient["id"]: patient for patient in data["patients"]}
    ids = next(
        (item["ids"] for item in data["cohorts"] if item["key"] == cohort),
        [],
    )
    queued = skipped = 0
    engagement = EngagementService()
    for patient_id in ids:
        patient = by_id.get(patient_id)
        if not patient or not patient["phone"] or patient["opt_out"]:
            skipped += 1
            continue
        if engagement.enqueue_control_room_invite(patient_id, body):
            queued += 1
        else:
            skipped += 1
    log_activity(
        "control_room_sms_queue",
        f"افزودن {queued} پیام به صف تأیید ({cohort})",
    )
    flash(
        f"{queued} پیام به صف تأیید پزشک افزوده شد"
        + (
            f" · {skipped} مورد تکراری/انصراف/بدون موبایل"
            if skipped
            else ""
        ),
        "success",
    )
    return redirect(url_for("control_room.index"))
