"""Focused, catalog-backed mutations for the native Patient Workspace.

Legacy patient routes remain available for compatibility. These routes are intentionally
strict: catalog identity is server authoritative and validation failures re-render the
originating tab with submitted values intact.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, flash, g, render_template, request, url_for, redirect

from src.adapters.sqlite.drug_catalog_repo import DrugCatalogRepository
from src.adapters.sqlite.lab_catalog_repo import LabCatalogRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.vitals_repo import VitalsRepository
from src.api.auth import login_required
from src.common.utils import iran_now, jalali_to_gregorian_str, today_str
from src.services.activity_logger import log_activity
from src.services.patient_workspace_service import PatientWorkspaceService, WORKSPACE_TABS


bp = Blueprint(
    "patient_workspace_mutations",
    __name__,
    url_prefix="/patients",
)


def _workspace_url(pid: int, tab: str) -> str:
    return url_for("patient_workspace.detail", pid=int(pid), tab=tab)


def _render_error(
    pid: int,
    *,
    tab: str,
    errors: list[str],
    form_state: dict,
):
    context = PatientWorkspaceService().build(pid)
    if context is None:
        flash("بیمار یافت نشد", "error")
        return redirect(url_for("patients.list_patients"))
    return (
        render_template(
            "patients/workspace.html",
            active_page="patients",
            active_tab=tab,
            workspace_tabs=WORKSPACE_TABS,
            legacy_url=url_for("patients.detail", pid=pid, legacy=1),
            workspace_form_errors=errors,
            workspace_form_state=form_state,
            **context,
        ),
        422,
    )


def _text(name: str) -> str:
    return str(request.form.get(name) or "").strip()


@bp.post("/<int:pid>/workspace/medications")
@login_required
def add_medication(pid: int):
    catalog_id = request.form.get("drug_catalog_id", type=int)
    dose_choice = _text("dose_choice")
    dose_custom = _text("dose_custom")
    schedule = _text("schedule")
    refill_interval = _text("refill_interval")
    notes = _text("notes")
    state = {
        "drug_catalog_id": str(catalog_id or ""),
        "dose_choice": dose_choice,
        "dose_custom": dose_custom,
        "schedule": schedule,
        "refill_interval": refill_interval,
        "notes": notes,
    }
    errors: list[str] = []

    catalog = DrugCatalogRepository().get(catalog_id) if catalog_id else None
    if not catalog or not int(catalog.get("is_active") or 0):
        errors.append("یک داروی فعال از فهرست انتخاب کنید.")

    dose = None
    if catalog:
        standard_doses = [str(value).strip() for value in catalog.get("doses") or []]
        if dose_choice == "__custom__":
            dose = dose_custom
            if not dose:
                errors.append("دوز سفارشی را وارد کنید.")
        elif standard_doses:
            if dose_choice not in standard_doses:
                errors.append("دوز انتخاب‌شده با فهرست استاندارد این دارو سازگار نیست.")
            else:
                dose = dose_choice
        else:
            dose = dose_custom or dose_choice or None

    if refill_interval and refill_interval not in {"15", "30", "60", "90"}:
        errors.append("فاصلهٔ تجدید نسخه معتبر نیست.")

    if errors:
        return _render_error(
            pid,
            tab="meds",
            errors=errors,
            form_state={"medication": state},
        )

    refill_due_date = None
    if refill_interval:
        refill_due_date = (
            iran_now() + timedelta(days=int(refill_interval))
        ).strftime("%Y-%m-%d")

    try:
        PatientRepository().add_medication(
            pid,
            drug_name=str(catalog["generic_fa"]),
            dose=dose,
            schedule=schedule or None,
            start_date=today_str(),
            refill_due_date=refill_due_date,
            notes=notes or None,
            drug_class=str(catalog["drug_class_key"] or "").strip() or None,
            drug_catalog_id=int(catalog["id"]),
            created_by=g.user["username"],
        )
    except ValueError as exc:
        return _render_error(
            pid,
            tab="meds",
            errors=[str(exc)],
            form_state={"medication": state},
        )

    log_activity(
        "medication_add",
        f"افزودن داروی کاتالوگی: {catalog['generic_fa']}",
        patient_link_id=pid,
    )
    flash("دارو از فهرست استاندارد ثبت شد.", "success")
    return redirect(_workspace_url(pid, "meds"))


@bp.post("/<int:pid>/workspace/labs")
@login_required
def add_lab(pid: int):
    test_key = _text("test_key")
    raw_value = _text("value")
    taken_date = _text("taken_date")
    notes = _text("notes")
    state = {
        "test_key": test_key,
        "value": raw_value,
        "taken_date": taken_date,
        "notes": notes,
    }
    errors: list[str] = []

    catalog = LabCatalogRepository().get(test_key) if test_key else None
    if not catalog or not int(catalog.get("is_active") or 0):
        errors.append("یک آزمایش فعال از فهرست انتخاب کنید.")

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = None
        errors.append("مقدار عددی آزمایش را وارد کنید.")

    taken = None
    if taken_date:
        taken = jalali_to_gregorian_str(taken_date)
        if not taken:
            errors.append("تاریخ آزمایش معتبر نیست.")

    if errors:
        return _render_error(
            pid,
            tab="clinical",
            errors=errors,
            form_state={"lab": state},
        )

    VitalsRepository().add_lab(
        pid,
        test_name=str(catalog["name_fa"]),
        test_key=str(catalog["test_key"]),
        value=value,
        unit=str(catalog.get("unit") or "").strip() or None,
        ref_low=catalog.get("ref_low"),
        ref_high=catalog.get("ref_high"),
        taken_at=f"{taken} 12:00:00" if taken else None,
        notes=notes or None,
        recorded_by=g.user["username"],
    )
    log_activity(
        "lab_add",
        f"ثبت آزمایش کاتالوگی: {catalog['test_key']}",
        patient_link_id=pid,
    )
    flash("آزمایش با واحد و محدودهٔ مرجع استاندارد ثبت شد.", "success")
    return redirect(_workspace_url(pid, "clinical"))


__all__ = ["bp"]
