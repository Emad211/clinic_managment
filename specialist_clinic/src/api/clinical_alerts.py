from __future__ import annotations

import sqlite3

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.engagement_repo import EngagementRepository
from src.security.permissions import Permission, permission_required
from src.services.activity_logger import log_activity
from src.services.clinical_alert_service import (
    ClinicalAlertConflict,
    ClinicalAlertService,
    ClinicalAlertValidationError,
)


bp = Blueprint("clinical_alerts", __name__, url_prefix="/clinical-alerts")


@bp.get("/")
@permission_required(Permission.CLINICAL_ALERT_VIEW)
def index():
    alerts = ClinicalAlertService().list_open()
    return render_template(
        "followups/alerts.html",
        alerts=alerts,
        active_page="sms",
        hub_tab="alerts",
        hub_pending=EngagementRepository().count_pending(),
        alert_pending=len(alerts),
    )


@bp.post("/<int:alert_id>/acknowledge")
@permission_required(Permission.CLINICAL_ALERT_ACKNOWLEDGE)
def acknowledge(alert_id: int):
    try:
        event = ClinicalAlertService().acknowledge(
            alert_id,
            expected_current_event_id=int(
                request.form.get("expected_current_event_id") or 0
            ),
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            assigned_to=request.form.get("assigned_to") or g.user["username"],
            note=request.form.get("note"),
        )
    except (
        LookupError,
        ValueError,
        ClinicalAlertConflict,
        ClinicalAlertValidationError,
        sqlite3.IntegrityError,
    ) as exc:
        flash(f"تأیید مشاهدهٔ هشدار ثبت نشد: {exc}", "error")
    else:
        alert = ClinicalAlertService().current(alert_id)
        log_activity(
            "clinical_alert_acknowledged",
            f"alert={alert_id} event={event['id']}",
            patient_link_id=int(alert["patient_link_id"]),
        )
        flash("مشاهده و مسئولیت پیگیری هشدار ثبت شد.", "success")
    return redirect(request.referrer or url_for("clinical_alerts.index"))


@bp.post("/<int:alert_id>/resolve")
@permission_required(Permission.CLINICAL_ALERT_RESOLVE)
def resolve(alert_id: int):
    try:
        event = ClinicalAlertService().resolve(
            alert_id,
            expected_current_event_id=int(
                request.form.get("expected_current_event_id") or 0
            ),
            decision_event_id=int(request.form.get("decision_event_id") or 0),
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            note=request.form.get("note") or "",
        )
    except (
        LookupError,
        ValueError,
        ClinicalAlertConflict,
        ClinicalAlertValidationError,
        sqlite3.IntegrityError,
    ) as exc:
        flash(f"بستن هشدار ثبت نشد: {exc}", "error")
    else:
        alert = ClinicalAlertService().current(alert_id)
        log_activity(
            "clinical_alert_resolved",
            f"alert={alert_id} event={event['id']} decision={event['decision_event_id']}",
            patient_link_id=int(alert["patient_link_id"]),
        )
        flash("هشدار با تصمیم ثبت‌شدهٔ پزشک بسته شد.", "success")
    return redirect(request.referrer or url_for("clinical_alerts.index"))


@bp.post("/<int:alert_id>/entered-in-error")
@permission_required(Permission.CLINICAL_ALERT_RESOLVE)
def entered_in_error(alert_id: int):
    try:
        event = ClinicalAlertService().enter_in_error(
            alert_id,
            expected_current_event_id=int(
                request.form.get("expected_current_event_id") or 0
            ),
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            note=request.form.get("note") or "",
        )
    except (
        LookupError,
        ValueError,
        ClinicalAlertConflict,
        ClinicalAlertValidationError,
        sqlite3.IntegrityError,
    ) as exc:
        flash(f"اصلاح هشدار ثبت نشد: {exc}", "error")
    else:
        alert = ClinicalAlertService().current(alert_id)
        log_activity(
            "clinical_alert_entered_in_error",
            f"alert={alert_id} event={event['id']}",
            patient_link_id=int(alert["patient_link_id"]),
        )
        flash("هشدار به‌عنوان ثبت اشتباه علامت‌گذاری شد.", "success")
    return redirect(request.referrer or url_for("clinical_alerts.index"))
