"""Token-authenticated bridge blueprint for the prescription browser extension.

This blueprint is not session/cookie based. Each request carries an active physician
API token in the Authorization header, so the mutation endpoint is explicitly exempt
from session CSRF while retaining origin, bearer-token and rate-limit controls.
"""
from flask import Blueprint, request, jsonify, current_app

from src.adapters.sqlite.core import get_db
from src.common.rate_limit import allow
from src.security.csrf import csrf_exempt


bp = Blueprint("ext", __name__, url_prefix="/api/ext")
ALLOWED_ORIGINS = (
    "https://ep.tamin.ir",
    "http://localhost",
    "http://127.0.0.1",
)


def _origin_allowed(origin: str) -> bool:
    value = str(origin or "").strip().rstrip("/")
    if value == "https://ep.tamin.ir":
        return True
    return (
        value in {"http://localhost", "http://127.0.0.1"}
        or value.startswith("http://localhost:")
        or value.startswith("http://127.0.0.1:")
    )


def _origin_rejected():
    origin = request.headers.get("Origin", "")
    if origin and not _origin_allowed(origin):
        return jsonify({"ok": False, "error": "origin_forbidden"}), 403
    return None


def _user_from_request():
    """Resolve only an active, unexpired bearer token; never accept query/body tokens."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    from src.adapters.sqlite.auth_repo import AuthRepository

    return AuthRepository().get_user_by_token(token) if token else None


@bp.after_request
def _cors(response):
    origin = request.headers.get("Origin", "")
    if _origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@bp.route("/pending", methods=["GET", "OPTIONS"])
def pending():
    if request.method == "OPTIONS":
        return "", 204
    rejected = _origin_rejected()
    if rejected:
        return rejected
    if not current_app.config.get("TESTING") and not allow(
        f"ext:{request.remote_addr or '?'}",
        limit=60,
        per_seconds=60,
    ):
        return jsonify({"ok": False, "error": "rate_limited"}), 429
    user = _user_from_request()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    db = get_db()
    from src.services.followup_projection_service import FollowupProjectionService

    rows = [
        task for task in FollowupProjectionService().open_tasks()
        if task.get("fulfillment") == "remote"
        and task.get("source_engine") != "clinical_v2"
    ][:200]
    items = []
    for row in rows:
        item = dict(row)
        item["followup_id"] = int(item["id"])
        item["full_name"] = item.get("patient_name")
        medications = db.execute(
            """SELECT drug_name, dose, schedule
               FROM patient_medications
               WHERE patient_link_id=? AND is_active=1""",
            (item["patient_link_id"],),
        ).fetchall()
        item["medications"] = [dict(medication) for medication in medications]
        items.append(item)
    return jsonify({"items": items})


@bp.route("/captured", methods=["POST", "OPTIONS"])
@csrf_exempt
def captured():
    if request.method == "OPTIONS":
        return "", 204
    rejected = _origin_rejected()
    if rejected:
        return rejected
    if not current_app.config.get("TESTING") and not allow(
        f"ext:{request.remote_addr or '?'}",
        limit=60,
        per_seconds=60,
    ):
        return jsonify({"ok": False, "error": "rate_limited"}), 429
    user = _user_from_request()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    db = get_db()
    patient = db.execute(
        "SELECT id FROM patient_links WHERE national_id=?",
        (data.get("national_id"),),
    ).fetchone()
    if not patient:
        return jsonify({"ok": False, "error": "patient_not_found"}), 404

    from src.adapters.sqlite.record_repo import RecordRepository

    prescription_id = RecordRepository().add_prescription(
        patient["id"],
        kind="refill",
        items=data.get("items"),
        mode="insurance",
        insurer=data.get("insurer"),
        portal_rx_id=data.get("portal_rx_id"),
        prescriber_user_id=user["id"],
        followup_task_id=data.get("followup_task_id"),
    )
    if data.get("followup_task_id"):
        from src.adapters.sqlite.followups_repo import FollowupRepository

        FollowupRepository().resolve(
            int(data["followup_task_id"]),
            "done",
            call_log="نسخهٔ بیمه‌ای از پل ثبت شد",
        )
    return jsonify({"ok": True, "prescription_id": prescription_id})


@bp.record_once
def register_work_center_outcomes(state):
    """Register focused Work Center routes and its detail-page context."""
    from src.api.work_center_outcomes import (
        bp as work_center_outcomes_bp,
        template_context,
    )

    if work_center_outcomes_bp.name not in state.app.blueprints:
        state.app.register_blueprint(work_center_outcomes_bp)
    state.app.context_processor(template_context)
