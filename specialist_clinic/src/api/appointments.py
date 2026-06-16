from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from src.api.auth import login_required
from src.adapters.sqlite.appointments_repo import AppointmentRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.services.appointment_service import AppointmentService
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str, iran_now, format_jalali_datetime

bp = Blueprint("appointments", __name__, url_prefix="/appointments")

APPT_TYPES = {'visit': 'ویزیت', 'lab': 'آزمایش', 'checkup': 'چکاپ دوره‌ای'}
STATUS_FA = {'scheduled': 'برنامه‌ریزی‌شده', 'done': 'انجام‌شده',
             'no_show': 'غیبت', 'cancelled': 'لغوشده'}


@bp.route("/")
@login_required
def list_appointments():
    # Default window: today .. +30 days
    df = jalali_to_gregorian_str(request.args.get("from", "")) or iran_now().strftime('%Y-%m-%d')
    dt = jalali_to_gregorian_str(request.args.get("to", "")) or (iran_now() + timedelta(days=30)).strftime('%Y-%m-%d')
    status = request.args.get("status") or None
    appts = AppointmentRepository().list_range(df, dt, status)
    today = iran_now().strftime('%Y-%m-%d')
    for a in appts:
        a['type_fa'] = APPT_TYPES.get(a.get('appt_type'), a.get('appt_type') or '—')
        a['status_fa'] = STATUS_FA.get(a.get('status'), a.get('status'))
        a['scheduled_fa'] = format_jalali_datetime(a['scheduled_at'])
        a['is_today'] = str(a['scheduled_at'])[:10] == today
    summary = {
        'today': sum(1 for a in appts if a['is_today']),
        'scheduled': sum(1 for a in appts if a['status'] == 'scheduled'),
        'done': sum(1 for a in appts if a['status'] == 'done'),
        'no_show': sum(1 for a in appts if a['status'] == 'no_show'),
        'total': len(appts),
    }
    return render_template("appointments/list.html", appointments=appts, status_fa=STATUS_FA,
                           active_page='appointments', summary=summary, active_status=status or '')


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_appointment():
    repo = PatientRepository()
    if request.method == "POST":
        pid = request.form.get("patient_link_id", type=int)
        date_g = jalali_to_gregorian_str(request.form.get("date", ""))
        time_s = request.form.get("time", "12:00").strip() or "12:00"
        if not pid or not date_g:
            flash("بیمار و تاریخ الزامی است")
            return redirect(url_for("appointments.new_appointment"))
        scheduled_at = f"{date_g} {time_s}:00"
        rec = request.form.get("recurrence_months", type=int)
        appt_id = AppointmentService().schedule(
            pid, scheduled_at=scheduled_at,
            appt_type=request.form.get("appt_type") or 'visit',
            notes=request.form.get("notes") or None,
            recurrence_months=rec or None,
            created_by=g.user["username"],
        )
        log_activity("appointment_create", "ثبت نوبت", patient_link_id=pid)
        flash("نوبت ثبت شد", "success")
        return redirect(url_for("appointments.list_appointments"))

    pre_pid = request.args.get("patient_link_id", type=int)
    patients = repo.list_patients()
    return render_template("appointments/new.html", patients=patients, appt_types=APPT_TYPES,
                           pre_pid=pre_pid, active_page='appointments')


@bp.route("/<int:appt_id>/status", methods=["POST"])
@login_required
def set_status(appt_id):
    status = request.form.get("status")
    svc = AppointmentService()
    if status == 'done':
        svc.mark_done(appt_id, created_by=g.user["username"])
    elif status in ('no_show', 'cancelled', 'scheduled'):
        svc.set_status(appt_id, status)
    log_activity("appointment_status", f"تغییر وضعیت نوبت به {STATUS_FA.get(status, status)}")
    return redirect(request.referrer or url_for("appointments.list_appointments"))
