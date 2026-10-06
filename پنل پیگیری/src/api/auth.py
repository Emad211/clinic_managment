"""Login and logout (docs/06 §3)."""
from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from ..app_context import get_db, now
from ..services.auth import AuthService, LoginError
from .security import home_for, principal

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str | None:
    if not target:
        return None
    parts = urlparse(target)
    return target if not parts.scheme and not parts.netloc and target.startswith("/") else None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        p = principal()
        if p is not None:
            return redirect(url_for(home_for(p)))
        return render_template("login.html", error=None, username="")

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    bridge = current_app.extensions["peygiri"].bridge
    try:
        p = AuthService(get_db(), bridge, now()).login(username, password)
    except LoginError as exc:
        return render_template("login.html", error=exc.message, username=username.strip()), 401
    session.clear()
    session.permanent = True
    session["principal"] = p.to_session()
    return redirect(_safe_next(request.args.get("next")) or url_for(home_for(p)))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
