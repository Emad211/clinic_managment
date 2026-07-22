"""Ownership-aware replacements for legacy patient mutation endpoints.

The public URLs and Flask endpoint names stay stable. This module is installed after
the historical patients blueprint and replaces only handlers whose old implementation
mutated a row by its global id without rechecking the patient id in the URL.
"""
from __future__ import annotations

from flask import flash, g, redirect, request, url_for

from src.adapters.sqlite.patients_repo import PatientRepository
from src.api.auth import login_required
from src.common.utils import jalali_to_gregorian_str
from src.services.activity_logger import log_activity


def _patient_redirect(pid: int, anchor: str = ""):
    return redirect(url_for("patients.detail", pid=pid) + anchor)


@login_required
def remove_condition(pid: int, pc_id: int):
    try:
        changed = PatientRepository().remove_condition(
            pc_id,
            patient_link_id=pid,
        )
    except (LookupError, ValueError) as exc:
        flash(f"تشخیص تغییر نکرد: {exc}", "error")
    else:
        if changed:
            log_activity(
                "condition_resolve",
                f"بستن تشخیص patient_condition={pc_id}",
                patient_link_id=pid,
            )
            flash("تشخیص به‌صورت تاریخی بسته شد و حذف نشد.", "success")
    return _patient_redirect(pid, "#record")


@login_required
def stop_medication(pid: int, med_id: int):
    end_date = jalali_to_gregorian_str(request.form.get("end_date", "")) or None
    try:
        changed = PatientRepository().stop_medication(
            med_id,
            end_date=end_date,
            created_by=g.user["username"],
            patient_link_id=pid,
        )
    except (LookupError, ValueError) as exc:
        flash(f"دارو قطع نشد: {exc}", "error")
    else:
        if changed:
            log_activity(
                "medication_stop",
                f"قطع دارو medication={med_id}",
                patient_link_id=pid,
            )
            flash("قطع دارو با تاریخ مؤثر ثبت شد.", "success")
    return _patient_redirect(pid, "#meds")


@login_required
def change_dose(pid: int, med_id: int):
    new_dose = request.form.get("dose", "").strip()
    if not new_dose:
        flash("دوز جدید الزامی است.", "error")
        return _patient_redirect(pid, "#meds")
    try:
        PatientRepository().change_dose(
            med_id,
            new_dose,
            change_date=(
                jalali_to_gregorian_str(request.form.get("change_date", ""))
                or None
            ),
            note=request.form.get("note") or None,
            created_by=g.user["username"],
            patient_link_id=pid,
        )
    except (LookupError, ValueError) as exc:
        flash(f"دوز تغییر نکرد: {exc}", "error")
    else:
        log_activity(
            "medication_dose",
            f"تغییر دوز medication={med_id} به {new_dose}",
            patient_link_id=pid,
        )
        flash("تغییر دوز در timeline دارویی ثبت شد.", "success")
    return _patient_redirect(pid, "#meds")


@login_required
def delete_allergy(pid: int, allergy_id: int):
    try:
        changed = PatientRepository().delete_allergy(
            allergy_id,
            patient_link_id=pid,
        )
    except (LookupError, ValueError) as exc:
        flash(f"حساسیت تغییر نکرد: {exc}", "error")
    else:
        if changed:
            log_activity(
                "allergy_resolve",
                f"بستن حساسیت allergy={allergy_id}",
                patient_link_id=pid,
            )
            flash("حساسیت به‌صورت تاریخی بسته شد و حذف نشد.", "success")
    return _patient_redirect(pid, "#record")


def install(app) -> None:
    """Replace four already-registered endpoint callables, keeping URL contracts."""
    replacements = {
        "patients.remove_condition": remove_condition,
        "patients.stop_medication": stop_medication,
        "patients.change_dose": change_dose,
        "patients.delete_allergy": delete_allergy,
    }
    missing = sorted(
        endpoint
        for endpoint in replacements
        if endpoint not in app.view_functions
    )
    if missing:
        raise RuntimeError(
            "patient mutation guard installation is incomplete: "
            + ", ".join(missing)
        )
    app.view_functions.update(replacements)
