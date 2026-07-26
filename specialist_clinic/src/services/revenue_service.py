"""Authoritative specialist-clinic revenue and explicit campaign attribution projection.

Accounting remains read-only. Main financial KPIs require a completed attributed
Encounter. Campaign revenue requires an additional positive patient-response event and
one exclusive current campaign attribution for that Journey; time windows are not used.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import jdatetime

from src.adapters import specialist_accounting_invoice_reader as accounting_reader
from src.adapters.sqlite.campaign_journey_attribution_repo import (
    CampaignJourneyAttributionRepository,
)
from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.adapters.sqlite.specialist_finance_repo import SpecialistFinanceRepository
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelRepository,
)
from src.common.utils import format_jalali_date, iran_now


def _jalali_month_start_gregorian() -> str:
    j_today = jdatetime.date.fromgregorian(date=iran_now().date())
    gregorian = jdatetime.date(j_today.year, j_today.month, 1).togregorian()
    return gregorian.strftime("%Y-%m-%d")


class RevenueService:
    """Audited financial projection with explicit completed-Encounter scope."""

    POLICY_VERSION = "EXPLICIT_RESPONSE_JOURNEY_ATTRIBUTION_V3"
    FRESHNESS_MINUTES = 15

    def __init__(
        self,
        *,
        journeys: CareJourneyRepository | None = None,
        enrollments: SpecialistEnrollmentRepository | None = None,
        finance: SpecialistFinanceRepository | None = None,
        funnel: SpecialistFinancialFunnelRepository | None = None,
        campaign_attribution: CampaignJourneyAttributionRepository | None = None,
        accounting=None,
        clock=None,
    ):
        self.journeys = journeys or CareJourneyRepository()
        self.enrollments = enrollments or SpecialistEnrollmentRepository()
        self.finance = finance or SpecialistFinanceRepository()
        self.funnel = funnel or SpecialistFinancialFunnelRepository()
        self.campaign_attribution = (
            campaign_attribution or CampaignJourneyAttributionRepository()
        )
        self.accounting = accounting or accounting_reader
        self.clock = clock or iran_now

    @staticmethod
    def _naive(value: datetime) -> datetime:
        return value.replace(tzinfo=None) if value.tzinfo is not None else value

    def dashboard(self) -> dict:
        now = self.clock()
        now_naive = self._naive(now)
        journey_scope = self.journeys.scope_summary()
        reconciliation = self.funnel.reconciliation_scope()
        funnel = self.funnel.funnel_summary()
        scope = {
            **journey_scope,
            **reconciliation,
            "policy_version": self.POLICY_VERSION,
            "history_visible_but_excluded": True,
            "time_only_attribution": False,
            "completed_encounter_required": True,
            "campaign_positive_response_required": True,
            "campaign_journey_exclusive": True,
            "payment_evidence": "ITEM_PAID_FLAGS",
            "as_of": now.isoformat(sep=" ", timespec="seconds"),
        }

        if scope["linked_patients_missing_cutover"]:
            return {
                "available": False,
                "error_code": "SPECIALIST_CUTOVER_MISSING",
                "scope": scope,
                "funnel": funnel,
            }
        if not self.accounting.is_available():
            return {
                "available": False,
                "error_code": "ACCOUNTING_DATABASE_UNAVAILABLE",
                "scope": scope,
                "funnel": funnel,
            }
        if reconciliation["missing_observations"]:
            return {
                "available": False,
                "error_code": "FINANCIAL_RECONCILIATION_INCOMPLETE",
                "scope": scope,
                "funnel": funnel,
            }

        latest_at = reconciliation.get("latest_observed_at")
        if reconciliation["eligible_invoices"] and not latest_at:
            return {
                "available": False,
                "error_code": "FINANCIAL_OBSERVATION_MISSING",
                "scope": scope,
                "funnel": funnel,
            }
        if latest_at:
            try:
                observed = datetime.fromisoformat(str(latest_at))
            except ValueError:
                return {
                    "available": False,
                    "error_code": "FINANCIAL_OBSERVATION_TIMESTAMP_INVALID",
                    "scope": scope,
                    "funnel": funnel,
                }
            age_minutes = max(
                int((now_naive - observed).total_seconds() // 60), 0
            )
            scope["observation_age_minutes"] = age_minutes
            if age_minutes > self.FRESHNESS_MINUTES:
                return {
                    "available": False,
                    "error_code": "FINANCIAL_OBSERVATION_STALE",
                    "scope": scope,
                    "funnel": funnel,
                }
        else:
            scope["observation_age_minutes"] = 0
            scope["freshness_status"] = "NO_COMPLETED_ENCOUNTERS"

        total = self.funnel.finance_totals()
        month = self.funnel.finance_totals(
            floor=_jalali_month_start_gregorian()
        )
        today = now.date()
        start = today - timedelta(days=29)
        daily = self.funnel.daily_totals(
            start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        )

        labels: list[str] = []
        billed_values: list[int] = []
        collected_values: list[int] = []
        for offset in range(30):
            day = start + timedelta(days=offset)
            key = day.strftime("%Y-%m-%d")
            bucket = daily.get(key) or {"billed": 0, "collected": 0}
            labels.append(format_jalali_date(key))
            billed_values.append(int(bucket["billed"] or 0))
            collected_values.append(int(bucket["collected"] or 0))

        scope["financially_observed_invoices"] = reconciliation[
            "observed_invoices"
        ]
        return {
            "available": True,
            "enrolled": self.enrollments.count(),
            "total": total,
            "month": month,
            "trend": {
                "labels": labels,
                "billed_values": billed_values,
                "collected_values": collected_values,
                "values": collected_values,
            },
            "funnel": funnel,
            "campaigns": self.campaign_revenue(),
            "scope": scope,
        }

    def campaign_revenue(self, ids_hint: list[int] | None = None) -> dict:
        """Collected revenue from exclusive, explicit response→Journey links.

        This is auditable operational attribution, not a causal-lift claim. Each Journey
        has at most one current campaign attribution, so totals are safe to sum without
        double-counting the same Journey across campaigns.
        """
        requested = {int(value) for value in (ids_hint or [])}
        rows: list[dict] = []
        attributed_total = 0
        billed_total = 0
        credit_distributed = 0
        pending_financial = 0
        for campaign in self.finance.campaigns():
            campaign_id = int(campaign["id"])
            if requested and campaign_id not in requested:
                continue
            metrics = self.campaign_attribution.campaign_metrics(campaign_id)
            credit = self.finance.positive_campaign_credit(campaign_id)
            credit_distributed += credit
            attributed_total += metrics["collected"]
            billed_total += metrics["billed"]
            pending_financial += metrics["pending_financial"]
            rows.append(
                {
                    "id": campaign_id,
                    "name": campaign["name"],
                    "type": campaign["campaign_type"],
                    "recipients": metrics["audience_treated"],
                    "audience_total": metrics["audience_total"],
                    "control": metrics["audience_control"],
                    "sent": int(campaign.get("sent_count") or 0),
                    "delivered": int(campaign.get("delivered_count") or 0),
                    "positive_responses": metrics["positive_responses"],
                    "attributed_journeys": metrics["attributed_journeys"],
                    "billed": metrics["billed"],
                    "revenue": metrics["collected"],
                    "invoices": metrics["invoices"],
                    "pending_financial": metrics["pending_financial"],
                    "credit": credit,
                    "measurement_status": "EXPLICIT_RESPONSE_JOURNEY",
                }
            )
        return {
            "rows": rows,
            "attributed_total": attributed_total,
            "billed_total": billed_total,
            "credit_distributed": credit_distributed,
            "pending_financial": pending_financial,
            "window_days": None,
            "safe_to_sum": True,
            "causal_claim": False,
            "measurement_status": "EXPLICIT_RESPONSE_JOURNEY",
        }

    def campaign_incrementality(self, campaign_id: int) -> dict | None:
        # Operational attribution is not causal lift. Incrementality remains unavailable
        # until immutable treated/control exposure and sufficient outcomes are validated.
        return None
