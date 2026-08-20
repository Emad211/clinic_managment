import functools

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from src.adapters.sqlite.clinical_care_loop_strict_guards import (
    ensure_strict_clinical_care_loop_guards,
)
from src.adapters.sqlite.security_permission_repo import (
    SecurityPermissionConflict,
    SecurityPermissionRepository,
    SecurityPermissionValidationError,
)
from src.adapters.sqlite.security_permission_schema import (
    ensure_security_permission_storage,
)
from src.adapters.sqlite.operational_lease_schema import (
    ensure_operational_lease_storage,
)
from src.adapters.sqlite.clinical_audit_integrity_schema import (
    ensure_clinical_audit_integrity_storage,
)
from src.security.csrf import rotate_csrf_token
from src.security.permissions import Permission, permission_required
from src.security.route_policy import enforce_route_permission
from src.services.activity_logger import log_activity
from src.services.auth_service import AuthService
from src.services.first_run_service import (
    FirstRunService,
    FirstRunValidationError,
)
from src.common.network_policy import is_loopback_remote


bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.record
def install_security_storage(state):
    # ``record`` is deliberate: test suites and desktop relaunches can construct more
    # than one app from the imported Blueprint object.
    with state.app.app_context():
        ensure_strict_clinical_care_loop_guards()
        ensure_security_permission_storage()
        ensure_operational_lease_storage()
        ensure_clinical_audit_integrity_storage()


@bp.before_app_request
def enforce_effective_route_permissions():
    return enforce_route_permission()


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
    if FirstRunService().setup_required():
        return redirect(url_for("auth.setup"))
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


@bp.route("/setup", methods=("GET", "POST"))
def setup():
    if not is_loopback_remote(request.remote_addr):
        abort(403)
    service = FirstRunService()
    target = service.setup_target()
    if target is None:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        try:
            user = service.complete(
                username=request.form.get("username", ""),
                password=request.form.get("password", ""),
                password_confirm=request.form.get("password_confirm", ""),
                full_name=request.form.get("full_name", ""),
            )
        except FirstRunValidationError as exc:
            flash(str(exc))
        except Exception:
            current_app.logger.exception("Secure first-run setup failed")
            flash("راه‌اندازی کامل نشد؛ لطفاً دوباره تلاش کنید.")
        else:
            session.clear()
            log_activity(
                "secure_first_run_completed",
                "Secure manager credentials configured",
                user_id=int(user["id"]),
                username=str(user["username"]),
            )
            if (
                not current_app.config.get("TESTING", False)
                and current_app.config.get("START_SCHEDULER", True)
            ):
                try:
                    from src.services.scheduler import init_scheduler

                    init_scheduler(current_app._get_current_object())
                except Exception:
                    current_app.logger.exception(
                        "Scheduler did not start after first-run setup"
                    )
            flash("راه‌اندازی امن تکمیل شد. اکنون وارد شوید.")
            return redirect(url_for("auth.login"))

    return render_template("auth/setup.html", target=target)


@bp.post("/logout")
@login_required
def logout():
    log_activity(
        "logout",
        f'خروج {g.user["username"]}',
        user_id=g.user["id"],
        username=g.user["username"],
    )
    session.clear()
    return redirect(url_for("auth.login"))


@bp.get("/permissions/<int:user_id>")
@permission_required(Permission.SECURITY_GRANT_MANAGE)
def permission_history(user_id: int):
    db_user = SecurityPermissionRepository()._db().execute(
        "SELECT id, username, full_name, role FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not db_user:
        return jsonify({"error": "user_not_found"}), 404
    return jsonify(
        {
            "user": dict(db_user),
            "events": SecurityPermissionRepository().list_for_user(user_id),
        }
    )


@bp.post("/permissions/<int:user_id>")
@permission_required(Permission.SECURITY_GRANT_MANAGE)
def record_permission(user_id: int):
    payload = request.get_json(silent=True) or request.form
    expected = payload.get("expected_current_event_id")
    try:
        event = SecurityPermissionRepository().record(
            user_id=user_id,
            permission=payload.get("permission_key") or "",
            effect=payload.get("effect") or "",
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            reason=payload.get("reason") or "",
            expected_current_event_id=(
                int(expected) if expected not in {None, ""} else None
            ),
        )
    except SecurityPermissionConflict:
        return jsonify({"error": "stale_permission_state"}), 409
    except LookupError:
        return jsonify({"error": "user_not_found"}), 404
    except (SecurityPermissionValidationError, TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_permission_event", "detail": str(exc)}), 400
    log_activity(
        "security_permission_event",
        f"user={user_id} permission={event['permission_key']} effect={event['effect']}",
        user_id=int(g.user["id"]),
        username=g.user["username"],
    )
    return jsonify({"event": event}), 201


__all__ = [
    "bp",
    "login_required",
    "manager_required",
    "permission_required",
]
