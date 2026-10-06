"""Liveness and status. Detailed /health becomes manager-only once login exists (M1)."""
from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from ..version import APP_ID, APP_VERSION

bp = Blueprint("health", __name__)

_LOCAL = {"127.0.0.1", "::1"}


def _runtime():
    return current_app.extensions["peygiri"]


@bp.get("/healthz")
def healthz():
    """Minimal public probe. The single-instance guard identifies us by ``app``."""
    return jsonify(app=APP_ID, version=APP_VERSION, status="ok")


@bp.get("/health")
def health():
    # Until authentication lands (M1) the detailed status is local-machine only.
    if request.remote_addr not in _LOCAL:
        abort(403)
    rt = _runtime()
    st = rt.monitor.status
    return jsonify(
        app=APP_ID,
        version=APP_VERSION,
        bridge={"state": st.state, "detail": st.detail, "checked_at": st.checked_at,
                "enabled": rt.bridge.enabled, "disabled_reason": rt.bridge.disabled_reason},
        panel_db_bytes=rt.settings.panel_db_path.stat().st_size,
    )


@bp.get("/")
def index():
    rt = _runtime()
    return render_template("index.html", status=rt.monitor.status, bridge=rt.bridge)
