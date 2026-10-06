"""Liveness probe and the manager's health page data (docs/02 §9)."""
from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, abort, jsonify

from ..app_context import get_db, now, runtime
from ..services.sync_status import status as sync_status
from ..version import APP_ID, APP_VERSION
from .security import is_local_request, principal

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    """Minimal public probe. The single-instance guard identifies us by ``app``."""
    return jsonify(app=APP_ID, version=APP_VERSION, status="ok")


@bp.get("/health")
def health():
    p = principal()
    if not (is_local_request() or (p is not None and p.role == "manager")):
        abort(403)
    rt = runtime()
    st = rt.monitor.status
    return jsonify(
        app=APP_ID,
        version=APP_VERSION,
        bridge={"state": st.state, "detail": st.detail, "checked_at": st.checked_at,
                "enabled": rt.bridge.enabled, "disabled_reason": rt.bridge.disabled_reason},
        sync=asdict(sync_status(get_db(), rt.bridge, now())),
        panel_db_bytes=rt.settings.panel_db_path.stat().st_size,
    )
