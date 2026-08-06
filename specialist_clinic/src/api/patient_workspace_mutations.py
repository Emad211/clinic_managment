"""Focused mutations for the native Patient Workspace.

Catalog identity and patient identity are server authoritative. Validation failures
re-render the originating tab with submitted values intact.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.drug_catalog_repo import DrugCatalogRepository
from src.adapters.sqlite.lab_catalog_repo import LabCatalogRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.adapters.sqlite.vitals_repo import VitalsRepository
from src.api.auth import login_required
from src.common.utils import iran_now, jalali_to_gregorian_str, today_str
from src.services.activity_logger import log_activity
from src.services.patient_data_quality_service import PatientDataQualityService
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
    context["data_quality"] = PatientDataQualityService(get_db()).build(pid)
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


def _phone(value: object) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


@bp.post("/<int:pid>/workspace/identity")
@login_required
def update_identity(pid: int):
    state = {
        "full_name": _text("full_name"),
        "phone_number": _phone(request.form.get("phone_number")),
        "national_id": _text("national_id"),
        "birthdate": _text("birthdate"),
        "gender": _text("gender"),
        "address": _text("address"),
    }
    errors: list[str] = []
    if not state["full_name"]:
        errors.append("نام و نام خانوادگی الزامی است.")
    if state["phone_number"] and len(state["phone_number"]) < 10:
        errors.append("شماره موبایل معتبر نیست.")
    if state["national_id"] and not state["national_id"].isdigit():
        errors.append("کد ملی فقط باید شامل رقم باشد.")
    if state["national_id"] and len(state["national_id"]) != 10:
        errors.append("کد ملی باید ۱۰ رقم باشد.")
    if state["gender"] and state["gender"] not in {"male", "female", "other"}:
        errors.append("جنسیت انتخاب‌شده معتبر نیست.")

    birthdate = None
    if state["birthdate"]:
        birthdate = jalali_to_gregorian_str(state["birthdate"])
        if not birthdate:
            errors.append("تاریخ تولد معتبر نیست.")

    db = get_db()
    if state["national_id"]:
        duplicate = db.execute(
            """SELECT id,full_name FROM patient_links
               WHERE national_id=? AND id<>? AND is_active=1 LIMIT 1""",
            (state["national_id"], int(pid)),
        ).fetchone()
        if duplicate:
            errors.append(
                f"این کد ملی در پرونده «{duplicate['full_name']}» ثبت شده است."
            )
    if state["phone_number"]:
        duplicate = db.execute(
            """SELECT id,full_name FROM patient_links
               WHERE id<>? AND is_active=1
                 AND REPLACE(REPLACE(REPLACE(REPLACE(
                   COALESCE(phone_number,''),' ',''),'-',''),'(',''),')','')=?
               LIMIT 1""",
            (int(pid), state["phone_number"]),
        ).fetchone()
        if duplicate:
            errors.append(
                f"این شماره موبایل در پرونده «{duplicate['full_name']}» ثبت شده است."
            )

    if errors:
        return _render_error(
            pid,
            tab="summary",
            errors=errors,
            form_state={"identity": state},
        )

    db.execute(
        """UPDATE patient_links
           SET full_name=?,phone_number=?,national_id=?,birthdate=?,gender=?,
               address=?,updated_at=datetime('now','+3 hours','+30 minutes')
           WHERE id=?""",
        (
            state["full_name"],
            state["phone_number"] or None,
            state["national_id"] or None,
            birthdate,
            state["gender"] or None,
            state["address"] or None,
            int(pid),
        ),
    )
    db.commit()
    log_activity(
        "patient_identity_update",
        "اصلاح هویت و اطلاعات تماس از فضای کاری بیمار",
        patient_link_id=pid,
    )
    flash("اطلاعات هویتی و تماس به‌روزرسانی شد.", "success")
    return redirect(_workspace_url(pid, "summary") + "#workspace-identity-editor")


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
