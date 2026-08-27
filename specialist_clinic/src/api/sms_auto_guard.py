"""Explicit manager surface for FOUX-V1 FO-6 governed CARE SMS."""
from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.security.permissions import Permission, permission_required
from src.services.sms.auto_guard_service import (
    ALLOWLIST,
    POLICY_LEVELS,
    REASON_LABELS,
    SmsAutoGuardError,
    SmsAutoGuardService,
)


bp = Blueprint("sms_auto_guard", __name__, url_prefix="/sms/auto-guard")


def _require_flag() -> None:
    if not current_app.config.get("FOLLOWUP_SMS_AUTO_GUARDED", False):
        abort(404)


def _redirect():
    return redirect(url_for("sms_auto_guard.index"))


def _view_model(status: dict) -> dict:
    policy = status.get("policy") or {}
    templates = status.get("templates") or {}
    candidates = []
    counts: dict[str, int] = {}
    for item in status.get("candidates", []):
        state = str(item.get("state") or "UNKNOWN")
        counts[state] = counts.get(state, 0) + 1
        candidates.append(
            {
                "id": int(item["id"]),
                "patient_link_id": int(item["patient_link_id"]),
                "event_key": str(item["event_key"]),
                "period_key": str(item["period_key"]),
                "generation_no": int(item["generation_no"]),
                "provider_name": str(item["provider_name"]),
                "created_at": str(item["created_at"]),
                "expires_at": str(item["expires_at"]),
                "state": state,
                "snapshot_short": str(item["snapshot_hash"])[:12],
            }
        )
    decisions = []
    for item in status.get("decisions", []):
        reason = str(item.get("reason_code") or "")
        decisions.append(
            {
                "id": int(item["id"]),
                "candidate_id": int(item["candidate_id"]),
                "decision_type": str(item["decision_type"]),
                "attempt_no": int(item.get("attempt_no") or 0),
                "reason_code": reason,
                "reason_label": REASON_LABELS.get(reason, reason),
                "message_id": item.get("message_id"),
                "recorded_at": str(item["recorded_at"]),
            }
        )
    return {
        "storage_ready": bool(status.get("storage_ready")),
        "feature_enabled": bool(status.get("feature_enabled")),
        "policy": {
            "id": policy.get("id"),
            "version": policy.get("version"),
            "created_at": policy.get("created_at"),
            "hash_short": str(policy.get("content_hash") or "")[:12],
        },
        "templates": {
            key: {
                "id": (value or {}).get("id"),
                "version": (value or {}).get("version"),
                "approved_at": (value or {}).get("approved_at"),
                "hash_short": str((value or {}).get("content_hash") or "")[:12],
            }
            for key, value in templates.items()
        },
        "candidates": candidates,
        "decisions": decisions,
        "counts": counts,
    }


@bp.after_request
def no_shared_cache(response):
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/")
@permission_required(Permission.SMS_APPROVAL_REVIEW)
def index():
    status = SmsAutoGuardService(get_db()).status(limit=200)
    return render_template(
        "sms/auto_guard.html",
        model=_view_model(status),
        allowlist=ALLOWLIST,
        policy_levels=POLICY_LEVELS,
        active_page="sms",
        hub_pending=0,
    )


@bp.post("/publish")
@permission_required(Permission.SMS_SETTINGS_MANAGE)
def publish():
    _require_flag()
    ttl_hours = request.form.get("ttl_hours", type=int) or 24
    try:
        result = SmsAutoGuardService(get_db()).publish_current_contract(
            actor_username=str(g.user["username"]),
            ttl_hours=ttl_hours,
        )
    except SmsAutoGuardError as exc:
        flash(f"قرارداد منتشر نشد: {exc.message}", "error")
    else:
        flash(
            "نسخهٔ محافظت‌شده ثبت شد؛ "
            f"سیاست {result['policy_version']} و "
            f"{result['templates_created']} قالب جدید.",
            "success",
        )
    return _redirect()


@bp.post("/collect")
@permission_required(Permission.SMS_SETTINGS_MANAGE)
def collect():
    _require_flag()
    limit = min(max(request.form.get("limit", type=int) or 100, 1), 500)
    try:
        result = SmsAutoGuardService(get_db()).collect_candidates(
            actor_username=str(g.user["username"]),
            limit=limit,
        )
    except SmsAutoGuardError as exc:
        flash(f"جمع‌آوری انجام نشد: {exc.message}", "error")
    else:
        counts = result.get("counts") or {}
        flash(
            "جمع‌آوری پایان یافت؛ "
            f"جدید: {counts.get('created', 0)}، "
            f"بدون تغییر: {counts.get('reused', 0)}.",
            "success",
        )
    return _redirect()


@bp.post("/execute")
@permission_required(Permission.SMS_SETTINGS_MANAGE)
def execute():
    _require_flag()
    service = SmsAutoGuardService(get_db())
    candidate_id = request.form.get("candidate_id", type=int)
    if candidate_id:
        result = service.execute_candidate(
            candidate_id,
            actor_username=str(g.user["username"]),
        )
        if result.get("ok"):
            flash("نامزد پس از بازبینی کامل به پنل تحویل شد.", "success")
        else:
            reason = str(result.get("reason") or "UNKNOWN")
            flash(
                f"ارسال متوقف شد: {REASON_LABELS.get(reason, reason)}",
                "warning",
            )
    else:
        limit = min(max(request.form.get("limit", type=int) or 10, 1), 50)
        try:
            result = service.execute_pending(
                actor_username=str(g.user["username"]),
                limit=limit,
            )
        except SmsAutoGuardError as exc:
            flash(f"اجرای محدود انجام نشد: {exc.message}", "error")
        else:
            flash(
                f"بررسی‌شده: {result['attempted']}، "
                f"پذیرفته‌شده: {result['accepted']}، "
                f"متوقف/ناموفق: {result['denied_or_failed']}.",
                "success",
            )
    return _redirect()


__all__ = ["bp"]
