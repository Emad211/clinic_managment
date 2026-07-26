"""Authoritative specialist-clinic revenue projection.

Accounting remains read-only and continues to expose the patient's complete historical
visit record.  Financial KPIs in this service are intentionally narrower: only CLOSED
accounting invoices carrying a current, explicit ATTRIBUTED event tied to a specialist
CareJourney/Encounter are included.  Enrollment time alone never attributes revenue.
"""
from __future__ import annotations

from datetime import timedelta

import jdatetime

from src.adapters import specialist_accounting_revenue as accounting_revenue
from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
from src.adapters.sqlite.specialist_enrollment_repo import (
    SpecialistEnrollmentRepository,
)
from src.adapters.sqlite.specialist_finance_repo import (
    SpecialistFinanceRepository,
)
from src.common.utils import format_jalali_date, iran_now


def _jalali_month_start_gregorian() -> str:
    j_today = jdatetime.date.fromgregorian(date=iran_now().date())
    gregorian = jdatetime.date(j_today.year, j_today.month, 1).togregorian()
    return gregorian.strftime("%Y-%m-%d")


class RevenueService:
    """Read-only financial projection with an explicit specialist scope."""

    POLICY_VERSION = "EXPLICIT_SPECIALIST_ATTRIBUTION_V1"

    def __init__(
        self,
        *,
        journeys: CareJourneyRepository | None = None,
        enrollments: SpecialistEnrollmentRepository | None = None,
        finance: SpecialistFinanceRepository | None = None,
        accounting=None,
        clock=None,
    ):
        self.journeys = journeys or CareJourneyRepository()
        self.enrollments = enrollments or SpecialistEnrollmentRepository()
        self.finance = finance or SpecialistFinanceRepository()
        self.accounting = accounting or accounting_revenue
        self.clock = clock or iran_now

    def dashboard(self) -> dict:
        now = self.clock()
        scope = self.journeys.scope_summary()
        scope.update(
            {
                "policy_version": self.POLICY_VERSION,
                "history_visible_but_excluded": True,
                "time_only_attribution": False,
                "as_of": now.isoformat(sep=" ", timespec="seconds"),
            }
        )

        if not self.accounting.is_available():
            return {
                "available": False,
                "error_code": "ACCOUNTING_DATABASE_UNAVAILABLE",
                "scope": scope,
            }
        if scope["linked_patients_missing_cutover"]:
            return {
                "available": False,
                "error_code": "SPECIALIST_CUTOVER_MISSING",
                "scope": scope,
            }

        invoice_ids = self.journeys.attributed_invoice_ids()
        try:
            total = self.accounting.revenue_for_invoice_ids(invoice_ids)
            month = self.accounting.revenue_for_invoice_ids(
                invoice_ids,
                floor=_jalali_month_start_gregorian(),
            )
            today = now.date()
            start = today - timedelta(days=29)
            daily = self.accounting.daily_revenue_for_invoice_ids(
                invoice_ids,
                start.strftime("%Y-%m-%d"),
                today.strftime("%Y-%m-%d"),
            )
        except (
            accounting_revenue.AccountingRevenueUnavailable,
            accounting_revenue.AccountingRevenueSchemaError,
        ) as exc:
            return {
                "available": False,
                "error_code": type(exc).__name__.upper(),
                "scope": scope,
            }

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

        scope["attributed_invoices"] = len(invoice_ids)
        return {
            "available": True,
            "enrolled": self.enrollments.count(),
            "total": total,
            "month": month,
            "trend": {
                "labels": labels,
                "billed_values": billed_values,
                "collected_values": collected_values,
                # Backward-compatible key; now intentionally means collected cash.
                "values": collected_values,
            },
            "campaigns": self.campaign_revenue(),
            "scope": scope,
        }

    def campaign_revenue(self, ids_hint: list[int] | None = None) -> dict:
        """Fail-closed campaign projection until campaigns create explicit journeys.

        The previous time-window-only estimate could count unrelated general-clinic
        visits and could count the same invoice for multiple campaigns.  Returning zero
        with a machine-readable status is safer than publishing a persuasive false KPI.
        Tranche A2 will bind campaign response -> journey -> encounter -> invoice.
        """
        rows = []
        issued_credit = 0
        for campaign in self.finance.campaigns():
            credit = self.finance.positive_campaign_credit(campaign["id"])
            issued_credit += credit
            rows.append(
                {
                    "id": campaign["id"],
                    "name": campaign["name"],
                    "type": campaign["campaign_type"],
                    "recipients": 0,
                    "sent": int(campaign.get("sent_count") or 0),
                    "delivered": int(campaign.get("delivered_count") or 0),
                    "revenue": 0,
                    "invoices": 0,
                    "credit": credit,
                    "measurement_status": "JOURNEY_LINK_REQUIRED",
                }
            )
        return {
            "rows": rows,
            "attributed_total": 0,
            "credit_distributed": issued_credit,
            "window_days": None,
            "safe_to_sum": False,
            "measurement_status": "JOURNEY_LINK_REQUIRED",
        }

    def campaign_incrementality(self, campaign_id: int) -> dict | None:
        # No causal/incremental figure is published before an explicit campaign journey
        # and exclusive invoice assignment exist.
        return None
