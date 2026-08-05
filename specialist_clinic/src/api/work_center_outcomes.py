"""Focused Work Center start, evidence and communication mutations."""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    request,
    url_for,
)

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now, jalali_to_gregorian_str
from src.security.permissions import Permission, permission_required, resolved_permissions
from src.services.activity_logger import log_activity
from src.services.followup_orchestration.ownership_service import (
    FollowupOwnershipError,
    FollowupOwnershipService,
)
from src.services.followup_orchestration.read_model_service import (
    ROLE_LABELS,
    SLA_LABELS,
    STATE_LABELS,
)
from src.services.followup_orchestration.work_center_action_service import (
    WorkCenterActionError,
    WorkCenterActionService,
)
from src.services.followup_orchestration.work_center_contract_service import (
    WorkCenterContractService,
)
from src.services.followup_orchestration.work_center_message_service import (
    WorkCenterMessageError,
    WorkCenterMessageService,
)
from src.services.followup_orchestration.work_center_read_model import (
    WorkCenterReadModelService,
)


bp = Blueprint(
    "work_center_outcomes",
    __name__,
    url_prefix="/followups/work-center-outcomes",
)


@bp.before_request
def require_work_center_actions():
    if not (
        current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_READONLY", False)
        and current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_ACTIONS", False)
    ):
        abort(404)


def _safe_work_url(value: object, fallback: str) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        return fallback
    parsed = urlsplit(rendered)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not parsed.path.startswith("/followups/unified"):
        return fallback
    return rendered


def _positive_int(value: object, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), maximum)


def _work_context(source) -> dict:
    permissions = resolved_permissions(g.user)
    allow_manager = Permission.FOLLOWUP_ADMIN_MANAGE in permissions
    view = WorkCenterReadModelService.normalize_view(
        source.get("work_view") or source.get("view") or "mine",
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
        "allow_manager": allow_manager,
    }


def _detail_url(episode_id: str, context: dict | None = None) -> str:
    values = context or {}
    return url_for(
        "unified_followups.detail",
        episode_id=episode_id,
        view=values.get("view", "mine"),
        q=values.get("q", ""),
        state=values.get("state", ""),
        role=values.get("role", ""),
        sla=values.get("sla", ""),
        page=values.get("page", 1),
        per_page=values.get("per_page", 20),
    )


def _failure(episode_id: str, error: Exception):
    if isinstance(
        error,
        (WorkCenterActionError, WorkCenterMessageError, FollowupOwnershipError),
    ):
        message = error.message
    elif isinstance(error, (ValueError, LookupError)):
        current_app.logger.info(
            "Rejected Work Center action for episode=%s: %s",
            episode_id,
            type(error).__name__,
        )
        message = "اطلاعات اقدام با قرارداد فعلی سازگار نیست."
    else:
        current_app.logger.exception(
            "Unexpected Work Center action failure for episode=%s",
            episode_id,
        )
        message = "خطای غیرمنتظره رخ داد؛ دوباره تلاش کنید."
    flash(f"اقدام انجام نشد: {message}", "error")
    return redirect(
        _safe_work_url(request.form.get("current_url"), _detail_url(episode_id))
    )


def _success(episode_id: str, result: dict, message: str):
    if not result.get("projection_refreshed", True):
        flash(message + " نمای کار نیازمند تازه‌سازی است.", "warning")
    else:
        flash(message, "success")
    next_url = _safe_work_url(request.form.get("next_url"), "")
    if next_url:
        return redirect(next_url)
    return redirect(
        _safe_work_url(
            request.form.get("return_url"),
            url_for("unified_followups.index"),
        )
    )


def _observed_at(value: object) -> str:
    raw = str(value or "").strip()
    if raw:
        converted = jalali_to_gregorian_str(raw)
        return f"{converted} 12:00:00" if converted else raw
    return iran_now().replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=None,
    ).isoformat(sep=" ", timespec="seconds")


def template_context() -> dict:
    """Inject only the action contract needed by the unified detail template."""
    if (
        request.endpoint != "unified_followups.detail"
        or not getattr(g, "user", None)
        or not current_app.config.get("FOLLOWUP_UNIFIED_WORKLIST_ACTIONS", False)
    ):
        return {"work_action": None}
    episode_id = str((request.view_args or {}).get("episode_id") or "").strip()
    if not episode_id:
        return {"work_action": None}
    try:
        action = WorkCenterContractService(get_db()).build(
            episode_id,
            permissions=resolved_permissions(g.user),
        )
    except Exception:
        current_app.logger.exception(
            "Unable to build Work Center action contract for episode=%s",
            episode_id,
        )
        action = None
    return {"work_action": action}


@bp.post("/start-next")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def start_next():
    """Open and, when allowed, claim the first eligible work item."""
    context = _work_context(request.form)
    db = get_db()
    reader = WorkCenterReadModelService(db)

    def find(view: str):
        return reader.next_item(
            actor_user_id=int(g.user["id"]),
            allow_manager_view=context["allow_manager"],
            work_view=view,
            query=context["q"],
            state_class=context["state"],
            role=context["role"],
            sla_state=context["sla"],
            now=iran_now().replace(tzinfo=None, microsecond=0),
        )

    item = find(context["view"])
    if item is None and context["view"] == "mine":
        item = find("unassigned")
        if item is not None:
            context["view"] = "unassigned"
    if item is None:
        flash("در این نما کار واجدشرایطی باقی نمانده است.", "success")
        return redirect(
            url_for(
                "unified_followups.index",
                view=context["view"],
                q=context["q"],
                state=context["state"],
                role=context["role"],
                sla=context["sla"],
            )
        )

    episode_id = str(item["episode_id"])
    ownership = FollowupOwnershipService(db)
    try:
        state = ownership.state(episode_id)
        capabilities = ownership.capabilities(episode_id=episode_id, actor=g.user)
        if item.get("state_class") != "TERMINAL" and capabilities["can_claim"]:
            ownership.claim(
                episode_id=episode_id,
                actor=g.user,
                expected_event_id=state.expected_event_id,
                idempotency_key=(
                    f"work-center-start:{g.user['id']}:{episode_id}:"
                    f"{secrets.token_hex(8)}"
                ),
            )
            flash("رسیدگی اولین کار واجدشرایط برای شما شروع شد.", "success")
    except FollowupOwnershipError as error:
        return _failure(episode_id, error)
    return redirect(_detail_url(episode_id, context))


@bp.post("/<episode_id>/clinical-complete")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def clinical_complete(episode_id: str):
    try:
        result = WorkCenterActionService(get_db()).complete_clinical(
            episode_id,
            actor_username=str(g.user["username"]),
            actor_user_id=int(g.user["id"]),
            permissions=resolved_permissions(g.user),
            idempotency_key=request.form.get("idempotency_key") or "",
            outcome_type=request.form.get("outcome_type") or "OTHER",
            fact_key=request.form.get("fact_key") or None,
            value=request.form.get("value") or None,
            unit=request.form.get("unit") or None,
            verification="CONFIRMED",
            observed_at=_observed_at(request.form.get("observed_at")),
            note=request.form.get("note") or None,
        )
    except Exception as error:
        return _failure(episode_id, error)
    log_activity(
        "work_center_clinical_complete",
        (
            f"episode={episode_id} task={result['task_id']} "
            f"outcome={result['outcome_event_id']}"
        ),
    )
    return _success(
        episode_id,
        result,
        "شاهد ثبت و پیگیری بالینی تکمیل شد؛ کار بعدی باز می‌شود.",
    )


@bp.post("/<episode_id>/plan-complete")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def plan_complete(episode_id: str):
    try:
        result = WorkCenterActionService(get_db()).complete_plan(
            episode_id,
            actor_username=str(g.user["username"]),
            actor_user_id=int(g.user["id"]),
            permissions=resolved_permissions(g.user),
            idempotency_key=request.form.get("idempotency_key") or "",
            evidence_type=request.form.get("evidence_type") or "",
            evidence_ref=request.form.get("evidence_ref") or "",
            outcome_code=request.form.get("outcome_code") or "",
            note=request.form.get("note") or None,
        )
    except Exception as error:
        return _failure(episode_id, error)
    log_activity(
        "work_center_plan_complete",
        f"episode={episode_id} task={result['task_id']} event={result['event_id']}",
    )
    return _success(
        episode_id,
        result,
        "شاهد اقدام درمانی ثبت و کار تکمیل شد؛ کار بعدی باز می‌شود.",
    )


@bp.post("/<episode_id>/queue-message")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def queue_message(episode_id: str):
    try:
        result = WorkCenterMessageService(get_db()).queue(
            episode_id,
            actor_username=str(g.user["username"]),
            actor_user_id=int(g.user["id"]),
            permissions=resolved_permissions(g.user),
        )
    except Exception as error:
        return _failure(episode_id, error)
    log_activity(
        "work_center_message_queued",
        f"episode={episode_id} approval={result['approval_id']}",
    )
    return _success(
        episode_id,
        result,
        "دعوت مصوب به صف تأیید پیام افزوده شد؛ کار بعدی باز می‌شود.",
    )


__all__ = ["bp", "template_context"]
