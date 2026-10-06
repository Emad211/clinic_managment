"""Doctor panel, journey cancel, nurse paper and cut-offs (docs/06 §1, §4-2, §5-2, §6)."""
from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, render_template, request

from ..app_context import get_db, now
from ..services import calls, cutoffs, encounters, journeys, walkins
from .security import login_required, principal

bp = Blueprint("clinical", __name__)

_ERRORS = (encounters.EncounterError, walkins.WalkinError, journeys.JourneyError, cutoffs.CutoffError,
           calls.CallError)


def json_errors(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except _ERRORS as exc:
            body = {"error": str(exc)}
            if getattr(exc, "problems", None):
                body["problems"] = exc.problems
            return jsonify(body), getattr(exc, "status", 400)
    return wrapped


def payload() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise encounters.EncounterError("بدنهٔ درخواست باید یک فرم JSON باشد")
    return data


# ------------------------------------------------------------------ doctor panel
@bp.get("/doctor/visit/<int:visit_id>")
@login_required("doctor")
def panel_page(visit_id: int):
    return render_template("doctor_panel.html", visit_id=visit_id)


@bp.get("/api/doctor/visit/<int:visit_id>")
@login_required("doctor")
@json_errors
def panel_data(visit_id: int):
    return jsonify(encounters.panel(get_db(), visit_id, principal().staff_id, now().date().isoformat()))


@bp.post("/api/doctor/visit/<int:visit_id>")
@login_required("doctor")
@json_errors
def panel_save(visit_id: int):
    p = principal()
    return jsonify(encounters.save(get_db(), visit_id, payload(), staff_id=p.staff_id, actor=p.actor, now=now()))


@bp.post("/api/journeys/<int:journey_id>/cancel")
@login_required("doctor", "manager")
@json_errors
def journey_cancel(journey_id: int):
    p = principal()
    journeys.cancel_by_user(get_db(), journey_id, role=p.role, staff_id=p.staff_id, actor=p.actor, now=now())
    return jsonify(message="مسیر لغو شد")


# ------------------------------------------------------------------ nurse paper
@bp.get("/api/reception/walkins")
@login_required("reception")
def walkin_list():
    return jsonify(walkins.worklist(get_db(), now()))


@bp.post("/api/reception/walkins/<int:invoice_id>")
@login_required("reception")
@json_errors
def walkin_save(invoice_id: int):
    return jsonify(walkins.save(get_db(), invoice_id, payload(), actor=principal().actor, now=now()))


# ------------------------------------------------------------------ calls & returns (M4)
@bp.get("/api/reception/followups")
@login_required("reception")
def followups():
    return jsonify(calls.worklists(get_db(), now()))


@bp.get("/api/reception/calls/<int:step_id>/slots")
@login_required("reception")
@json_errors
def call_slots(step_id: int):
    return jsonify(slots=calls.appointment_slots(get_db(), step_id, now()))


@bp.post("/api/reception/calls/<int:step_id>")
@login_required("reception")
@json_errors
def call_outcome(step_id: int):
    return jsonify(calls.record(get_db(), step_id, payload(), actor=principal().actor, now=now()))


@bp.post("/api/reception/link")
@login_required("reception")
@json_errors
def link_invoice():
    data = payload()
    try:
        invoice_id, person_id = int(data.get("invoice_id")), int(data.get("person_id"))
    except (TypeError, ValueError):
        raise calls.CallError("فاکتور و شخص را انتخاب کنید") from None
    return jsonify(calls.link_invoice(get_db(), invoice_id, person_id, actor=principal().actor, now=now()))


@bp.post("/api/reception/suggestions/<int:suggestion_id>")
@login_required("reception")
@json_errors
def suggestion(suggestion_id: int):
    accept = payload().get("accept")
    if accept not in (True, False):
        raise calls.CallError("«همین بیمار است» یا «نه» را انتخاب کنید")
    return jsonify(calls.decide_suggestion(get_db(), suggestion_id, accept, actor=principal().actor, now=now()))


# ------------------------------------------------------------------ cut-offs
@bp.get("/cutoffs")
@login_required("manager", "director")
def cutoffs_page():
    return render_template("cutoffs.html")


@bp.get("/api/cutoffs")
@login_required("manager", "director")
def cutoffs_state():
    p = principal()
    return jsonify(**cutoffs.state(get_db()), can_approve=bool(p.role == "doctor" and p.is_director))


@bp.post("/api/cutoffs/draft")
@login_required("manager", "director")
@json_errors
def cutoffs_draft():
    data = payload()
    return jsonify(cutoffs.save_draft(get_db(), data.get("rules"), actor=principal().actor, now=now()))


@bp.post("/api/cutoffs/approve")
@login_required("director")
@json_errors
def cutoffs_approve():
    p = principal()
    if not (p.role == "doctor" and p.is_director):
        raise cutoffs.CutoffError("فقط پزشک مدیر می‌تواند کات‌آف را تأیید کند")
    version = cutoffs.approve(get_db(), director_staff_id=p.staff_id, actor=p.actor, now=now())
    return jsonify(message=f"نسخهٔ {version} تأیید شد و از این پس اعمال می‌شود")
