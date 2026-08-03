"""FO-3 feature-flagged, GET-only Unified Worklist and episode Timeline."""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    render_template,
    request,
    url_for,
)

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now
from src.security.permissions import Permission, has_permission, permission_required
from src.services.followup_orchestration.read_model_service import (
    FollowupUnifiedReadModelService,
    ROLE_LABELS,
    STATE_LABELS,
)
from src.services.followup_orchestration.timeline_service import (
    FollowupTimelineService,
)


bp = Blueprint("unified_followups", __name__, url_prefix="/followups/unified")


def _require_flag() -> None:
    if not current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_READONLY", False):
        abort(404)


@bp.after_request
def disable_shared_caching(response):
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def index():
    _require_flag()
    model = FollowupUnifiedReadModelService(get_db()).list_items(
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 20),
        query=request.args.get("q"),
        state_class=request.args.get("state"),
        role=request.args.get("role"),
        sla_state=request.args.get("sla"),
        now=iran_now().replace(tzinfo=None, microsecond=0),
    )
    return render_template(
        "followups/unified_worklist.html",
        model=model,
        state_labels=STATE_LABELS,
        role_labels=ROLE_LABELS,
        sla_labels={
            "ON_TIME": "در مهلت",
            "DUE_SOON": "نزدیک موعد",
            "OVERDUE": "موعدگذشته",
            "BLOCKED": "مسدود",
            "NONE": "بدون SLA",
        },
        hub_tab="unified",
        hub_pending=0,
        alert_pending=0,
        active_page="sms",
    )


@bp.get("/<episode_id>")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def detail(episode_id: str):
    _require_flag()
    db = get_db()
    item = FollowupUnifiedReadModelService(db).get_item(
        episode_id,
        now=iran_now().replace(tzinfo=None, microsecond=0),
    )
    if item is None:
        abort(404)
    timeline = FollowupTimelineService(db).build(episode_id)
    if timeline is None:
        abort(404)

    deep_links = [
        {
            "label": "بازکردن ورک‌لیست فعلی",
            "href": url_for(
                "followups.worklist",
                q=item.get("patient_name") or "",
            ),
            "primary": True,
        },
        {
            "label": "بازکردن پروندهٔ بیمار",
            "href": url_for("patients.detail", pid=item["patient_link_id"]),
            "primary": False,
        },
    ]
    if has_permission(Permission.SMS_APPROVAL_REVIEW):
        deep_links.append(
            {
                "label": "بازکردن صف تأیید پیام",
                "href": url_for("sms.approvals"),
                "primary": False,
            }
        )
    if has_permission(Permission.SMS_VIEW):
        deep_links.append(
            {
                "label": "بازکردن گزارش تحویل پیام",
                "href": url_for("sms.messages_report"),
                "primary": False,
            }
        )

    return render_template(
        "followups/unified_detail.html",
        item=item,
        timeline=timeline,
        deep_links=deep_links,
        hub_tab="unified",
        hub_pending=0,
        alert_pending=0,
        active_page="sms",
    )


__all__ = ["bp"]
