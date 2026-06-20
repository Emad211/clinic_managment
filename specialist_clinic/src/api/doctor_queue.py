"""Physician visit-queue panel (phase3_doctor_queue_plan.md).

Live queue of today's OPEN visit invoices (read from the accounting bridge, read-only) +
the specialist-side در‌نوبت/انجام‌شده state. "پایانِ ویزیت" records physician-side state only;
it does NOT close the accounting invoice (reception does that). No SQL here — see the
service / repo. Staff role (the physician is a staff user).
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from src.api.auth import login_required
from src.services.doctor_queue_service import DoctorQueueService
from src.adapters.sqlite.patients_repo import PatientRepository
from src.services.activity_logger import log_activity
from src.common.utils import jalali_to_gregorian_str, today_str

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
    snap = _snapshot(invoice_id)
    DoctorQueueService().start(snap)
    log_activity("visit_start", f"شروع ویزیتِ فاکتور #{invoice_id}")
    return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id, nid=snap["national_id"] or ""))


@bp.route("/<int:invoice_id>/done", methods=["POST"])
@login_required
def done(invoice_id):
    DoctorQueueService().end_visit(_snapshot(invoice_id), g.user["username"],
                                   notes=request.form.get("notes") or None)
    log_activity("visit_done", f"پایانِ ویزیتِ فاکتور #{invoice_id}")
    return redirect(url_for("doctor_queue.index"))


@bp.route("/<int:invoice_id>/visit")
@login_required
def visit(invoice_id):
    """Simple visit view for an ENROLLED patient: compact previous info + quick data entry
    + the «مرحله بعد» menu. Read-only w.r.t. accounting."""
    nid = (request.args.get("nid") or "").strip() or None
    link = PatientRepository().get_by_national_id(nid) if nid else None
    if not link:
        flash("این بیمار در پروندهٔ تخصصی ثبت نشده — از «پایانِ ویزیت» در صف استفاده کنید.")
        return redirect(url_for("doctor_queue.index"))
    pid = link["id"]
    from src.services.patient_service import PatientService
    from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
    from src.adapters.sqlite.record_repo import RecordRepository
    from src.adapters.sqlite.followups_repo import FollowupRepository
    from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
    profile = PatientService().get_full_profile(pid)
    rules = ClinicalRulesRepository()
    codes = [c.get("condition_code") for c in profile["conditions"] if c.get("condition_code")]
    entry_indicators = [i for i in rules.for_conditions(codes) if i.get("is_vital")]
    ind_labels = {i["key"]: i for i in rules.all_indicators(active_only=False)}
    recent_vitals = VitalsRepository().get_readings(pid, limit=8)
    for v in recent_vitals:
        meta = ind_labels.get(v["type"]) or VITAL_TYPES.get(v["type"], {})
        v["type_label"] = meta.get("label", v["type"])
    notes = RecordRepository().list_notes(pid, "exam")
    open_followups = [t for t in FollowupRepository().list_for_patient(pid) if t.get("status") == "open"]
    return render_template(
        "doctor_queue/visit_quick.html", active_page="doctor_queue",
        invoice_id=invoice_id, nid=nid, pid=pid, work_date=today_str(),
        patient=profile["patient"], conditions=profile["conditions"],
        medications=profile["medications"], allergies=profile["allergies"],
        entry_indicators=entry_indicators, recent_vitals=recent_vitals,
        last_note=(notes[0] if notes else None), open_followups=open_followups)


@bp.route("/<int:invoice_id>/save", methods=["POST"])
@login_required
def save(invoice_id):
    """Save today's vitals + visit note (reusing the vitals/record repos), then return to
    the visit view so the physician stays in the visit flow."""
    pid = request.form.get("pid", type=int)
    nid = request.form.get("nid") or ""
    if pid:
        from src.adapters.sqlite.vitals_repo import VitalsRepository, VITAL_TYPES
        from src.adapters.sqlite.clinical_rules_repo import ClinicalRulesRepository
        from src.adapters.sqlite.record_repo import RecordRepository
        measured = jalali_to_gregorian_str(request.form.get("measured_date", ""))
        measured_at = f"{measured} 12:00:00" if measured else None
        indicators = ClinicalRulesRepository().as_map()
        keys = set(indicators.keys()) | set(VITAL_TYPES.keys())
        vrepo = VitalsRepository()
        added = 0
        for vtype in keys:
            raw = (request.form.get(vtype, "") or "").strip()
            if raw == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            unit = (indicators.get(vtype) or {}).get("unit") or VITAL_TYPES.get(vtype, {}).get("unit")
            vrepo.add_reading(pid, vtype=vtype, value=value, unit=unit,
                              measured_at=measured_at, recorded_by=g.user["username"])
            added += 1
        note = (request.form.get("note") or "").strip()
        if note:
            RecordRepository().add_note(pid, "exam", note, recorded_by=g.user["username"])
        if added or note:
            log_activity("visit_save", f"ثبت {added} شاخص + یادداشت ویزیت", patient_link_id=pid)
            flash("اطلاعاتِ ویزیت ثبت شد", "success")
    return redirect(url_for("doctor_queue.visit", invoice_id=invoice_id, nid=nid))
