"""Fine-grained authorization vocabulary for clinical and operational mutations.

Existing coarse roles are treated only as default grant bundles. Routes depend on a
stable permission key, so future per-user grants or directory integration can replace
the default resolver without rewriting clinical APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import functools
from typing import Iterable

from flask import abort, flash, g, redirect, request, url_for


class Permission(StrEnum):
    PATIENT_VIEW = "patient.view"
    PATIENT_EDIT = "patient.edit"
    CLINICAL_DATA_RECORD = "clinical.data.record"
    CLINICAL_RECONCILE = "clinical.reconcile"
    CLINICAL_CONFLICT_RESOLVE = "clinical.conflict.resolve"
    CLINICAL_ENCOUNTER_MANAGE = "clinical.encounter.manage"
    CLINICAL_DECISION_RECORD = "clinical.decision.record"
    CLINICAL_TASK_VIEW = "clinical.task.view"
    CLINICAL_TASK_TRANSITION = "clinical.task.transition"
    CLINICAL_OUTCOME_RECORD = "clinical.outcome.record"
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


def resolved_permissions(user) -> frozenset[Permission]:
    if not user:
        return frozenset()
    # Per-user grant events are added later in this tranche. Keeping resolution in
    # one function prevents role checks from spreading back through clinical routes.
    return default_permissions(user["role"])


def decide(user, permission: str | Permission) -> PermissionDecision:
    required = Permission(permission)
    allowed = required in resolved_permissions(user)
    return PermissionDecision(
        permission=required,
        allowed=allowed,
        source=f"role:{user['role']}" if user else "anonymous",
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
                # API clients receive an explicit authorization status; browser
                # forms keep the established Persian UX without leaking internals.
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
