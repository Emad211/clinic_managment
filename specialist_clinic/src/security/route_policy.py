"""Endpoint-level permission policy for clinical mutations not yet decorator-migrated.

This central boundary prevents coarse role checks or forgotten legacy decorators from
becoming authorization bypasses while routes are migrated incrementally.
"""
from __future__ import annotations

from flask import abort, flash, g, redirect, request, url_for

from src.security.permissions import Permission, has_permission


_ENDPOINT_PERMISSIONS = {
    "patients.list_patients": Permission.PATIENT_VIEW,
    "patients.detail": Permission.PATIENT_VIEW,
    "patients.analytics": Permission.PATIENT_VIEW,
    "patients.enroll": Permission.PATIENT_EDIT,
    "patients.enroll_accounting": Permission.PATIENT_EDIT,
    "patients.enroll_manual": Permission.PATIENT_EDIT,
    "patients.wallet_adjust": Permission.PATIENT_EDIT,
    "patients.add_condition": Permission.CLINICAL_DATA_RECORD,
    "patients.remove_condition": Permission.CLINICAL_DATA_RECORD,
    "patients.add_medication": Permission.CLINICAL_DATA_RECORD,
    "patients.stop_medication": Permission.CLINICAL_DATA_RECORD,
    "patients.change_dose": Permission.CLINICAL_DATA_RECORD,
    "patients.add_allergy": Permission.CLINICAL_DATA_RECORD,
    "patients.delete_allergy": Permission.CLINICAL_DATA_RECORD,
    "patients.save_flags": Permission.CLINICAL_DATA_RECORD,
    "patients.clinical_v2_decision": Permission.CLINICAL_DECISION_RECORD,
    "patients.generate_followups": Permission.CLINICAL_TASK_TRANSITION,
    "manager.clinical_engine": Permission.RULE_REVIEW_CLINICAL,
}


def _manager_action_permission() -> Permission:
    action = str(request.view_args.get("action") or "").strip()
    if action in {
        "activate-selected",
        "verify-selected",
        "promote-ruleset",
        "activate-global",
        "rollback",
        "reset-workflow",
    }:
        return Permission.RULE_ACTIVATE
    if action == "approve" and request.form.get("role") == "technical":
        return Permission.RULE_REVIEW_TECHNICAL
    if action in {"prepare-rules", "compare", "prepare-demo-cohort"}:
        return Permission.RULE_REVIEW_TECHNICAL
    return Permission.RULE_REVIEW_CLINICAL


def required_permission() -> Permission | None:
    endpoint = str(request.endpoint or "")
    if endpoint == "manager.clinical_engine_action":
        return _manager_action_permission()
    return _ENDPOINT_PERMISSIONS.get(endpoint)


def enforce_route_permission():
    permission = required_permission()
    if permission is None:
        return None
    if getattr(g, "user", None) is None:
        return redirect(url_for("auth.login"))
    if has_permission(permission):
        return None
    if request.is_json or request.accept_mimetypes.best == "application/json":
        abort(403)
    flash("مجوز governشدهٔ لازم برای این عملیات ثبت نشده است.", "error")
    return redirect(request.referrer or url_for("dashboard.index"))


__all__ = ["enforce_route_permission", "required_permission"]
