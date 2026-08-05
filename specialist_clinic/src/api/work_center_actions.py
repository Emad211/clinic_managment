"""Focused mutation endpoints used by the Work Center workspace."""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlsplit

from flask import Blueprint, flash, g, redirect, request, url_for

from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now, jalali_to_gregorian_str
from src.security.permissions import (
    Permission,
    permission_required,
    resolved_permissions,
)
from src.services.activity_logger import log_activity
from src.services.followup_orchestration.work_center_action_service import (
    WorkCenterActionError,
    WorkCenterActionService,
)


bp = Blueprint(
    "work_center_actions",
    __name__,
    url_prefix="/followups/work-center-actions",
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


def _failure_redirect(episode_id: str):
    return redirect(
        _safe_work_url(request.form.get("current_url"), _detail_url(episode_id))
    )


def _success_redirect(episode_id: str):
    fallback = url_for("unified_followups.index")
    next_url = _safe_work_url(request.form.get("next_url"), "")
    if next_url:
        return redirect(next_url)
    return redirect(
        _safe_work_url(request.form.get("return_url"), fallback)
    )


def _future_from_form(*, prefix: str, allow_days: bool) -> str:
    if allow_days:
        days = request.form.get(f"{prefix}_days", type=int)
        if days:
            target = iran_now().replace(
                hour=9,
                minute=0,
                second=0,
                microsecond=0,
            ) + timedelta(days=max(days, 1))
            if target.tzinfo is not None:
                target = target.replace(tzinfo=None)
            return target.isoformat(sep=" ", timespec="seconds")

    date_j = str(request.form.get(f"{prefix}_date") or "").strip()
    time_s = str(request.form.get(f"{prefix}_time") or "09:00").strip() or "09:00"
    date_g = jalali_to_gregorian_str(date_j)
    if not date_g:
        raise WorkCenterActionError(
            "INVALID_ACTION_DATE",
            "تاریخ انتخاب‌شده معتبر نیست.",
        )
    try:
        clock = datetime.strptime(time_s, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise WorkCenterActionError(
            "INVALID_ACTION_TIME",
            "ساعت انتخاب‌شده معتبر نیست.",
        ) from exc
    return f"{date_g} {clock}:00"


def _action_error(error: Exception, episode_id: str):
    message = error.message if isinstance(error, WorkCenterActionError) else str(error)
    flash(f"اقدام انجام نشد: {message}", "error")
    return _failure_redirect(episode_id)


@bp.post("/<episode_id>/defer")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def defer(episode_id: str):
    try:
        result = WorkCenterActionService(get_db()).defer(
            episode_id,
            due_at=_future_from_form(prefix="defer", allow_days=True),
            actor_username=str(g.user["username"]),
            actor_user_id=int(g.user["id"]),
            permissions=resolved_permissions(g.user),
            idempotency_key=request.form.get("idempotency_key") or "",
            note=request.form.get("note") or None,
        )
    except Exception as error:
        return _action_error(error, episode_id)
    log_activity(
        "work_center_defer",
        f"episode={episode_id} task={result['task_id']} due={result['due_at']}",
    )
    flash("موعد اقدام بعدی ثبت شد؛ کار بعدی باز می‌شود.", "success")
    return _success_redirect(episode_id)


@bp.post("/<episode_id>/book")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def book(episode_id: str):
    try:
        result = WorkCenterActionService(get_db()).book(
            episode_id,
            scheduled_at=_future_from_form(prefix="booking", allow_days=False),
            actor_username=str(g.user["username"]),
            actor_user_id=int(g.user["id"]),
            permissions=resolved_permissions(g.user),
            idempotency_key=request.form.get("idempotency_key") or "",
        )
    except Exception as error:
        return _action_error(error, episode_id)
    log_activity(
        "work_center_book",
        f"episode={episode_id} appointment={result['appointment_id']}",
    )
    flash(
        f"نوبت #{result['appointment_id']} ثبت شد؛ کار بعدی باز می‌شود.",
        "success",
    )
    return _success_redirect(episode_id)


@bp.post("/<episode_id>/complete")
@permission_required(Permission.CLINICAL_TASK_VIEW)
def complete(episode_id: str):
    try:
        result = WorkCenterActionService(get_db()).complete_administrative(
            episode_id,
            actor_username=str(g.user["username"]),
            permissions=resolved_permissions(g.user),
            note=request.form.get("note") or None,
        )
    except Exception as error:
        return _action_error(error, episode_id)
    log_activity(
        "work_center_complete",
        f"episode={episode_id} task={result['task_id']} status=done",
        patient_link_id=result["patient_link_id"],
    )
    flash("کار تکمیل شد؛ کار بعدی باز می‌شود.", "success")
    return _success_redirect(episode_id)


__all__ = ["bp"]
