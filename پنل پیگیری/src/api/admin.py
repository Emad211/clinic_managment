"""Manager pages (docs/06 §6): reports, audit log, procedure names, call texts, health, stop."""
from __future__ import annotations

import threading

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from ..app_context import get_db, now, runtime
from ..common.jalali import jalali_date, jalali_month_start
from ..domain import categories as cat
from ..services import admin
from .security import is_local_request, login_required, principal

bp = Blueprint("admin", __name__)


def _today_range() -> str:
    """From the 1st of the current JALALI month to today ('this month' for the clinic)."""
    t = now().date()
    return f"{jalali_date(jalali_month_start(t))} - {jalali_date(t)}"


# ------------------------------------------------------------------ reports
@bp.get("/reports")
@login_required("manager", "director")
def report_page():
    return render_template("report.html", default_range=_today_range())


@bp.get("/api/reports/followup")
@login_required("manager", "director")
def report_api():
    try:
        start, end = admin.parse_range(request.args.get("range", ""))
    except admin.AdminError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(admin.report(get_db(), start, end))


# ------------------------------------------------------------------ audit log
@bp.get("/manager/audit")
@login_required("manager")
def audit_page():
    return render_template("audit.html", default_range=_today_range())


@bp.get("/api/manager/audit")
@login_required("manager")
def audit_api():
    try:
        start, end = admin.parse_range(request.args.get("range", ""))
        page = max(0, int(request.args.get("page", 0)))
    except (admin.AdminError, ValueError) as exc:
        return jsonify(error=str(exc) if isinstance(exc, admin.AdminError) else "صفحهٔ نامعتبر"), 400
    return jsonify(admin.audit(get_db(), start=start, end=end, actor=request.args.get("actor", "").strip(),
                               action=request.args.get("action", "").strip(), page=page))


# ------------------------------------------------------------------ settings: procedure names, call texts
@bp.get("/manager/settings")
@login_required("manager")
def settings_page():
    conn = get_db()
    return render_template("settings.html", procedures=admin.procedure_names(conn), texts=admin.call_texts(conn),
                           categories=[(c, cat.LABELS_FA[c]) for c in admin.MAPPABLE])


@bp.post("/manager/settings/procedure")
@login_required("manager")
def map_procedure():
    try:
        n = admin.map_procedure(get_db(), request.form.get("name", ""), request.form.get("choice", ""),
                                actor=principal().actor, now=now())
    except admin.AdminError as exc:
        flash(str(exc), "error")
    else:
        flash(f"ذخیره شد؛ دستهٔ {n} ردیف به‌روز شد" if n else "ذخیره شد", "ok")
    return redirect(url_for("admin.settings_page") + "#procedures")


@bp.post("/manager/settings/call-text")
@login_required("manager")
def save_call_text():
    try:
        admin.save_call_text(get_db(), request.form.get("purpose", ""), request.form.get("text", ""),
                             actor=principal().actor, now=now())
    except admin.AdminError as exc:
        flash(str(exc), "error")
    else:
        flash("متن تماس ذخیره شد", "ok")
    return redirect(url_for("admin.settings_page") + "#call-texts")


# ------------------------------------------------------------------ health, backup, stop
@bp.get("/manager/health")
@login_required("manager")
def health_page():
    rt = runtime()
    return render_template("health.html", h=admin.health(get_db(), rt.settings, rt.bridge, rt.monitor, now()),
                           can_stop=is_local_request() and rt.stop_server is not None)


@bp.post("/manager/backup")
@login_required("manager")
def backup_now():
    result = runtime().maintenance.run_once(force=True)
    flash(f"پشتیبان گرفته شد: {result['backup']}", "ok")
    return redirect(url_for("admin.health_page"))


@bp.post("/manager/stop")
@login_required("manager")
def stop():
    rt = runtime()
    if not is_local_request():
        abort(403)                          # only from the main PC (docs/02 §7)
    if rt.stop_server is None:
        flash("توقف از این حالت اجرا ممکن نیست", "error")
        return redirect(url_for("admin.health_page"))
    admin.record_stop(get_db(), actor=principal().actor, now=now())
    threading.Timer(0.5, rt.stop_server).start()
    return render_template("stopped.html")
