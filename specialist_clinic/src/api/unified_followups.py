"""FO-3 read model plus feature-gated FO-4 ownership actions."""
from __future__ import annotations

import secrets
import sqlite3

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

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now
from src.security.permissions import Permission, has_permission, permission_required
from src.services.followup_orchestration.ownership_service import (
    FollowupOwnershipError,
    FollowupOwnershipService,
    ROLE_LABELS as OWNER_ROLE_LABELS,
)
from src.services.followup_orchestration.read_model_service import (
    FollowupUnifiedReadModelService,
    READINESS_COPY,
    ROLE_LABELS,
    STATE_LABELS,
)
from src.services.followup_orchestration.timeline_service import FollowupTimelineService


bp = Blueprint("unified_followups", __name__, url_prefix="/followups/unified")


def _require_flag() -> None:
    if not current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_READONLY", False):
        abort(404)


def _require_actions_flag() -> None:
    _require_flag()
    if not current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_ACTIONS", False):
        abort(404)


def _require_routing_flag() -> None:
    _require_actions_flag()
    if not current_app.config.get("FOLLOWUP_AUTO_ROUTING", False):
        abort(404)


def _read_failure() -> dict:
    copy = READINESS_COPY["PROJECTION_READ_FAILED"]
    return {
        "ready": False,
        "code": "PROJECTION_READ_FAILED",
        "label": copy["label"],
        "help": copy["help"],
    }


def _render_unavailable(readiness: dict):
    return render_template(
        "followups/unified_unavailable.html",
        readiness=readiness,
        hub_tab="unified",
        hub_pending=0,
        alert_pending=0,
        active_page="sms",
    )


def _redirect_detail(episode_id: str):
    return redirect(url_for("unified_followups.detail", episode_id=episode_id))


def _handle_ownership_error(error: FollowupOwnershipError, episode_id: str):
    category = "warning" if error.code in {
        "STALE_OWNERSHIP_FORM", "ALREADY_CLAIMED"
    } else "error"
    flash(error.message, category)
    return _redirect_detail(episode_id)


@bp.after_request
def disable_shared_caching(response):
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def index():
    _require_flag()
    db = get_db()
    model = FollowupUnifiedReadModelService(db).list_items(
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 20),
        query=request.args.get("q"),
        state_class=request.args.get("state"),
        role=request.args.get("role"),
        sla_state=request.args.get("sla"),
        now=iran_now().replace(tzinfo=None, microsecond=0),
    )
    if model.get("projection_ready"):
        FollowupOwnershipService(db).decorate_items(model["items"])
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
        actions_enabled=bool(
            current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_ACTIONS", False)
        ),
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
    read_model = FollowupUnifiedReadModelService(db)
    result = read_model.get_item_result(
        episode_id,
        now=iran_now().replace(tzinfo=None, microsecond=0),
    )
    if not result["readiness"]["ready"]:
        return _render_unavailable(result["readiness"])
    item = result["item"]
    if item is None:
        abort(404)

    try:
        timeline = FollowupTimelineService(db).build(episode_id)
    except sqlite3.Error:
        return _render_unavailable(_read_failure())
    if timeline is None:
        return _render_unavailable(_read_failure())

    ownership_service = FollowupOwnershipService(db)
    ownership = ownership_service.state(episode_id).as_dict()
    actions_enabled = bool(
        current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_ACTIONS", False)
    )
    routing_enabled = bool(
        current_app.config.get("FOLLOWUP_AUTO_ROUTING", False)
    )
    capabilities = (
        ownership_service.capabilities(episode_id=episode_id, actor=g.user)
        if actions_enabled
        else {
            "can_claim": False,
            "can_release": False,
            "can_assign": False,
            "can_route": False,
        }
    )
    assignable_users = (
        ownership_service.assignable_users(ownership.get("owner_role"))
        if actions_enabled and capabilities["can_assign"]
        else []
    )

    deep_links = [
        {
            "label": "بازکردن ورک‌لیست فعلی",
            "href": url_for("followups.worklist", q=item.get("patient_name") or ""),
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
        ownership=ownership,
        ownership_capabilities=capabilities,
        assignable_users=assignable_users,
        ownership_role_labels=OWNER_ROLE_LABELS,
        ownership_action_token=secrets.token_hex(16),
        actions_enabled=actions_enabled,
        routing_enabled=routing_enabled,
        hub_tab="unified",
        hub_pending=0,
        alert_pending=0,
        active_page="sms",
    )


@bp.post("/<episode_id>/claim")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def claim(episode_id: str):
    _require_actions_flag()
    try:
        FollowupOwnershipService(get_db()).claim(
            episode_id=episode_id,
            actor=g.user,
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
        )
    except FollowupOwnershipError as error:
        return _handle_ownership_error(error, episode_id)
    flash("این مورد برای رسیدگی شما ثبت شد.", "success")
    return _redirect_detail(episode_id)


@bp.post("/<episode_id>/release")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def release(episode_id: str):
    _require_actions_flag()
    try:
        FollowupOwnershipService(get_db()).release(
            episode_id=episode_id,
            actor=g.user,
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
            reason_code=request.form.get("reason_code", "OWNER_RELEASE"),
        )
    except FollowupOwnershipError as error:
        return _handle_ownership_error(error, episode_id)
    flash("مسئول این مورد آزاد شد و به صف مربوط بازگشت.", "success")
    return _redirect_detail(episode_id)


@bp.post("/<episode_id>/assign")
@permission_required(Permission.FOLLOWUP_ADMIN_MANAGE)
def assign(episode_id: str):
    _require_actions_flag()
    try:
        FollowupOwnershipService(get_db()).assign(
            episode_id=episode_id,
            owner_user_id=request.form.get("owner_user_id", type=int),
            actor=g.user,
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
            reason_code=request.form.get("reason_code", "MANAGER_ASSIGN"),
        )
    except (FollowupOwnershipError, TypeError, ValueError) as error:
        if isinstance(error, FollowupOwnershipError):
            return _handle_ownership_error(error, episode_id)
        flash("کاربر انتخاب‌شده معتبر نیست.", "error")
        return _redirect_detail(episode_id)
    flash("مسئول این مورد ثبت شد.", "success")
    return _redirect_detail(episode_id)


@bp.post("/<episode_id>/route")
@permission_required(Permission.FOLLOWUP_ADMIN_MANAGE)
def route(episode_id: str):
    _require_routing_flag()
    try:
        FollowupOwnershipService(get_db()).route(
            episode_id=episode_id,
            owner_role=request.form.get("owner_role", ""),
            actor=g.user,
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
            reason_code=request.form.get("reason_code", "MANAGER_ROUTE"),
        )
    except FollowupOwnershipError as error:
        return _handle_ownership_error(error, episode_id)
    flash("صف مسئول تغییر کرد؛ مورد اکنون بدون مسئول فردی در صف جدید است.", "success")
    return _redirect_detail(episode_id)


__all__ = ["bp"]
