"""Authoritative specialist-clinic revenue and conversion projection.

Accounting remains read-only and exposes complete patient history. Financial KPIs are
computed only from latest append-only observations of invoices that are explicitly
attributed to a COMPLETED specialist Encounter. Booking, attendance, service completion,
invoice closure and collection remain distinct stages.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import jdatetime

from src.adapters import specialist_accounting_invoice_reader as accounting_reader
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

    POLICY_VERSION = "COMPLETED_ENCOUNTER_OBSERVATION_V2"
    FRESHNESS_MINUTES = 15

    def __init__(
        self,
        *,
        journeys: CareJourneyRepository | None = None,
        enrollments: SpecialistEnrollmentRepository | None = None,
        finance: SpecialistFinanceRepository | None = None,
        funnel: SpecialistFinancialFunnelRepository | None = None,
        accounting=None,
        clock=None,
    ):
        self.journeys = journeys or CareJourneyRepository()
        self.enrollments = enrollments or SpecialistEnrollmentRepository()
        self.finance = finance or SpecialistFinanceRepository()
        self.funnel = funnel or SpecialistFinancialFunnelRepository()
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
        from src.adapters.sqlite.specialist_payer_adjustment_repo import (
            SpecialistPayerAdjustmentRepository,
        )
        payer_review = SpecialistPayerAdjustmentRepository().reviewed_finance_totals()
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
            "payer_review": payer_review,
            "scope": scope,
        }

    def campaign_revenue(self, ids_hint: list[int] | None = None) -> dict:
        """Campaign economics from explicit Journey/invoice lineage only."""
        from src.adapters.sqlite.campaign_economics_repo import (
            CampaignEconomicsRepository,
        )

        repository = CampaignEconomicsRepository()
        rows = []
        attributable_total = 0
        direct_cost_total = 0
        net_total = 0
        all_ready = True
        for campaign in self.finance.campaigns():
            projection = repository.campaign_projection(int(campaign["id"]))
            ready = bool(
                projection["safe_to_sum"]
                and projection["measurement_status"] == "READY"
            )
            all_ready = all_ready and ready
            if ready:
                attributable_total += int(projection["finance"]["collected"])
                direct_cost_total += int(projection["costs"]["direct_cost"])
                net_total += int(projection["net_contribution"])
            rows.append(
                {
                    "id": int(campaign["id"]),
                    "name": campaign["name"],
                    "type": campaign["campaign_type"],
                    "recipients": int(
                        projection["audience"].get("eligible_count") or 0
                    ),
                    "treated": int(
                        projection["audience"].get("treated_count") or 0
                    ),
                    "control": int(
                        projection["audience"].get("control_count") or 0
                    ),
                    "accepted": int(
                        projection["messages"].get("provider_accepted") or 0
                    ),
                    "sent": int(
                        projection["messages"].get("provider_accepted") or 0
                    ),
                    "delivered": int(projection["messages"]["delivered"]),
                    "positive_responses": int(
                        projection["responses"]["positive"]
                    ),
                    "journeys": int(projection["attributions"]["journeys"]),
                    "revenue": (
                        int(projection["finance"]["collected"])
                        if ready else None
                    ),
                    "invoices": int(projection["finance"]["invoices"]),
                    "direct_cost": (
                        int(projection["costs"]["direct_cost"])
                        if ready else None
                    ),
                    "net_contribution": (
                        int(projection["net_contribution"]) if ready else None
                    ),
                    "roi_percent": projection["roi_percent"] if ready else None,
                    "measurement_status": projection["measurement_status"],
                    "safe_to_sum": ready,
                }
            )
        safe_to_sum = bool(rows) and all_ready
        if not rows:
            measurement_status = "JOURNEY_LINK_REQUIRED"
        elif safe_to_sum:
            measurement_status = "READY"
        else:
            measurement_status = "CAMPAIGN_ECONOMICS_INCOMPLETE"
        return {
            "rows": rows,
            "attributed_total": attributable_total if safe_to_sum else 0,
            "direct_cost_total": direct_cost_total if safe_to_sum else 0,
            "net_contribution_total": net_total if safe_to_sum else 0,
            "credit_distributed": 0,
            "window_days": None,
            "safe_to_sum": safe_to_sum,
            "measurement_status": measurement_status,
            "policy_version": "EXPLICIT_CAMPAIGN_JOURNEY_ROI_V1",
        }

    def campaign_incrementality(self, campaign_id: int) -> dict | None:
        # No causal claim is published merely because a control group exists.
        # A6 reports explicit attribution and ROI; causal inference needs a separate,
        # adequately powered analysis contract.
        return None
