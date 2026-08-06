"""Source-backed growth and specialist revenue cockpit.

No historical accounting activity is counted unless it has explicit specialist encounter
and invoice attribution. Forecast is withheld when a trustworthy priced pipeline is not
available. Converted Leads take precedence over explicit attribution for existing patients.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.leads_repo import LeadRepository
from src.adapters.sqlite.patient_acquisition_schema import (
    ensure_patient_acquisition_storage,
)
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelRepository,
)
from src.common.utils import iran_now
from src.services.lead_pipeline_service import LEAD_SOURCES


class GrowthRevenueCockpitService:
    def __init__(self):
        self.db = get_db()
        ensure_patient_acquisition_storage(self.db)
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

    def _patient_source_map(self) -> dict[int, str]:
        # Explicit attribution covers patients enrolled before the Lead pipeline.
        result = {
            int(row["patient_link_id"]): str(row["source_code"])
            for row in self.db.execute(
                """SELECT patient_link_id,source_code
                   FROM growth_patient_acquisition"""
            ).fetchall()
        }
        # A converted Lead is the stronger lifecycle evidence and always wins.
        result.update(
            {
                int(row["patient_link_id"]): str(row["source_code"])
                for row in self.db.execute(
                    """SELECT patient_link_id,source_code
                       FROM growth_leads
                       WHERE status='CONVERTED'
                         AND patient_link_id IS NOT NULL"""
                ).fetchall()
            }
        )
        return result

    def _revenue_by_lead_source(self, observations: list[dict]) -> list[dict]:
        source_by_patient = self._patient_source_map()
        grouped: dict[str, dict] = defaultdict(
            lambda: {
                "patients": set(),
                "invoices": 0,
                "billed": 0,
                "collected": 0,
            }
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
        return sorted(
            output,
            key=lambda row: (-row["collected"], row["source_label"]),
        )

    def _referral_records(self) -> list[dict]:
        records = [
            {
                "record_type": "LEAD",
                "record_id": int(row["id"]),
                "referrer_id": int(row["referrer_patient_link_id"]),
                "referrer_name": row["referrer_name_resolved"],
                "status": str(row["status"]),
                "referred_patient_id": (
                    int(row["patient_link_id"])
                    if row["patient_link_id"] is not None
                    else None
                ),
            }
            for row in self.db.execute(
                """SELECT lead.id,lead.referrer_patient_link_id,
                          referrer.full_name AS referrer_name_resolved,
                          lead.status,lead.patient_link_id
                   FROM growth_leads lead
                   JOIN patient_links referrer
                     ON referrer.id=lead.referrer_patient_link_id
                   WHERE lead.source_code='PATIENT_REFERRAL'
                     AND lead.referrer_patient_link_id IS NOT NULL"""
            ).fetchall()
        ]
        # Existing-patient attribution is already a converted patient. It is only added
        # when that patient is not represented by a converted Lead, preventing double count.
        records.extend(
            {
                "record_type": "EXPLICIT_ATTRIBUTION",
                "record_id": int(row["patient_link_id"]),
                "referrer_id": int(row["referrer_patient_link_id"]),
                "referrer_name": row["referrer_name_resolved"],
                "status": "CONVERTED",
                "referred_patient_id": int(row["patient_link_id"]),
            }
            for row in self.db.execute(
                """SELECT acquisition.patient_link_id,
                          acquisition.referrer_patient_link_id,
                          referrer.full_name AS referrer_name_resolved
                   FROM growth_patient_acquisition acquisition
                   JOIN patient_links referrer
                     ON referrer.id=acquisition.referrer_patient_link_id
                   WHERE acquisition.source_code='PATIENT_REFERRAL'
                     AND acquisition.referrer_patient_link_id IS NOT NULL
                     AND NOT EXISTS (
                       SELECT 1 FROM growth_leads lead
                       WHERE lead.patient_link_id=acquisition.patient_link_id
                         AND lead.status='CONVERTED'
                     )"""
            ).fetchall()
        )
        return records

    def _referral_leaders(self, observations: list[dict]) -> list[dict]:
        records = self._referral_records()
        if not records:
            return []

        lifecycle: dict[int, dict] = {}
        referrer_by_referred_patient: dict[int, int] = {}
        for record in records:
            referrer_id = int(record["referrer_id"])
            bucket = lifecycle.setdefault(
                referrer_id,
                {
                    "referrer_id": referrer_id,
                    "referrer_name": record["referrer_name"],
                    "referrals": 0,
                    "converted": 0,
                    "lost": 0,
                    "booked_open": 0,
                    "attended_open": 0,
                },
            )
            bucket["referrals"] += 1
            status = str(record["status"])
            if status == "CONVERTED":
                bucket["converted"] += 1
            elif status == "LOST":
                bucket["lost"] += 1
            elif status == "APPOINTMENT_BOOKED":
                bucket["booked_open"] += 1
            elif status == "ATTENDED":
                bucket["attended_open"] += 1
            patient_id = record.get("referred_patient_id")
            if patient_id is not None and status == "CONVERTED":
                referrer_by_referred_patient[int(patient_id)] = referrer_id

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
        for referrer_id, row in lifecycle.items():
            values = financial[referrer_id]
            referrals = int(row["referrals"])
            converted = int(row["converted"])
            output.append(
                {
                    **row,
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
            and month_start.isoformat()
            <= str(row["work_date"])
            <= today.isoformat()
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
