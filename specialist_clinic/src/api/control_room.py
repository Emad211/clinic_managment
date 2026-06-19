"""Patient Control Room — prioritized cohort targeting with one-click recall.

Visible to all logged-in users; the revenue/value dimension is computed only for
managers (`g.user.role == 'manager'`). Cohort recipient lists are always
recomputed server-side from the cohort key (posted ids are never trusted)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from src.api.auth import login_required
from src.services.control_room_service import ControlRoomService
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.services.activity_logger import log_activity

bp = Blueprint("control_room", __name__, url_prefix="/control-room")


def _show_value() -> bool:
    return bool(g.user and g.user['role'] == 'manager')


@bp.route("/")
@login_required
def index():
    svc = ControlRoomService()
    data = svc.panel(show_value=_show_value())
    conversion = svc.conversion()
    return render_template("control_room.html", active_page='control_room',
                           conversion=conversion, **data)


@bp.route("/recall", methods=["POST"])
@login_required
def recall():
    """Open a 'recall' worklist call-task for everyone in the chosen cohort."""
    cohort = request.form.get("cohort", "")
    ids = ControlRoomService().cohort_ids(cohort, show_value=_show_value())
    repo = FollowupRepository()
    created = 0
    for pid in ids:
        if not repo.exists_open(pid, 'recall'):
            repo.create(pid, reason='recall', detail='دعوتِ بازگشت — از اتاقِ کنترل',
                        source_event='control_room')
            created += 1
    log_activity("control_room_recall", f"ساخت {created} تسکِ تماس از اتاقِ کنترل ({cohort})")
    flash(f"{created} تسکِ تماس برای این گروه در ورک‌لیست ساخته شد", "success")
    return redirect(url_for("control_room.index"))


@bp.route("/sms", methods=["POST"])
@login_required
def sms():
    """Send a one-off invitation SMS to everyone in the cohort (opt-out respected)."""
    from src.services.sms.campaign_service import send_single
    from src.services.sms.compliance import sanitize
    cohort = request.form.get("cohort", "")
    body = sanitize((request.form.get("body", "") or "").strip())
    if not body:
        flash("متن پیام الزامی است")
        return redirect(url_for("control_room.index"))
    data = ControlRoomService().panel(show_value=_show_value())
    by_id = {p['id']: p for p in data['patients']}
    ids = next((c['ids'] for c in data['cohorts'] if c['key'] == cohort), [])
    sent = skipped = 0
    for pid in ids:
        p = by_id.get(pid)
        if not p or not p['phone'] or p['opt_out']:
            skipped += 1
            continue
        send_single(pid, p['phone'], body.replace('{name}', p['name'] or 'بیمار'),
                    message_type='Informational')
        sent += 1
    log_activity("control_room_sms", f"ارسال {sent} پیامکِ دعوت از اتاقِ کنترل ({cohort})")
    flash(f"{sent} پیامک ارسال شد" + (f" · {skipped} رد (انصراف/بدون موبایل)" if skipped else ""),
          "success")
    return redirect(url_for("control_room.index"))
