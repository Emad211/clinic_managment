import functools

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from src.security.csrf import rotate_csrf_token
from src.security.permissions import Permission, permission_required
from src.services.activity_logger import log_activity
from src.services.auth_service import AuthService


bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(**kwargs)

    return wrapped_view


# Backward-compatible import for existing administrative routes. The route no longer
# knows the concrete role name; authorization resolves through the permission model.
manager_required = permission_required(Permission.SECURITY_GRANT_MANAGE)


@bp.route("/login", methods=("GET", "POST"))
def login():
    service = AuthService()
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = service.validate_login(username, password)
        if user is None:
            flash(
                "نام کاربری یا رمز عبور نادرست است، یا حساب موقتاً قفل شده است."
            )
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session.permanent = True
            rotate_csrf_token()
            log_activity(
                "login",
                f'ورود {user["username"]}',
                user_id=user["id"],
                username=user["username"],
            )
            return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    # Converted to POST after the shared navigation template is migrated. Until then
    # this compatibility GET is deliberately limited to clearing the current session;
    # it performs no clinical or persistent database mutation.
    if g.user:
        log_activity(
            "logout",
            f'خروج {g.user["username"]}',
            user_id=g.user["id"],
            username=g.user["username"],
        )
    session.clear()
    return redirect(url_for("auth.login"))


__all__ = [
    "bp",
    "login_required",
    "manager_required",
    "permission_required",
]
