from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def target(relative: str) -> Path:
    path = ROOT / relative
    if not path.exists():
        raise AssertionError(f"A7 routes target missing: {relative}")
    return path


def replace_once(relative: str, old: str, new: str) -> None:
    path = target(relative)
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise AssertionError(f"A7 routes anchor missing in {relative}: {old[:240]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Register finance-review blueprint.
replace_once(
    "specialist_clinic/src/app.py",
    '''    from src.api.followups import bp as followups_bp
    from src.api.health import bp as health_bp
''',
    '''    from src.api.followups import bp as followups_bp
    from src.api.finance_review import bp as finance_review_bp
    from src.api.health import bp as health_bp
''',
)
replace_once(
    "specialist_clinic/src/app.py",
    '''        followups_bp,
        sms_bp,
''',
    '''        followups_bp,
        finance_review_bp,
        sms_bp,
''',
)

# Navigation.
replace_once(
    "specialist_clinic/src/templates/base.html",
    '''            <a class="nav-item {% if active_page=='sms' %}active{% endif %}" href="{{ url_for('sms.campaigns') }}"{% if active_page=='sms' %} aria-current="page"{% endif %}><svg class="icon"><use href="#i-megaphone"></use></svg> هاب پیام</a>
''',
    '''            <a class="nav-item {% if active_page=='sms' %}active{% endif %}" href="{{ url_for('sms.campaigns') }}"{% if active_page=='sms' %} aria-current="page"{% endif %}><svg class="icon"><use href="#i-megaphone"></use></svg> هاب پیام</a>
            {% if permissions.get('financial.review.view') %}
            <a class="nav-item {% if active_page=='finance_review' %}active{% endif %}" href="{{ url_for('finance_review.index') }}"{% if active_page=='finance_review' %} aria-current="page"{% endif %}><svg class="icon"><use href="#i-banknote"></use></svg> بازبینی وصول</a>
            {% endif %}
''',
)

# Dashboard projection includes reviewed payer/adjustment totals without making the
# gross A4 dashboard unavailable while reviews are pending.
replace_once(
    "specialist_clinic/src/services/revenue_service.py",
    '''        total = self.funnel.finance_totals()
        month = self.funnel.finance_totals(
''',
    '''        total = self.funnel.finance_totals()
        from src.adapters.sqlite.specialist_payer_adjustment_repo import (
            SpecialistPayerAdjustmentRepository,
        )
        payer_review = SpecialistPayerAdjustmentRepository().reviewed_finance_totals()
        month = self.funnel.finance_totals(
''',
)
replace_once(
    "specialist_clinic/src/services/revenue_service.py",
    '''            "campaigns": self.campaign_revenue(),
            "scope": scope,
''',
    '''            "campaigns": self.campaign_revenue(),
            "payer_review": payer_review,
            "scope": scope,
''',
)

# Campaign financial rows use only current reviewed adjustment snapshots.
repo_path = target("specialist_clinic/src/adapters/sqlite/campaign_economics_repo.py")
repo = repo_path.read_text(encoding="utf-8")
old_query = '''            """SELECT attribution.journey_id,
                      attribution.patient_link_id,
                      attribution.response_event_id,
                      observation.accounting_invoice_id,
                      observation.invoice_status,
                      observation.billed_amount,
                      observation.collected_amount,
                      observation.collection_state,
                      observation.observed_at
               FROM campaign_journey_attribution_events attribution
               LEFT JOIN specialist_financial_observations observation
                 ON observation.journey_id=attribution.journey_id
                AND observation.id=(
                    SELECT latest.id FROM specialist_financial_observations latest
                    WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
                    ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
                )
'''
new_query = '''            """SELECT attribution.journey_id,
                      attribution.patient_link_id,
                      attribution.response_event_id,
                      observation.accounting_invoice_id,
                      observation.invoice_status,
                      observation.billed_amount,
                      observation.collected_amount AS gross_collected_amount,
                      observation.collection_state,
                      observation.observed_at,
                      review.id AS financial_review_event_id,
                      review.status AS financial_review_status,
                      CASE WHEN review.status='REVIEWED'
                                AND review.financial_observation_id=observation.id
                           THEN 1 ELSE 0 END AS financial_review_ready,
                      COALESCE((
                          SELECT SUM(adjustment.signed_amount)
                          FROM specialist_financial_adjustment_events adjustment
                          WHERE adjustment.accounting_invoice_id=observation.accounting_invoice_id
                            AND adjustment.financial_observation_id=observation.id
                            AND adjustment.id=(
                                SELECT head.id
                                FROM specialist_financial_adjustment_events head
                                WHERE head.adjustment_id=adjustment.adjustment_id
                                ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                            ) AND adjustment.status='ACTIVE'
                      ),0) AS adjustment_total,
                      observation.collected_amount+COALESCE((
                          SELECT SUM(adjustment.signed_amount)
                          FROM specialist_financial_adjustment_events adjustment
                          WHERE adjustment.accounting_invoice_id=observation.accounting_invoice_id
                            AND adjustment.financial_observation_id=observation.id
                            AND adjustment.id=(
                                SELECT head.id
                                FROM specialist_financial_adjustment_events head
                                WHERE head.adjustment_id=adjustment.adjustment_id
                                ORDER BY head.recorded_at DESC,head.id DESC LIMIT 1
                            ) AND adjustment.status='ACTIVE'
                      ),0) AS adjusted_collected_amount
               FROM campaign_journey_attribution_events attribution
               LEFT JOIN specialist_financial_observations observation
                 ON observation.journey_id=attribution.journey_id
                AND observation.id=(
                    SELECT latest.id FROM specialist_financial_observations latest
                    WHERE latest.accounting_invoice_id=observation.accounting_invoice_id
                    ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
                )
               LEFT JOIN specialist_financial_review_events review
                 ON review.accounting_invoice_id=observation.accounting_invoice_id
                AND review.id=(
                    SELECT review_head.id FROM specialist_financial_review_events review_head
                    WHERE review_head.accounting_invoice_id=observation.accounting_invoice_id
                    ORDER BY review_head.recorded_at DESC,review_head.id DESC LIMIT 1
                )
'''
if new_query not in repo:
    if old_query not in repo:
        raise AssertionError("A7 campaign financial query anchor missing")
    repo = repo.replace(old_query, new_query, 1)
repo = repo.replace(
    '''        observed_journeys = {row["journey_id"] for row in financial if row["accounting_invoice_id"] is not None}
        attributed_journeys = {row["journey_id"] for row in trusted_attributions}
        billed = sum(int(row["billed_amount"] or 0) for row in financial)
        collected = sum(int(row["collected_amount"] or 0) for row in financial)
        invoices = sum(1 for row in financial if row["accounting_invoice_id"] is not None)
''',
    '''        observed_journeys = {
            row["journey_id"]
            for row in financial
            if row["accounting_invoice_id"] is not None
        }
        reviewed_journeys = {
            row["journey_id"]
            for row in financial
            if int(row["financial_review_ready"] or 0) == 1
        }
        attributed_journeys = {row["journey_id"] for row in trusted_attributions}
        billed = sum(int(row["billed_amount"] or 0) for row in financial)
        gross_collected = sum(
            int(row["gross_collected_amount"] or 0) for row in financial
        )
        adjustment_total = sum(
            int(row["adjustment_total"] or 0)
            for row in financial
            if int(row["financial_review_ready"] or 0) == 1
        )
        collected = sum(
            int(row["adjusted_collected_amount"] or 0)
            for row in financial
            if int(row["financial_review_ready"] or 0) == 1
        )
        invoices = sum(
            1 for row in financial if row["accounting_invoice_id"] is not None
        )
''',
    1,
)
repo = repo.replace(
    '''        finance_complete = attributed_journeys <= observed_journeys
''',
    '''        finance_complete = attributed_journeys <= observed_journeys
        adjustment_review_complete = attributed_journeys <= reviewed_journeys
''',
    1,
)
repo = repo.replace(
    '''            and finance_complete
            and not stale_attributions
''',
    '''            and finance_complete
            and adjustment_review_complete
            and not stale_attributions
''',
    1,
)
repo = repo.replace(
    '''        elif not finance_complete:
            measurement_status = "FINANCIAL_RECONCILIATION_INCOMPLETE"
''',
    '''        elif not finance_complete:
            measurement_status = "FINANCIAL_RECONCILIATION_INCOMPLETE"
        elif not adjustment_review_complete:
            measurement_status = "FINANCIAL_ADJUSTMENT_REVIEW_REQUIRED"
''',
    1,
)
repo = repo.replace(
    '''            "finance": {
                "billed": billed,
                "collected": collected,
''',
    '''            "finance": {
                "billed": billed,
                "gross_collected": gross_collected,
                "adjustment_total": adjustment_total,
                "collected": collected,
''',
    1,
)
repo = repo.replace(
    '''                "observed_journeys": len(observed_journeys),
                "missing_journeys": len(attributed_journeys - observed_journeys),
''',
    '''                "observed_journeys": len(observed_journeys),
                "reviewed_journeys": len(reviewed_journeys),
                "missing_journeys": len(attributed_journeys - observed_journeys),
                "pending_adjustment_review": len(
                    attributed_journeys - reviewed_journeys
                ),
''',
    1,
)
repo_path.write_text(repo, encoding="utf-8")

# Campaign UI status label.
replace_once(
    "specialist_clinic/src/templates/sms/campaign_detail.html",
    '''    'STALE_RESPONSE_ATTRIBUTION_REVIEW_REQUIRED':'پاسخ بیمار پس از انتساب اصلاح شده و انتساب نیازمند بازبینی است'
''',
    '''    'STALE_RESPONSE_ATTRIBUTION_REVIEW_REQUIRED':'پاسخ بیمار پس از انتساب اصلاح شده و انتساب نیازمند بازبینی است',
    'FINANCIAL_ADJUSTMENT_REVIEW_REQUIRED':'refund/chargeback/تسویهٔ بیمه برای فاکتور منتسب هنوز بازبینی نشده است'
''',
)

# Dashboard shows A7 review quality and a direct route to pending work.
replace_once(
    "specialist_clinic/src/templates/dashboard.html",
    '''    <div class="dashboard-billing-mix">
''',
    '''    {% if revenue.payer_review %}
    <div class="alert-banner {% if revenue.payer_review.safe_to_sum %}alert-info{% else %}alert-warn{% endif %}" style="margin-top:var(--s3);">
        <svg class="icon"><use href="#i-banknote"></use></svg>
        <span>
            بازبینی payer/adjustment:
            {{ revenue.payer_review.reviewed_invoices|fa_num }} از
            {{ revenue.payer_review.invoices|fa_num }} فاکتور.
            {% if revenue.payer_review.safe_to_sum %}
            خالص تعدیل‌شدهٔ بازبینی‌شده: {{ revenue.payer_review.adjusted_collected|fa_num }} تومان.
            {% else %}
            تا تکمیل {{ revenue.payer_review.pending_review|fa_num }} بازبینی، جمع خالص منتشر نمی‌شود.
            {% endif %}
            {% if permissions.get('financial.review.view') %}<a href="{{ url_for('finance_review.index') }}">بازکردن بازبینی وصول</a>{% endif %}
        </span>
    </div>
    {% endif %}

    <div class="dashboard-billing-mix">
''',
)

Path(__file__).unlink()
