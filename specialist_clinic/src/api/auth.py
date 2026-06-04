import functools
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)

from src.services.auth_service import AuthService
from src.services.activity_logger import log_activity

bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(**kwargs)
    return wrapped_view


def manager_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        if g.user["role"] != "manager":
            flash("دسترسی فقط برای مدیر مجاز است.")
            return redirect(url_for("dashboard.index"))
        return view(**kwargs)
    return wrapped_view


@bp.route("/login", methods=("GET", "POST"))
def login():
    service = AuthService()
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = service.validate_login(username, password)
        if user is None:
            flash("نام کاربری یا رمز عبور نادرست است، یا حساب موقتاً قفل شده است.")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            log_activity("login", f'ورود {user["username"]}', user_id=user["id"], username=user["username"])
            return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    if g.user:
        log_activity("logout", f'خروج {g.user["username"]}', user_id=g.user["id"], username=g.user["username"])
    session.clear()
    return redirect(url_for("auth.login"))
