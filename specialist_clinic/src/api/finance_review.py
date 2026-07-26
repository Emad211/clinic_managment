"""Manager review surface for payer evidence and recorded financial adjustments."""
from __future__ import annotations

import uuid

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from src.adapters.sqlite.core import get_db
from src.security.permissions import Permission, permission_required
from src.services.activity_logger import log_activity
from src.services.specialist_financial_reconciliation_service import (
    SpecialistFinancialReconciliationService,
)
from src.services.specialist_payer_adjustment_service import (
    SpecialistFinancialReviewConflict,
    SpecialistFinancialReviewValidationError,
    SpecialistPayerAdjustmentService,
)


bp = Blueprint("finance_review", __name__, url_prefix="/finance-review")


@bp.get("/")
@permission_required(Permission.FINANCIAL_REVIEW_VIEW)
def index():
    status_filter = str(request.args.get("status") or "pending").strip().lower()
    rows = get_db().execute(
        """SELECT observation.accounting_invoice_id,
                  observation.patient_link_id,
                  observation.journey_id,
                  observation.encounter_id,
                  observation.work_date,
                  observation.billed_amount,
                  observation.collected_amount,
                  observation.collection_state,
                  observation.observed_at,
                  patient.full_name
           FROM specialist_financial_observations observation
           JOIN patient_links patient ON patient.id=observation.patient_link_id
           WHERE observation.id=(
               SELECT latest.id FROM specialist_financial_observations latest
               WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
               ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
           )
           ORDER BY observation.observed_at DESC,observation.id DESC"""
    ).fetchall()
    service = SpecialistPayerAdjustmentService()
    items = []
    for source in rows:
        projection = service.invoice_projection(
            int(source["accounting_invoice_id"])
        )
        item = {**dict(source), "projection": projection}
        if status_filter == "pending" and projection.get("safe_to_sum"):
            continue
        if status_filter == "reviewed" and not projection.get("safe_to_sum"):
            continue
        items.append(item)
    totals = service.totals()
    return render_template(
        "finance_review/index.html",
        items=items,
        totals=totals,
        status_filter=status_filter,
        active_page="finance_review",
    )


@bp.post("/reconcile")
@permission_required(Permission.FINANCIAL_RECONCILE)
def reconcile():
    result = SpecialistFinancialReconciliationService().reconcile_all()
    if result["issues"]:
        flash(
            f"بازخوانی انجام شد؛ {len(result['issues'])} فاکتور خطا داشت.",
            "warning",
        )
    else:
        flash(
            f"{result['observed']} فاکتور بررسی شد و "
            f"{result['reviews_opened']} بازبینی جدید باز شد.",
            "success",
        )
    log_activity("financial_reconcile_a7", f"A7 reconciliation: {result}")
    return redirect(url_for("finance_review.index"))


@bp.post("/invoice/<int:invoice_id>/adjustment")
@permission_required(Permission.FINANCIAL_ADJUSTMENT_RECORD)
def record_adjustment(invoice_id: int):
    service = SpecialistPayerAdjustmentService()
    try:
        event = service.record_adjustment(
            accounting_invoice_id=invoice_id,
            adjustment_type=request.form.get("adjustment_type") or "",
            signed_amount=request.form.get("signed_amount", type=int),
            evidence_type=request.form.get("evidence_type") or "",
            evidence_ref=request.form.get("evidence_ref") or "",
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            note=request.form.get("note"),
            occurred_at=request.form.get("occurred_at") or None,
            adjustment_id=request.form.get("adjustment_id") or None,
            expected_current_event_id=request.form.get(
                "expected_current_event_id", type=int
            ),
            idempotency_key=(
                request.form.get("idempotency_key")
                or f"financial-adjustment:{invoice_id}:{uuid.uuid4().hex}"
            ),
        )
    except (
        LookupError,
        TypeError,
        ValueError,
        SpecialistFinancialReviewConflict,
        SpecialistFinancialReviewValidationError,
    ) as exc:
        flash(f"اصلاح مالی ثبت نشد: {exc}", "error")
    else:
        log_activity(
            "financial_adjustment_record",
            f"invoice={invoice_id} adjustment={event['adjustment_id']} "
            f"amount={event['signed_amount']}",
            patient_link_id=int(event["patient_link_id"]),
        )
        flash("اصلاح مالی با شاهد ثبت شد؛ بازبینی دوباره لازم است.", "success")
    return redirect(url_for("finance_review.index") + f"#invoice-{invoice_id}")


@bp.post("/adjustment/<adjustment_id>/reverse")
@permission_required(Permission.FINANCIAL_ADJUSTMENT_CORRECT)
def reverse_adjustment(adjustment_id: str):
    service = SpecialistPayerAdjustmentService()
    try:
        event = service.reverse_adjustment(
            adjustment_id=adjustment_id,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            note=request.form.get("note") or "",
            expected_current_event_id=request.form.get(
                "expected_current_event_id", type=int
            ),
            idempotency_key=(
                request.form.get("idempotency_key")
                or f"financial-adjustment-reverse:{adjustment_id}:{uuid.uuid4().hex}"
            ),
        )
    except (
        LookupError,
        TypeError,
        ValueError,
        SpecialistFinancialReviewConflict,
        SpecialistFinancialReviewValidationError,
    ) as exc:
        flash(f"برگشت اصلاح مالی انجام نشد: {exc}", "error")
        return redirect(url_for("finance_review.index"))
    log_activity(
        "financial_adjustment_reverse",
        f"adjustment={adjustment_id}",
        patient_link_id=int(event["patient_link_id"]),
    )
    flash("اصلاح مالی برگشت داده شد؛ تاریخچه حفظ شد.", "success")
    return redirect(
        url_for("finance_review.index")
        + f"#invoice-{event['accounting_invoice_id']}"
    )


@bp.post("/invoice/<int:invoice_id>/review")
@permission_required(Permission.FINANCIAL_REVIEW_COMPLETE)
def complete_review(invoice_id: int):
    service = SpecialistPayerAdjustmentService()
    try:
        event = service.mark_reviewed(
            accounting_invoice_id=invoice_id,
            actor_username=g.user["username"],
            actor_user_id=int(g.user["id"]),
            with_adjustment=request.form.get("with_adjustment") == "1",
            note=request.form.get("note") or "",
            expected_current_event_id=request.form.get(
                "expected_current_event_id", type=int
            ),
            idempotency_key=(
                request.form.get("idempotency_key")
                or f"financial-review:{invoice_id}:{uuid.uuid4().hex}"
            ),
        )
    except (
        LookupError,
        TypeError,
        ValueError,
        SpecialistFinancialReviewConflict,
        SpecialistFinancialReviewValidationError,
    ) as exc:
        flash(f"بازبینی مالی تکمیل نشد: {exc}", "error")
    else:
        log_activity(
            "financial_review_complete",
            f"invoice={invoice_id} type={event['event_type']}",
            patient_link_id=int(event["patient_link_id"]),
        )
        flash("بازبینی مالی برای snapshot فعلی ثبت شد.", "success")
    return redirect(url_for("finance_review.index") + f"#invoice-{invoice_id}")
