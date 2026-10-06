"""Shared header data, shift override, doctor queue, reception home."""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from ..app_context import get_db, now, runtime
from ..common.jalali import gregorian_from_jalali, jalali_date, jalali_long
from ..services import queue as queue_service
from ..services import shift as shift_service
from ..services.sync_status import status as sync_status
from .security import home_for, login_required, principal

bp = Blueprint("pages", __name__)
doctor_bp = Blueprint("doctor", __name__)
reception_bp = Blueprint("reception", __name__)


def header_state() -> dict:
    conn = get_db()
    shift = shift_service.current(conn, now())
    sync = sync_status(conn, runtime().bridge, now())
    return {
        "shift": {"work_date": shift.work_date, "work_date_fa": jalali_date(shift.work_date),
                  "work_date_long": jalali_long(shift.work_date),
                  "shift": shift.shift, "label": shift.label, "source": shift.source},
        "sync": {"color": sync.color, "age_seconds": sync.age_seconds, "message": sync.message},
    }


@bp.get("/")
def index():
    p = principal()
    return redirect(url_for(home_for(p)) if p else url_for("auth.login"))


@bp.get("/api/status")
@login_required()
def api_status():
    return jsonify(header_state())


@bp.post("/api/shift")
@login_required()
def api_shift():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    if data.get("clear"):
        shift_service.clear_override(conn, actor=principal().actor, now=now())
    else:
        try:
            work_date = gregorian_from_jalali(str(data.get("work_date_fa", "")))
            shift_service.set_override(conn, work_date, str(data.get("shift", "")),
                                       actor=principal().actor, now=now())
        except (ValueError, shift_service.ShiftError) as exc:
            return jsonify(error=str(exc)), 400
    return jsonify(header_state())


# ---------------------------------------------------------------- doctor
@doctor_bp.get("/doctor")
@login_required("doctor")
def queue_page():
    return render_template("doctor_queue.html")


@doctor_bp.get("/api/doctor/queue")
@login_required("doctor")
def queue_api():
    conn = get_db()
    shift = shift_service.current(conn, now())
    rows = queue_service.doctor_queue(conn, principal().staff_id, shift)
    return jsonify(
        shift={"label": shift.label, "work_date_long": jalali_long(shift.work_date)},
        total=len(rows),
        pending=sum(r.status == queue_service.STATUS_PENDING for r in rows),
        rows=[{**asdict(r), "status_label": r.status_label} for r in rows],
    )


# ---------------------------------------------------------------- reception (tabs arrive in M2/M4)
@reception_bp.get("/reception")
@login_required("reception")
def home():
    return render_template("reception_home.html")
