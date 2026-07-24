"""Small dependency-free CSRF protection for browser and JSON mutations."""
from __future__ import annotations

import functools
import hmac
import re
import secrets

from flask import abort, current_app, request, session


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_SESSION_KEY = "_csrf_token"
_POST_FORM = re.compile(
    r"(<form\b(?=[^>]*\bmethod\s*=\s*(['\"]?)post\2)[^>]*>)",
    re.IGNORECASE,
)


def csrf_token() -> str:
    token = session.get(_SESSION_KEY)
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        session[_SESSION_KEY] = token
    return token


def rotate_csrf_token() -> str:
    session.pop(_SESSION_KEY, None)
    return csrf_token()


def csrf_exempt(view):
    view.csrf_exempt = True
    return view


def _endpoint_exempt() -> bool:
    endpoint = request.endpoint
    if not endpoint:
        return False
    view = current_app.view_functions.get(endpoint)
    return bool(view and getattr(view, "csrf_exempt", False))


def _supplied_token() -> str:
    return str(
        request.headers.get("X-CSRF-Token")
        or request.form.get("_csrf_token")
        or ""
    )


def validate_csrf_request() -> None:
    if not current_app.config.get("CSRF_PROTECTION_ENABLED", True):
        return
    if request.method in _SAFE_METHODS or _endpoint_exempt():
        return
    expected = session.get(_SESSION_KEY)
    supplied = _supplied_token()
    if (
        not isinstance(expected, str)
        or len(expected) < 32
        or not supplied
        or not hmac.compare_digest(expected, supplied)
    ):
        abort(400, description="CSRF validation failed")


def _inject_form_tokens(response):
    if not current_app.config.get("CSRF_PROTECTION_ENABLED", True):
        return response
    if (
        response.status_code != 200
        or response.direct_passthrough
        or not response.mimetype
        or response.mimetype != "text/html"
    ):
        return response
    body = response.get_data(as_text=True)
    if "<form" not in body.lower():
        return response
    hidden = (
        '<input type="hidden" name="_csrf_token" value="'
        + csrf_token()
        + '">'
    )
    body = _POST_FORM.sub(lambda match: match.group(1) + hidden, body)
    response.set_data(body)
    return response


def install_csrf(app) -> None:
    # Production is strict by default. Existing broad regression suites can keep
    # TESTING isolated until converted, while focused security tests explicitly set
    # CSRF_PROTECTION_ENABLED=True and exercise the exact production boundary.
    app.config.setdefault(
        "CSRF_PROTECTION_ENABLED",
        not bool(app.config.get("TESTING", False)),
    )
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(validate_csrf_request)
    app.after_request(_inject_form_tokens)


__all__ = [
    "csrf_exempt",
    "csrf_token",
    "install_csrf",
    "rotate_csrf_token",
    "validate_csrf_request",
]
