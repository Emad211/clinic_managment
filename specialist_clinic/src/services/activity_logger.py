"""Durable activity logger for the specialist app."""
import os
from pathlib import Path

from flask import current_app, g
from src.adapters.sqlite.core import get_db
from src.common.utils import iran_now


class ActivityLogError(RuntimeError):
    """The requested audit event could not be persisted."""

    code = "ACTIVITY_AUDIT_WRITE_FAILED"
    status_code = 500


def activity_audit_marker_path(
    database_path: str, *, instance_path: str
) -> Path:
    """Return a PHI-free incident marker that survives process restarts."""
    if str(database_path) == ":memory:":
        return Path(instance_path).resolve() / "activity-audit-degraded.flag"
    database = Path(database_path).resolve()
    return database.with_name(database.name + ".activity-audit-degraded.flag")


def activity_audit_marker_exists(
    database_path: str, *, instance_path: str
) -> bool:
    return activity_audit_marker_path(
        database_path, instance_path=instance_path
    ).is_file()


def _persist_degraded_marker() -> None:
    marker = None
    staging = None
    try:
        database_path = current_app.config.get("DATABASE_PATH") or str(
            Path(current_app.instance_path) / "specialist.db"
        )
        marker = activity_audit_marker_path(
            database_path,
            instance_path=current_app.instance_path,
        )
        staging = marker.with_suffix(marker.suffix + ".tmp")
        marker.parent.mkdir(parents=True, exist_ok=True)
        staging.write_text(
            "ACTIVITY_AUDIT_GAP\n" + iran_now().isoformat(timespec="seconds"),
            encoding="utf-8",
        )
        os.replace(staging, marker)
    except OSError:
        current_app.logger.critical(
            "activity audit incident marker could not be persisted",
            exc_info=True,
        )
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def acknowledge_activity_audit_gap(actor: str) -> bool:
    """Clear the durable marker only after a new acknowledgement is audited."""
    username = str(actor or "").strip()
    if not username:
        raise ValueError("actor is required")
    marker = activity_audit_marker_path(
        current_app.config["DATABASE_PATH"],
        instance_path=current_app.instance_path,
    )
    if not marker.is_file():
        current_app.extensions["activity_audit_healthy"] = True
        return False
    log_activity(
        "activity_audit_gap_acknowledged",
        "Operator acknowledged a prior activity-audit persistence gap",
        user_id=0,
        username=username,
        strict=True,
    )
    marker.unlink()
    current_app.extensions["activity_audit_healthy"] = True
    current_app.logger.warning(
        "activity audit incident acknowledged actor=%s", username
    )
    return True


def log_activity(action_type: str, description: str = None,
                 patient_link_id: int = None, user_id: int = None,
                 username: str = None, *, strict: bool = False):
    db = None
    try:
        db = get_db()
        if user_id is None and getattr(g, 'user', None):
            user_id = g.user['id']
            username = g.user['username']
        if user_id is None:
            user_id, username = 0, 'system'
        db.execute(
            """
            INSERT INTO activity_logs (user_id, username, action_type, description, patient_link_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, action_type, description, patient_link_id,
             iran_now().strftime('%Y-%m-%d %H:%M:%S')),
        )
        db.commit()
        return True
    except Exception as exc:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                current_app.logger.exception("activity audit rollback failed")
        current_app.logger.exception(
            "activity audit write failed action_type=%s", action_type
        )
        current_app.extensions["activity_audit_healthy"] = False
        _persist_degraded_marker()
        if strict:
            raise ActivityLogError("activity audit write failed") from exc
        # Primary mutations and external SMS effects generally commit before this
        # audit call. A retryable 500 would misreport that result and can duplicate
        # effects; the persistent ERROR and degraded readiness remain fail-loud.
        return False
