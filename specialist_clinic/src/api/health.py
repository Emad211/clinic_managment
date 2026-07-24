"""Minimal PHI-free operational health endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify

from src.adapters.sqlite.clinical_engine_activation_repo import (
    ClinicalEngineActivationRepository,
)
from src.adapters.sqlite.core import get_db
from src.security.permissions import Permission, permission_required


bp = Blueprint("health", __name__, url_prefix="/health")

_REQUIRED_TABLES = frozenset(
    {
        "patient_links",
        "clinical_engine_runs",
        "clinical_rule_versions",
        "clinical_recommendation_events",
        "clinical_decision_events",
        "clinical_task_events",
        "clinical_outcome_events",
        "clinical_data_conflict_events",
    }
)


def _readiness_checks() -> dict[str, bool]:
    db = get_db()
    quick = db.execute("PRAGMA quick_check").fetchone()
    integrity_ok = bool(quick and str(quick[0]).lower() == "ok")
    tables = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    schema_ok = _REQUIRED_TABLES <= tables

    activation = ClinicalEngineActivationRepository()
    raw_mode = activation.raw_mode()
    activation_ok = (
        raw_mode in {"off", "shadow"}
        or (
            raw_mode in {"on_selected", "on"}
            and activation.valid_seal(raw_mode)
        )
    )
    return {
        "database": integrity_ok,
        "schema": schema_ok,
        "activation": activation_ok,
    }


@bp.get("/live")
def live():
    return jsonify({"status": "ok"})


@bp.get("/ready")
def ready():
    try:
        checks = _readiness_checks()
    except Exception:
        checks = {
            "database": False,
            "schema": False,
            "activation": False,
        }
    is_ready = all(checks.values())
    # Public readiness discloses no table, patient, path, mode, secret or exception.
    return jsonify({"status": "ready" if is_ready else "not_ready"}), (
        200 if is_ready else 503
    )


@bp.get("/details")
@permission_required(Permission.OPERATIONAL_HEALTH_VIEW)
def details():
    try:
        checks = _readiness_checks()
        error = None
    except Exception:
        checks = {
            "database": False,
            "schema": False,
            "activation": False,
        }
        error = "health_check_failed"
    is_ready = all(checks.values())
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "checks": checks,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if error:
        payload["error"] = error
    return jsonify(payload), (200 if is_ready else 503)
