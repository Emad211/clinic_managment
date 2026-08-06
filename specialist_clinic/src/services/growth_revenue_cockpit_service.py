"""Source-backed growth and specialist revenue cockpit.

No historical accounting activity is counted unless it has explicit specialist encounter
and invoice attribution. Forecast is withheld when a trustworthy priced pipeline is not
available.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.leads_repo import LeadRepository
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelRepository,
)
from src.common.utils import iran_now
from src.services.lead_pipeline_service import LEAD_SOURCES


class GrowthRevenueCockpitService:
    def __init__(self):
        self.db = get_db()
        self.finance = SpecialistFinancialFunnelRepository(self.db)
        self.leads = LeadRepository(self.db)

    @staticmethod
    def _today() -> date:
        current = iran_now()
        return current.date()

    def _appointment_counts(self) -> dict:
        today_text = self._today().isoformat()
        month_start = self._today().replace(day=1).isoformat()
        row = self.db.execute(
            """SELECT
                 SUM(CASE WHEN status='scheduled'
                           AND date(scheduled_at)=date(?) THEN 1 ELSE 0 END) AS today_scheduled,
                 SUM(CASE WHEN status='done'
                           AND date(scheduled_at)=date(?) THEN 1 ELSE 0 END) AS today_done,
                 SUM(CASE WHEN status='no_show'
                           AND date(scheduled_at)>=date(?) THEN 1 ELSE 0 END) AS month_no_show,
                 SUM(CASE WHEN status='cancelled'
                           AND date(scheduled_at)>=date(?) THEN 1 ELSE 0 END) AS month_cancelled,
                 SUM(CASE WHEN status='scheduled'
                           AND datetime(scheduled_at)>=datetime('now','+3 hours','+30 minutes')
                           THEN 1 ELSE 0 END) AS upcoming
               FROM appointments""",
            (today_text, today_text, month_start, month_start),
        ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def _revenue_by_lead_source(self, observations: list[dict]) -> list[dict]:
        source_by_patient = {
            int(row["patient_link_id"]): str(row["source_code"])
            for row in self.db.execute(
                """SELECT patient_link_id,source_code
                   FROM growth_leads
                   WHERE status='CONVERTED' AND patient_link_id IS NOT NULL"""
            ).fetchall()
        }
        grouped: dict[str, dict] = defaultdict(
            lambda: {"patients": set(), "invoices": 0, "billed": 0, "collected": 0}
        )
        for observation in observations:
            patient_id = int(observation.get("patient_link_id") or 0)
            source = source_by_patient.get(patient_id, "EXISTING_PATIENT")
            bucket = grouped[source]
            bucket["patients"].add(patient_id)
            bucket["invoices"] += 1
            bucket["billed"] += int(observation.get("billed_amount") or 0)
            bucket["collected"] += int(observation.get("collected_amount") or 0)
        output = []
        for source, values in grouped.items():
            output.append(
                {
                    "source_code": source,
                    "source_label": (
                        "بیماران موجود / منبع قدیمی"
                        if source == "EXISTING_PATIENT"
                        else LEAD_SOURCES.get(source, source)
                    ),
                    "patients": len(values["patients"]),
                    "invoices": values["invoices"],
                    "billed": values["billed"],
                    "collected": values["collected"],
                }
            )
        return sorted(output, key=lambda row: (-row["collected"], row["source_label"]))

    def _referral_leaders(self, observations: list[dict]) -> list[dict]:
        lifecycle_rows = self.db.execute(
            """SELECT lead.referrer_patient_link_id AS referrer_id,
                      referrer.full_name AS referrer_name,
                      COUNT(*) AS referrals,
                      SUM(CASE WHEN lead.status='CONVERTED' THEN 1 ELSE 0 END) AS converted,
                      SUM(CASE WHEN lead.status='LOST' THEN 1 ELSE 0 END) AS lost,
                      SUM(CASE WHEN lead.status='APPOINTMENT_BOOKED'
                               THEN 1 ELSE 0 END) AS booked_open,
                      SUM(CASE WHEN lead.status='ATTENDED'
                               THEN 1 ELSE 0 END) AS attended_open
               FROM growth_leads lead
               JOIN patient_links referrer
                 ON referrer.id=lead.referrer_patient_link_id
               WHERE lead.source_code='PATIENT_REFERRAL'
                 AND lead.referrer_patient_link_id IS NOT NULL
               GROUP BY lead.referrer_patient_link_id,referrer.full_name"""
        ).fetchall()
        if not lifecycle_rows:
            return []

        referrer_by_referred_patient = {
            int(row["patient_link_id"]): int(row["referrer_patient_link_id"])
            for row in self.db.execute(
                """SELECT patient_link_id,referrer_patient_link_id
                   FROM growth_leads
                   WHERE source_code='PATIENT_REFERRAL'
                     AND status='CONVERTED'
                     AND patient_link_id IS NOT NULL
                     AND referrer_patient_link_id IS NOT NULL"""
            ).fetchall()
        }
        financial: dict[int, dict] = defaultdict(
            lambda: {
                "referred_patients_with_revenue": set(),
                "invoices": 0,
                "billed": 0,
                "collected": 0,
            }
        )
        for observation in observations:
            patient_id = int(observation.get("patient_link_id") or 0)
            referrer_id = referrer_by_referred_patient.get(patient_id)
            if referrer_id is None:
                continue
            bucket = financial[referrer_id]
            bucket["referred_patients_with_revenue"].add(patient_id)
            bucket["invoices"] += 1
            bucket["billed"] += int(observation.get("billed_amount") or 0)
            bucket["collected"] += int(observation.get("collected_amount") or 0)

        output = []
        for raw in lifecycle_rows:
            row = dict(raw)
            referrer_id = int(row["referrer_id"])
            values = financial[referrer_id]
            referrals = int(row["referrals"] or 0)
            converted = int(row["converted"] or 0)
            output.append(
                {
                    "referrer_id": referrer_id,
                    "referrer_name": row["referrer_name"],
                    "referrals": referrals,
                    "converted": converted,
                    "lost": int(row["lost"] or 0),
                    "booked_open": int(row["booked_open"] or 0),
                    "attended_open": int(row["attended_open"] or 0),
                    "conversion_rate": (
                        round(converted * 100 / referrals, 1)
                        if referrals
                        else 0.0
                    ),
                    "revenue_patients": len(
                        values["referred_patients_with_revenue"]
                    ),
                    "invoices": int(values["invoices"]),
                    "billed": int(values["billed"]),
                    "collected": int(values["collected"]),
                }
            )
        return sorted(
            output,
            key=lambda row: (
                -row["collected"],
                -row["converted"],
                -row["referrals"],
                row["referrer_name"],
            ),
        )

    def _lead_funnel(self) -> dict:
        counts = self.leads.counts()
        total = sum(
            counts.get(status, 0)
            for status in (
                "NEW",
                "CONTACTED",
                "APPOINTMENT_BOOKED",
                "ATTENDED",
                "CONVERTED",
                "LOST",
            )
        )
        decided = counts.get("CONVERTED", 0) + counts.get("LOST", 0)
        return {
            "counts": counts,
            "total": total,
            "conversion_rate": (
                round(counts.get("CONVERTED", 0) * 100 / decided, 1)
                if decided
                else 0.0
            ),
            "appointment_rate": (
                round(
                    (
                        counts.get("APPOINTMENT_BOOKED", 0)
                        + counts.get("ATTENDED", 0)
                        + counts.get("CONVERTED", 0)
                    )
                    * 100
                    / total,
                    1,
                )
                if total
                else 0.0
            ),
        }

    @staticmethod
    def _referral_summary(leaders: list[dict]) -> dict:
        return {
            "referrers": len(leaders),
            "referrals": sum(row["referrals"] for row in leaders),
            "converted": sum(row["converted"] for row in leaders),
            "billed": sum(row["billed"] for row in leaders),
            "collected": sum(row["collected"] for row in leaders),
        }

    def build(self) -> dict:
        today = self._today()
        month_start = today.replace(day=1)
        today_finance = self.finance.finance_totals(
            floor=today.isoformat(),
            until=today.isoformat(),
        )
        month_finance = self.finance.finance_totals(
            floor=month_start.isoformat(),
            until=today.isoformat(),
        )
        observations = [
            row
            for row in self.finance.latest_observations()
            if str(row.get("invoice_status") or "") == "closed"
            and row.get("work_date")
            and month_start.isoformat() <= str(row["work_date"]) <= today.isoformat()
        ]
        funnel = self.finance.funnel_summary()
        reconciliation = self.finance.reconciliation_scope()
        appointments = self._appointment_counts()
        lead_funnel = self._lead_funnel()
        referral_leaders = self._referral_leaders(observations)

        return {
            "today": today_finance,
            "month": {
                **month_finance,
                "outstanding": max(
                    int(month_finance.get("total") or 0)
                    - int(month_finance.get("collected") or 0),
                    0,
                ),
            },
            "financial_funnel": funnel,
            "reconciliation": reconciliation,
            "appointments": appointments,
            "lead_funnel": lead_funnel,
            "revenue_by_source": self._revenue_by_lead_source(observations),
            "referral_leaders": referral_leaders,
            "referral_summary": self._referral_summary(referral_leaders),
            "forecast": {
                "available": False,
                "reason": (
                    "برای پیش‌بینی معتبر، قیمت خدمت باید پیش از نوبت و با lineage "
                    "مشخص ثبت شود؛ تعداد نوبت به‌تنهایی درآمد محسوب نمی‌شود."
                ),
            },
            "evidence_note": (
                "فقط فاکتورهای بسته‌شده دارای Encounter، خدمت و انتساب صریح "
                "در درآمد کلینیک تخصصی محاسبه شده‌اند."
            ),
        }


__all__ = ["GrowthRevenueCockpitService"]
