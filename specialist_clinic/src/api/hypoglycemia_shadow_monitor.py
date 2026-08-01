"""Internal monitoring and clinician-owned hypoglycemia shadow adjudication."""
from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
    g,
)

from src.security.permissions import Permission, permission_required
from src.services.hypoglycemia_shadow import (
    HypoglycemiaShadowConflict,
    HypoglycemiaShadowService,
    HypoglycemiaShadowValidationError,
)
from src.services.hypoglycemia_shadow_adjudication import (
    HypoglycemiaShadowAdjudicationQueue,
)
from src.services.hypoglycemia_shadow_observability import (
    HypoglycemiaShadowObservability,
)


bp = Blueprint(
    "hypoglycemia_shadow_monitor",
    __name__,
    url_prefix="/manager/hypoglycemia-shadow",
)
_ALLOWED_UI_DECISIONS = frozenset({"CONFIRMED", "REJECTED", "CONFLICT"})


def _private_response(template: str, **context):
    response = make_response(render_template(template, **context))
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@bp.get("/")
@permission_required(Permission.OPERATIONAL_HEALTH_VIEW)
def index():
    """Render identifier-free internal counts without adding a write surface."""
    return _private_response(
        "manager/hypoglycemia_shadow_monitor.html",
        shadow=HypoglycemiaShadowObservability().snapshot(),
        active_page="manager",
    )


@bp.get("/candidates")
@permission_required(Permission.CLINICAL_DECISION_RECORD)
def candidates():
    """List only current candidate/conflict heads for human adjudication."""
    return _private_response(
        "manager/hypoglycemia_shadow_candidates.html",
        queue=HypoglycemiaShadowAdjudicationQueue().snapshot(),
        active_page="manager",
    )


@bp.post("/candidates/<event_id>/adjudicate")
@permission_required(Permission.CLINICAL_DECISION_RECORD)
def adjudicate(event_id: str):
    """Record one explicit human event decision; never open a review or task."""
    queue = HypoglycemiaShadowAdjudicationQueue()
    if queue.storage_state(queue._db()) != "READY":
        flash("زیرساخت Shadow برای داوری آماده نیست.", "error")
        return redirect(url_for("hypoglycemia_shadow_monitor.candidates"))

    decision = str(request.form.get("decision") or "").strip().upper()
    rationale = " ".join(
        str(request.form.get("rationale") or "").strip().split()
    )
    try:
        expected_version_id = int(
            request.form.get("expected_version_id") or ""
        )
    except (TypeError, ValueError):
        flash("نسخهٔ رخداد برای داوری معتبر نیست.", "error")
        return redirect(url_for("hypoglycemia_shadow_monitor.candidates"))
    if decision not in _ALLOWED_UI_DECISIONS:
        flash("تصمیم داوری معتبر نیست.", "error")
        return redirect(url_for("hypoglycemia_shadow_monitor.candidates"))
    if not rationale:
        flash("ثبت دلیل داوری الزامی است.", "error")
        return redirect(url_for("hypoglycemia_shadow_monitor.candidates"))
    if len(rationale) > 1000:
        flash("دلیل داوری بیش از حد طولانی است.", "error")
        return redirect(url_for("hypoglycemia_shadow_monitor.candidates"))

    try:
        HypoglycemiaShadowService().adjudicate(
            event_id,
            expected_current_version_id=expected_version_id,
            decision=decision,
            actor_username=g.user["username"],
            note=rationale,
        )
    except HypoglycemiaShadowConflict:
        flash(
            "رخداد هم‌زمان تغییر کرده است؛ فهرست را دوباره بررسی کنید.",
            "error",
        )
    except (HypoglycemiaShadowValidationError, LookupError) as exc:
        flash(f"داوری ثبت نشد: {exc}", "error")
    else:
        labels = {
            "CONFIRMED": "تأیید",
            "REJECTED": "رد",
            "CONFLICT": "تعارض",
        }
        flash(f"نتیجهٔ داوری ({labels[decision]}) ثبت شد.", "success")
    return redirect(url_for("hypoglycemia_shadow_monitor.candidates"))
