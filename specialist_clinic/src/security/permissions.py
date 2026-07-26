"""Fine-grained authorization vocabulary for clinical and operational mutations.

Existing coarse roles are treated only as default grant bundles. Routes depend on a
stable permission key, so per-user append-only overrides or future directory integration
can change authorization without rewriting clinical APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import functools
import sqlite3

from flask import (
    abort,
    flash,
    g,
    has_app_context,
    redirect,
    request,
    url_for,
)


class Permission(StrEnum):
    PATIENT_VIEW = "patient.view"
    PATIENT_EDIT = "patient.edit"
    CLINICAL_DATA_RECORD = "clinical.data.record"
    CLINICAL_RECONCILE = "clinical.reconcile"
    CLINICAL_CONFLICT_RESOLVE = "clinical.conflict.resolve"
    CLINICAL_ENCOUNTER_MANAGE = "clinical.encounter.manage"
    CLINICAL_DECISION_RECORD = "clinical.decision.record"
    CLINICAL_TASK_VIEW = "clinical.task.view"
    FOLLOWUP_CONTACT_RECORD = "followup.contact.record"
    CLINICAL_TASK_TRANSITION = "clinical.task.transition"
    CLINICAL_OUTCOME_RECORD = "clinical.outcome.record"
    CLINICAL_ALERT_VIEW = "clinical.alert.view"
    CLINICAL_ALERT_ACKNOWLEDGE = "clinical.alert.acknowledge"
    CLINICAL_ALERT_RESOLVE = "clinical.alert.resolve"
    RULE_REVIEW_CLINICAL = "rule.review.clinical"
    RULE_REVIEW_TECHNICAL = "rule.review.technical"
    RULE_ACTIVATE = "rule.activate"
    OPERATIONAL_HEALTH_VIEW = "operational.health.view"
    SECURITY_GRANT_MANAGE = "security.grant.manage"


_ALL = frozenset(Permission)
_ROLE_DEFAULTS = {
    "manager": _ALL,
    "staff": frozenset(
        {
            Permission.PATIENT_VIEW,
            Permission.PATIENT_EDIT,
            Permission.CLINICAL_DATA_RECORD,
            Permission.CLINICAL_TASK_VIEW,
            Permission.FOLLOWUP_CONTACT_RECORD,
            Permission.CLINICAL_ALERT_VIEW,
            Permission.CLINICAL_ALERT_ACKNOWLEDGE,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    permission: Permission
    allowed: bool
    source: str


def default_permissions(role: str | None) -> frozenset[Permission]:
    return _ROLE_DEFAULTS.get(str(role or "").strip().lower(), frozenset())


def _current_overrides(user_id: int) -> dict[Permission, bool] | None:
    """Return overrides, ``{}`` when storage is not installed, or None on failure."""
    if not has_app_context():
        return {}
    from src.adapters.sqlite.core import get_db

    try:
        db = get_db()
        table = db.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='security_permission_events'"""
        ).fetchone()
        if not table:
            return {}
        rows = db.execute(
            """SELECT event.permission_key, event.effect
               FROM security_permission_events event
               WHERE event.user_id=?
                 AND NOT EXISTS (
                     SELECT 1 FROM security_permission_events child
                     WHERE child.supersedes_event_id=event.id
                 )
               ORDER BY event.permission_key""",
            (int(user_id),),
        ).fetchall()
    except (sqlite3.Error, RuntimeError, TypeError, ValueError):
        return None

    result: dict[Permission, bool] = {}
    for row in rows:
        try:
            permission = Permission(row["permission_key"])
        except (KeyError, TypeError, ValueError):
            continue
        result[permission] = row["effect"] == "GRANTED"
    return result


def resolved_permissions(user) -> frozenset[Permission]:
    if not user:
        return frozenset()
    grants = set(default_permissions(user["role"]))
    overrides = _current_overrides(int(user["id"]))
    if overrides is None:
        # Failure to read revocations must never restore a role default. Authorization
        # fails closed until storage health is restored.
        return frozenset()
    for permission, allowed in overrides.items():
        if allowed:
            grants.add(permission)
        else:
            grants.discard(permission)
    return frozenset(grants)


def decide(user, permission: str | Permission) -> PermissionDecision:
    required = Permission(permission)
    allowed = required in resolved_permissions(user)
    return PermissionDecision(
        permission=required,
        allowed=allowed,
        source="effective-grants" if user else "anonymous",
    )


def has_permission(permission: str | Permission) -> bool:
    return decide(getattr(g, "user", None), permission).allowed


def permission_required(permission: str | Permission):
    required = Permission(permission)

    def decorator(view):
        @functools.wraps(view)
        def wrapped_view(**kwargs):
            if getattr(g, "user", None) is None:
                return redirect(url_for("auth.login"))
            decision = decide(g.user, required)
            if not decision.allowed:
                if request.is_json or request.accept_mimetypes.best == "application/json":
                    abort(403)
                flash("مجوز لازم برای این اقدام ثبت نشده است.", "error")
                return redirect(request.referrer or url_for("dashboard.index"))
            return view(**kwargs)

        wrapped_view.required_permission = required.value
        return wrapped_view

    return decorator


def permissions_for_template() -> dict[str, bool]:
    grants = resolved_permissions(getattr(g, "user", None))
    return {permission.value: permission in grants for permission in Permission}


__all__ = [
    "Permission",
    "PermissionDecision",
    "decide",
    "default_permissions",
    "has_permission",
    "permission_required",
    "permissions_for_template",
    "resolved_permissions",
]
