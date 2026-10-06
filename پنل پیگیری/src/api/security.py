"""Request guards: session principal, roles, CSRF and the optional client allow-list (docs/02 §8)."""
from __future__ import annotations

import hmac
import secrets
from functools import wraps
from typing import Callable

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from ..services.auth import Principal

LOCAL_ADDRS = frozenset({"127.0.0.1", "::1"})
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def principal() -> Principal | None:
    if "principal" not in g:
        data = session.get("principal")
        g.principal = Principal.from_session(data) if data else None
    return g.principal


def csrf_token() -> str:
    token = session.get(CSRF_FIELD)
    if not token:
        token = session[CSRF_FIELD] = secrets.token_urlsafe(32)
    return token


def _wants_json() -> bool:
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def check_csrf() -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD, "")
    expected = session.get(CSRF_FIELD, "")
    if not expected or not hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8")):
        message = "نشست منقضی شده است؛ صفحه را دوباره باز کنید"
        if _wants_json():
            resp = jsonify(error=message)
            resp.status_code = 400          # abort(response, code) would ignore the code
            abort(resp)
        abort(400, description=message)


def check_client() -> None:
    allowed = current_app.extensions["peygiri"].settings.allowed_clients
    if allowed and request.remote_addr not in LOCAL_ADDRS and request.remote_addr not in allowed:
        abort(403)


def is_local_request() -> bool:
    return request.remote_addr in LOCAL_ADDRS


def login_required(*roles: str) -> Callable:
    """``roles`` empty → any signed-in user. 'director' means a doctor flagged as director."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            p = principal()
            if p is None:
                if _wants_json():
                    return jsonify(error="ابتدا وارد شوید"), 401
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if roles and p.role not in roles and not ("director" in roles and p.is_director):
                if _wants_json():
                    return jsonify(error="دسترسی ندارید"), 403
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def home_for(p: Principal) -> str:
    return {"doctor": "doctor.queue_page", "reception": "reception.home",
            "manager": "manager.doctors"}[p.role]
