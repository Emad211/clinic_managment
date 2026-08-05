"""Evidence-governed completion and safe message actions for Work Center."""
from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, current_app, flash, g, redirect, request, url_for

from src.adapters.sqlite.core import get_db
from src.common.utils import jalali_to_gregorian_str
from src.security.permissions import Permission, permission_required, resolved_permissions
from src.services.activity_logger import log_activity
from src.services.followup_orchestration.work_center_action_service import (
    WorkCenterActionError,
    WorkCenterActionService,
)


bp = Blueprint(
    "work_center_outcomes",
    __name__,
    url_prefix="/followups/work-center-outcomes",
)


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


def _detail_url(episode_id: str) -> str:
    return url_for("unified_followups.detail", episode_id=episode_id)


def _failure(episode_id: str, error: Exception):
    if isinstance(error, WorkCenterActionError):
        message = error.message
    elif isinstance(error, (ValueError, LookupError)):
        message = str(error)
    else:
        current_app.logger.exception(
            "Unexpected Work Center outcome failure for episode=%s",
            episode_id,
        )
        message = "خطای غیرمنتظره رخ داد؛ دوباره تلاش کنید."
    flash(f"اقدام انجام نشد: {message}", "error")
    return redirect(
        _safe_work_url(request.form.get("current_url"), _detail_url(episode_id))
    )


def _success(episode_id: str, result: dict, message: str):
    if not result.get("projection_refreshed", True):
        flash(
            message + " نمای کار نیازمند تازه‌سازی است.",
            "warning",
        )
    elif result.get("episode_linked") is False:
        flash(
            message + " ارتباط نمای کار در بازخوانی بعدی تکمیل می‌شود.",
            "warning",
        )
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


def _observed_at(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    converted = jalali_to_gregorian_str(raw)
    return f"{converted} 12:00:00" if converted else raw


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
        result = WorkCenterActionService(get_db()).queue_visit_invite(
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
        "دعوت آماده به صف تأیید پیام افزوده شد؛ کار بعدی باز می‌شود.",
    )


__all__ = ["bp"]
