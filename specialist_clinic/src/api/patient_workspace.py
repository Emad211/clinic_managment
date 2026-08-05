"""Native five-tab Patient Workspace and compatibility routing."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for

from src.api.auth import login_required
from src.services.patient_workspace_service import (
    PatientWorkspaceService,
    WORKSPACE_TABS,
)


bp = Blueprint("patient_workspace", __name__, url_prefix="/patients")
_PATIENT_DETAIL_PATH = re.compile(r"^/patients/(?P<pid>\d+)/?$")
_FRAGMENT_TO_TAB = {
    "cockpit": "summary",
    "trends": "clinical",
    "record": "clinical",
    "labs": "clinical",
    "meds": "meds",
    "encounters": "encounters",
    "documents": "encounters",
    "actions": "actions",
}
_ENDPOINT_TO_TAB = {
    "patients.sms_consent_update": "actions",
    "followups.add_manual": "actions",
    "vitals.add_reading": "clinical",
    "vitals.add_lab": "clinical",
    "patients.add_condition": "clinical",
    "patients.remove_condition": "clinical",
    "patients.add_allergy": "clinical",
    "patients.delete_allergy": "clinical",
    "patients.save_flags": "clinical",
    "patients.record_history_add": "clinical",
    "patients.record_history_delete": "clinical",
    "patients.record_surgery_add": "clinical",
    "patients.record_surgery_delete": "clinical",
    "patients.record_note_add": "clinical",
    "patients.record_note_delete": "clinical",
    "patients.add_medication": "meds",
    "patients.stop_medication": "meds",
    "patients.change_medication_dose": "meds",
    "patients.add_prescription": "meds",
    "appointments.new_appointment": "encounters",
}


def _normalize_tab(value: object) -> str:
    tab = str(value or "summary").strip().lower()
    return tab if tab in WORKSPACE_TABS else "summary"


@bp.get("/<int:pid>/workspace")
@login_required
def detail(pid: int):
    workspace = PatientWorkspaceService().build(pid)
    if workspace is None:
        flash("بیمار یافت نشد", "error")
        return redirect(url_for("patients.list_patients"))
    active_tab = _normalize_tab(request.args.get("tab"))
    return render_template(
        "patients/workspace.html",
        active_page="patients",
        active_tab=active_tab,
        workspace_tabs=WORKSPACE_TABS,
        legacy_url=url_for("patients.detail", pid=pid, legacy=1),
        **workspace,
    )


def _workspace_url(pid: int, tab: str) -> str:
    return url_for("patient_workspace.detail", pid=int(pid), tab=_normalize_tab(tab))


def install_compatibility(app) -> None:
    """Make the native workspace canonical without breaking historical deep links."""
    if app.extensions.get("patient_workspace_compatibility_v2"):
        return
    app.extensions["patient_workspace_compatibility_v2"] = True

    @app.before_request
    def redirect_legacy_patient_detail():
        if request.endpoint != "patients.detail":
            return None
        if request.args.get("legacy") == "1":
            return None
        pid = (request.view_args or {}).get("pid")
        if not pid:
            return None
        return redirect(_workspace_url(int(pid), request.args.get("tab") or "summary"))

    @app.after_request
    def rewrite_patient_redirects(response):
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location")
        if not location:
            return response
        parsed = urlsplit(location)
        match = _PATIENT_DETAIL_PATH.match(parsed.path)
        if not match:
            return response

        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query.get("legacy") == "1":
            return response
        fragment_tab = _FRAGMENT_TO_TAB.get(parsed.fragment.lower())
        endpoint_tab = _ENDPOINT_TO_TAB.get(request.endpoint or "")
        requested_tab = query.get("tab")
        tab = fragment_tab or endpoint_tab or requested_tab or "summary"
        path = url_for(
            "patient_workspace.detail",
            pid=int(match.group("pid")),
        )
        response.headers["Location"] = urlunsplit(
            ("", "", path, urlencode({"tab": _normalize_tab(tab)}), "")
        )
        return response


__all__ = ["bp", "install_compatibility"]
