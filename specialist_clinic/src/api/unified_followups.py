"""Automation-first Work Center over the governed follow-up orchestration seams."""
from __future__ import annotations

from datetime import datetime
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
from src.adapters.sqlite.followup_episode_repo import FollowupEpisodeRepository
from src.common.utils import iran_now, jalali_to_gregorian_str
from src.security.permissions import (
    Permission,
    has_permission,
    permission_required,
    resolved_permissions,
)
from src.services.followup_orchestration.ownership_service import (
    FollowupOwnershipError,
    FollowupOwnershipService,
    ROLE_LABELS as OWNER_ROLE_LABELS,
    ROLE_PERMISSIONS,
)
from src.services.followup_orchestration.read_model_service import (
    FollowupUnifiedReadModelService,
    READINESS_COPY,
    ROLE_LABELS,
    SLA_LABELS,
    STATE_LABELS,
)
from src.services.followup_orchestration.structured_contact_service import (
    FollowupStructuredContactError,
    FollowupStructuredContactService,
    OUTCOME_LABELS as CONTACT_OUTCOME_LABELS,
)
from src.services.followup_orchestration.timeline_service import (
    FollowupTimelineService,
)
from src.services.followup_orchestration.work_center_read_model import (
    WORK_VIEW_LABELS,
    WorkCenterReadModelService,
)


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


def _require_structured_contact_flag() -> None:
    _require_routing_flag()
    if not current_app.config.get("FOLLOWUP_STRUCTURED_CONTACT", False):
        abort(404)


def _contact_callback_value() -> str | None:
    date_j = str(request.form.get("callback_date") or "").strip()
    time_s = str(request.form.get("callback_time") or "").strip()
    if not date_j and not time_s:
        return None
    if not date_j or not time_s:
        raise FollowupStructuredContactError(
            "INVALID_CALLBACK_AT",
            "برای تماس مجدد، تاریخ و ساعت را کامل وارد کنید.",
        )
    date_g = jalali_to_gregorian_str(date_j)
    if not date_g:
        raise FollowupStructuredContactError(
            "INVALID_CALLBACK_AT",
            "تاریخ شمسی تماس مجدد معتبر نیست.",
        )
    try:
        normalized_time = datetime.strptime(time_s, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise FollowupStructuredContactError(
            "INVALID_CALLBACK_AT",
            "ساعت تماس مجدد معتبر نیست.",
        ) from exc
    return f"{date_g} {normalized_time}:00"


def _read_failure() -> dict:
    copy = READINESS_COPY["PROJECTION_READ_FAILED"]
    return {
        "ready": False,
        "code": "PROJECTION_READ_FAILED",
        "label": copy["label"],
        "help": copy["help"],
    }


def _can_manage_work() -> bool:
    return has_permission(Permission.FOLLOWUP_ADMIN_MANAGE)


def _positive_int(value: object, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), maximum)


def _work_context(source) -> dict:
    allow_manager = _can_manage_work()
    raw_view = source.get("work_view") or source.get("view") or "mine"
    view = WorkCenterReadModelService.normalize_view(
        raw_view,
        allow_manager=allow_manager,
    )
    state = str(source.get("state") or "").strip().upper()
    role = str(source.get("role") or "").strip().upper()
    sla = str(source.get("sla") or "").strip().upper()
    return {
        "view": view,
        "q": str(source.get("q") or "").strip()[:120],
        "state": state if state in STATE_LABELS else "",
        "role": role if role in ROLE_LABELS else "",
        "sla": sla if sla in SLA_LABELS else "",
        "page": _positive_int(source.get("page"), 1, 1_000_000),
        "per_page": _positive_int(source.get("per_page"), 20, 50),
    }


def _context_params(context: dict) -> dict:
    return {
        "view": context["view"],
        "q": context["q"],
        "state": context["state"],
        "role": context["role"],
        "sla": context["sla"],
        "page": context["page"],
        "per_page": context["per_page"],
    }


def _index_url(context: dict) -> str:
    return url_for("unified_followups.index", **_context_params(context))


def _detail_url(episode_id: str, context: dict) -> str:
    return url_for(
        "unified_followups.detail",
        episode_id=episode_id,
        **_context_params(context),
    )


def _redirect_detail(episode_id: str, context: dict | None = None):
    return redirect(_detail_url(episode_id, context or _work_context({})))


def _next_item_url(context: dict, *, exclude_episode_id: str) -> str | None:
    next_item = WorkCenterReadModelService(get_db()).next_item(
        actor_user_id=int(g.user["id"]),
        allow_manager_view=_can_manage_work(),
        work_view=context["view"],
        query=context["q"],
        state_class=context["state"],
        role=context["role"],
        sla_state=context["sla"],
        exclude_episode_id=exclude_episode_id,
        now=iran_now().replace(tzinfo=None, microsecond=0),
    )
    if not next_item:
        return None
    return _detail_url(str(next_item["episode_id"]), context)


def _render_unavailable(readiness: dict):
    return render_template(
        "followups/unified_unavailable.html",
        readiness=readiness,
        active_page="work_center",
    )


def _handle_ownership_error(
    error: FollowupOwnershipError,
    episode_id: str,
    context: dict,
):
    category = "warning" if error.code in {
        "STALE_OWNERSHIP_FORM",
        "ALREADY_CLAIMED",
    } else "error"
    flash(error.message, category)
    return _redirect_detail(episode_id, context)


def _handle_contact_error(
    error: FollowupStructuredContactError,
    episode_id: str,
    context: dict,
):
    category = "warning" if error.code in {
        "STALE_CONTACT_FORM",
        "CONTACT_IDEMPOTENCY_CONFLICT",
    } else "error"
    flash(error.message, category)
    return _redirect_detail(episode_id, context)


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
    allow_manager_view = _can_manage_work()
    read_model = WorkCenterReadModelService(db)
    model = read_model.list_items(
        actor_user_id=int(g.user["id"]),
        allow_manager_view=allow_manager_view,
        work_view=request.args.get("view", "mine"),
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 20),
        query=request.args.get("q"),
        state_class=request.args.get("state"),
        role=request.args.get("role"),
        sla_state=request.args.get("sla"),
        now=iran_now().replace(tzinfo=None, microsecond=0),
    )
    actions_enabled = bool(
        current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_ACTIONS", False)
    )
    routing_enabled = bool(
        current_app.config.get("FOLLOWUP_AUTO_ROUTING", False)
    )
    structured_contact_enabled = bool(
        actions_enabled
        and routing_enabled
        and current_app.config.get("FOLLOWUP_STRUCTURED_CONTACT", False)
    )
    if model.get("projection_ready"):
        ownership_service = FollowupOwnershipService(db)
        ownership_service.decorate_items(model["items"])
        effective_permissions = resolved_permissions(g.user)
        for item in model["items"]:
            ownership = item["ownership"]
            owner_role = ownership.get("owner_role")
            item["ownership_capabilities"] = {
                "can_claim": bool(
                    actions_enabled
                    and owner_role in ROLE_PERMISSIONS
                    and not ownership["assigned"]
                    and ROLE_PERMISSIONS[owner_role] in effective_permissions
                ),
                "can_release": bool(
                    actions_enabled
                    and ownership["assigned"]
                    and (
                        ownership.get("owner_user_id") == int(g.user["id"])
                        or Permission.FOLLOWUP_ADMIN_MANAGE in effective_permissions
                    )
                ),
                "can_assign": bool(
                    actions_enabled
                    and Permission.FOLLOWUP_ADMIN_MANAGE in effective_permissions
                ),
                "can_route": bool(
                    routing_enabled
                    and Permission.FOLLOWUP_ADMIN_MANAGE in effective_permissions
                ),
            }
            item["ownership_action_token"] = secrets.token_hex(16)
        if structured_contact_enabled:
            FollowupStructuredContactService(db).decorate_items(model["items"])

    work_counts = read_model.counts(actor_user_id=int(g.user["id"]))
    return render_template(
        "followups/unified_worklist.html",
        model=model,
        work_counts=work_counts,
        work_view_labels=WORK_VIEW_LABELS,
        state_labels=STATE_LABELS,
        role_labels=ROLE_LABELS,
        sla_labels=SLA_LABELS,
        actions_enabled=actions_enabled,
        structured_contact_enabled=structured_contact_enabled,
        can_manage_work=allow_manager_view,
        active_page="work_center",
    )


@bp.get("/<episode_id>")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def detail(episode_id: str):
    _require_flag()
    db = get_db()
    context = _work_context(request.args)
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
    structured_contact_enabled = bool(
        actions_enabled
        and routing_enabled
        and current_app.config.get("FOLLOWUP_STRUCTURED_CONTACT", False)
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

    contact_summary = None
    contact_capabilities = {
        "can_record": False,
        "reason": None,
        "task_id": None,
    }
    contact_expected_event_id = 0
    if structured_contact_enabled:
        contact_service = FollowupStructuredContactService(db)
        contact_summary = contact_service.summary(episode_id)
        contact_capabilities = contact_service.capabilities(
            episode_id=episode_id,
            actor=g.user,
        )
        current_event = FollowupEpisodeRepository(db).current_event(episode_id)
        contact_expected_event_id = (
            int(current_event["id"]) if current_event else 0
        )

    return render_template(
        "followups/unified_detail.html",
        item=item,
        timeline=timeline,
        ownership=ownership,
        ownership_capabilities=capabilities,
        assignable_users=assignable_users,
        ownership_role_labels=OWNER_ROLE_LABELS,
        ownership_action_token=secrets.token_hex(16),
        actions_enabled=actions_enabled,
        routing_enabled=routing_enabled,
        structured_contact_enabled=structured_contact_enabled,
        contact_summary=contact_summary,
        contact_capabilities=contact_capabilities,
        contact_outcome_labels=CONTACT_OUTCOME_LABELS,
        contact_expected_event_id=contact_expected_event_id,
        contact_action_token=secrets.token_hex(16),
        work_context=context,
        return_url=_index_url(context),
        next_item_url=_next_item_url(context, exclude_episode_id=episode_id),
        active_page="work_center",
    )


@bp.post("/<episode_id>/handle")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def handle(episode_id: str):
    """Start handling when claim is allowed, otherwise open the workspace."""
    _require_flag()
    context = _work_context(request.form)
    if current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_ACTIONS", False):
        service = FollowupOwnershipService(get_db())
        try:
            capabilities = service.capabilities(episode_id=episode_id, actor=g.user)
            state = service.state(episode_id)
            if capabilities["can_claim"] and not state.assigned:
                service.claim(
                    episode_id=episode_id,
                    actor=g.user,
                    expected_event_id=request.form.get("expected_event_id"),
                    idempotency_key=request.form.get("idempotency_key", ""),
                )
                flash("رسیدگی این مورد برای شما شروع شد.", "success")
        except FollowupOwnershipError as error:
            return _handle_ownership_error(error, episode_id, context)
    return _redirect_detail(episode_id, context)


@bp.post("/<episode_id>/claim")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def claim(episode_id: str):
    """Compatibility endpoint; normal Work Center flow uses handle()."""
    _require_actions_flag()
    context = _work_context(request.form)
    try:
        FollowupOwnershipService(get_db()).claim(
            episode_id=episode_id,
            actor=g.user,
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
        )
    except FollowupOwnershipError as error:
        return _handle_ownership_error(error, episode_id, context)
    flash("رسیدگی این مورد برای شما شروع شد.", "success")
    return _redirect_detail(episode_id, context)


@bp.post("/<episode_id>/release")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def release(episode_id: str):
    _require_actions_flag()
    context = _work_context(request.form)
    try:
        FollowupOwnershipService(get_db()).release(
            episode_id=episode_id,
            actor=g.user,
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
            reason_code=request.form.get(
                "reason_code",
                "OWNER_RELEASE",
            ),
        )
    except FollowupOwnershipError as error:
        return _handle_ownership_error(error, episode_id, context)
    flash("مسئول این مورد آزاد شد و به صف مربوط بازگشت.", "success")
    return _redirect_detail(episode_id, context)


@bp.post("/<episode_id>/assign")
@permission_required(Permission.FOLLOWUP_ADMIN_MANAGE)
def assign(episode_id: str):
    _require_actions_flag()
    context = _work_context(request.form)
    try:
        FollowupOwnershipService(get_db()).assign(
            episode_id=episode_id,
            owner_user_id=request.form.get("owner_user_id", type=int),
            actor=g.user,
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
            reason_code=request.form.get(
                "reason_code",
                "MANAGER_ASSIGN",
            ),
        )
    except (FollowupOwnershipError, TypeError, ValueError) as error:
        if isinstance(error, FollowupOwnershipError):
            return _handle_ownership_error(error, episode_id, context)
        flash("کاربر انتخاب‌شده معتبر نیست.", "error")
        return _redirect_detail(episode_id, context)
    flash("مسئول این مورد ثبت شد.", "success")
    return _redirect_detail(episode_id, context)


@bp.post("/<episode_id>/route")
@permission_required(Permission.FOLLOWUP_ADMIN_MANAGE)
def route(episode_id: str):
    _require_routing_flag()
    context = _work_context(request.form)
    try:
        FollowupOwnershipService(get_db()).route(
            episode_id=episode_id,
            owner_role=request.form.get("owner_role", ""),
            actor=g.user,
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
            reason_code=request.form.get(
                "reason_code",
                "MANAGER_ROUTE",
            ),
        )
    except FollowupOwnershipError as error:
        return _handle_ownership_error(error, episode_id, context)
    flash(
        "صف مسئول تغییر کرد؛ مورد اکنون بدون مسئول فردی در صف جدید است.",
        "success",
    )
    return _redirect_detail(episode_id, context)


@bp.post("/<episode_id>/contact")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def record_contact(episode_id: str):
    _require_structured_contact_flag()
    context = _work_context(request.form)
    try:
        summary = FollowupStructuredContactService(get_db()).record(
            episode_id=episode_id,
            actor=g.user,
            structured_outcome=request.form.get("structured_outcome"),
            expected_event_id=request.form.get("expected_event_id"),
            idempotency_key=request.form.get("idempotency_key", ""),
            callback_at=_contact_callback_value(),
            note=request.form.get("note") or None,
            now=iran_now(),
        )
    except FollowupStructuredContactError as error:
        return _handle_contact_error(error, episode_id, context)

    if summary.get("callback_at"):
        message = "نتیجهٔ تماس و زمان تماس مجدد ثبت شد."
    elif summary.get("escalated"):
        message = "نتیجهٔ تماس ثبت و مسیر برای بررسی بالاتر ارجاع شد."
    else:
        message = "نتیجهٔ تماس ثبت شد."

    if request.form.get("auto_next") == "1":
        next_url = _next_item_url(context, exclude_episode_id=episode_id)
        if next_url:
            flash(message + " کار بعدی باز شد.", "success")
            return redirect(next_url)
        flash(message + " در این نما کار دیگری باقی نمانده است.", "success")
        return redirect(_index_url(context))

    flash(message, "success")
    return _redirect_detail(episode_id, context)


__all__ = ["bp"]
