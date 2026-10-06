"""Manager: doctor accounts (docs/06 §6)."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..app_context import get_db, now, runtime
from ..services import auth as auth_service
from ..services import calls as calls_service
from .security import login_required, principal

bp = Blueprint("manager", __name__)


@bp.get("/manager/doctors")
@login_required("manager")
def doctors():
    conn = get_db()
    accounts, available = auth_service.doctor_accounts(conn)
    all_doctors, followup = calls_service.followup_doctors(conn)
    return render_template("manager_doctors.html", accounts=accounts, available=available,
                           all_doctors=all_doctors, followup=followup)


@bp.post("/manager/followup-doctors")
@login_required("manager")
def followup_doctors():
    try:
        ids = [int(v) for v in request.form.getlist("staff_id")]
        calls_service.set_followup_doctors(get_db(), ids, actor=principal().actor, now=now())
    except (ValueError, calls_service.CallError) as exc:
        flash(str(exc) if isinstance(exc, calls_service.CallError) else "انتخاب نامعتبر است", "error")
    else:
        flash("پزشکان پیگیری ذخیره شدند", "ok")
    return redirect(url_for("manager.doctors"))


@bp.post("/manager/doctors")
@login_required("manager")
def create_doctor():
    f = request.form
    try:
        staff_id = int(f.get("staff_id") or 0)
    except ValueError:
        flash("پزشک انتخاب‌شده نامعتبر است؛ از فهرست انتخاب کنید", "error")
        return redirect(url_for("manager.doctors"))
    try:
        auth_service.create_doctor(
            get_db(), runtime().bridge, username=f.get("username", ""), password=f.get("password", ""),
            staff_id=staff_id, is_director=f.get("is_director") == "1",
            actor=principal().actor, now=now())
    except auth_service.AccountError as exc:
        flash(str(exc), "error")
    else:
        flash("حساب پزشک ساخته شد", "ok")
    return redirect(url_for("manager.doctors"))


@bp.post("/manager/doctors/<int:doctor_id>")
@login_required("manager")
def update_doctor(doctor_id: int):
    f = request.form
    action = f.get("action")
    kwargs: dict = {}
    if action == "director_on":
        kwargs["is_director"] = True
    elif action == "director_off":
        kwargs["is_director"] = False
    elif action == "deactivate":
        kwargs["is_active"] = False
    elif action == "activate":
        kwargs["is_active"] = True
    elif action == "password":
        kwargs["password"] = f.get("password", "")
    else:
        flash("درخواست نامعتبر است", "error")
        return redirect(url_for("manager.doctors"))
    try:
        auth_service.update_doctor(get_db(), doctor_id, actor=principal().actor, now=now(), **kwargs)
    except auth_service.AccountError as exc:
        flash(str(exc), "error")
    else:
        flash({"password": "رمز عوض شد", "deactivate": "حساب غیرفعال شد", "activate": "حساب فعال شد"}
              .get(action, "ذخیره شد"), "ok")
    return redirect(url_for("manager.doctors"))
