"""Physician visit-queue panel (phase3_doctor_queue_plan.md).

Live queue of today's OPEN visit invoices (read from the accounting bridge, read-only) +
the specialist-side در‌نوبت/انجام‌شده state. "پایانِ ویزیت" records physician-side state only;
it does NOT close the accounting invoice (reception does that). No SQL here — see the
service / repo. Staff role (the physician is a staff user).
"""
from flask import Blueprint, render_template, request, redirect, url_for, g

from src.api.auth import login_required
from src.services.doctor_queue_service import DoctorQueueService
from src.adapters.sqlite.patients_repo import PatientRepository
from src.services.activity_logger import log_activity

bp = Blueprint("doctor_queue", __name__, url_prefix="/doctor-queue")


def _snapshot(invoice_id):
    """Build the doctor_visit_log snapshot from the posted queue row; resolve the local
    patient_links id from national_id (so a tampered hidden field can't mis-link)."""
    nid = (request.form.get("national_id") or "").strip() or None
    link = PatientRepository().get_by_national_id(nid) if nid else None
    return {
        "accounting_invoice_id": invoice_id,
        "patient_link_id": link["id"] if link else None,
        "national_id": nid,
        "full_name": request.form.get("full_name") or "—",
        "work_date": request.form.get("work_date") or None,
    }


@bp.route("/")
@login_required
def index():
    data = DoctorQueueService().queue()
    return render_template("doctor_queue/queue.html", active_page="doctor_queue", **data)


@bp.route("/<int:invoice_id>/start", methods=["POST"])
@login_required
def start(invoice_id):
    DoctorQueueService().start(_snapshot(invoice_id))
    log_activity("visit_start", f"شروع ویزیتِ فاکتور #{invoice_id}")
    return redirect(url_for("doctor_queue.index"))


@bp.route("/<int:invoice_id>/done", methods=["POST"])
@login_required
def done(invoice_id):
    DoctorQueueService().end_visit(_snapshot(invoice_id), g.user["username"],
                                   notes=request.form.get("notes") or None)
    log_activity("visit_done", f"پایانِ ویزیتِ فاکتور #{invoice_id}")
    return redirect(url_for("doctor_queue.index"))
