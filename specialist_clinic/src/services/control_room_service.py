"""Administrative patient worklist and cohort projection.

Clinical priority belongs exclusively to Clinical Engine v2.  The optional business-value
dimension is also fail-closed: it uses only collected amounts from accounting invoices
explicitly attributed to a specialist CareJourney/Encounter. Historical or general-clinic
revenue never changes the worklist score.
"""
from __future__ import annotations

from datetime import datetime

from src.adapters import specialist_accounting_revenue
from src.adapters.sqlite.care_journey_repo import CareJourneyRepository
from src.adapters.sqlite.core import get_db
from src.common.utils import format_jalali_date, iran_now
from src.services.followup_projection_service import FollowupProjectionService


LAPSED_DAYS = 120
COHORT_DEFS = (
    ("lapsed", "بدون ثبت دادهٔ اخیر"),
    ("overdue_care", "پیگیری باز"),
    ("refill_due", "تجدید نسخه سررسیده"),
    ("no_show", "عدم مراجعه ثبت‌شده"),
    ("valuable_lapsed", "ارزشمند و بدون مراجعه اخیر"),
)


class ControlRoomService:
    VALUE_POLICY = "EXPLICIT_SPECIALIST_ATTRIBUTION_V1"

    def panel(self, show_value: bool = True) -> dict:
        db = get_db()
        now = iran_now()
        rows = db.execute(
            """SELECT p.id, p.full_name, p.phone_number,
                      p.accounting_patient_id, p.enrolled_at,
                      COALESCE(p.sms_opt_out, 0) AS opt_out,
                      MAX(
                        COALESCE((SELECT MAX(v.measured_at)
                                  FROM vital_readings v
                                  WHERE v.patient_link_id=p.id), ''),
                        COALESCE((SELECT MAX(l.taken_at)
                                  FROM lab_results l
                                  WHERE l.patient_link_id=p.id), '')
                      ) AS last_observation,
                      (SELECT COUNT(*) FROM followup_tasks f
                       WHERE f.patient_link_id=p.id AND f.status='open') AS open_fu,
                      (SELECT COUNT(*) FROM patient_medications m
                       WHERE m.patient_link_id=p.id AND m.is_active=1
                         AND m.refill_due_date IS NOT NULL
                         AND m.refill_due_date <= date(
                             'now','+3 hours','+30 minutes','+7 days'
                         )) AS refill_due,
                      (SELECT COUNT(*) FROM appointments a
                       WHERE a.patient_link_id=p.id AND a.status='no_show') AS no_show,
                      EXISTS(
                        SELECT 1 FROM appointments a
                        WHERE a.patient_link_id=p.id AND a.status='scheduled'
                          AND a.scheduled_at >= datetime(
                              'now','+3 hours','+30 minutes'
                          )
                      ) AS upcoming
               FROM patient_links p
               WHERE p.is_active=1
               ORDER BY p.id"""
        ).fetchall()

        conditions: dict[int, list[str]] = {}
        for row in db.execute(
            """SELECT pc.patient_link_id AS patient_id, c.name
               FROM patient_conditions pc
               JOIN conditions c ON c.id=pc.condition_id
               WHERE pc.is_active=1"""
        ):
            conditions.setdefault(int(row["patient_id"]), []).append(row["name"])

        revenue: dict[int, int] = {}
        median_revenue = 0
        value_available = False
        value_error = None
        if show_value:
            try:
                patient_ids = [int(row["id"]) for row in rows]
                invoice_map = CareJourneyRepository().attributed_invoices_by_patient(
                    patient_ids
                )
                all_invoice_ids = sorted(
                    {
                        invoice_id
                        for invoice_ids in invoice_map.values()
                        for invoice_id in invoice_ids
                    }
                )
                collected = specialist_accounting_revenue.collected_by_invoice_ids(
                    all_invoice_ids
                )
                for patient_id, invoice_ids in invoice_map.items():
                    revenue[patient_id] = sum(
                        int(collected.get(invoice_id, 0) or 0)
                        for invoice_id in invoice_ids
                    )
                values = sorted(value for value in revenue.values() if value > 0)
                median_revenue = values[len(values) // 2] if values else 0
                value_available = True
            except (
                specialist_accounting_revenue.AccountingRevenueUnavailable,
                specialist_accounting_revenue.AccountingRevenueSchemaError,
            ) as exc:
                # Financial unavailability must never demote/upgrade a patient silently.
                revenue = {}
                median_revenue = 0
                value_error = type(exc).__name__.upper()

        open_followup_counts = FollowupProjectionService().open_counts_by_patient()
        patients: list[dict] = []
        summary = {
            "total": len(rows),
            "with_observation": 0,
            "lapsed": 0,
            "open_followup_patients": 0,
            "refill_due_patients": 0,
            "no_show_patients": 0,
            "action_required": 0,
        }
        for row in rows:
            patient_id = int(row["id"])
            last_observation = row["last_observation"] or None
            days_since_data = None
            if last_observation:
                summary["with_observation"] += 1
                try:
                    measured = datetime.strptime(
                        str(last_observation)[:10], "%Y-%m-%d"
                    )
                    days_since_data = (now.replace(tzinfo=None) - measured).days
                except ValueError:
                    days_since_data = None
            lapsed = days_since_data is None or days_since_data > LAPSED_DAYS
            open_followups = int(open_followup_counts.get(patient_id, 0))
            refill_due = int(row["refill_due"] or 0)
            no_show = int(row["no_show"] or 0)
            upcoming = bool(row["upcoming"])
            if lapsed:
                summary["lapsed"] += 1
            if open_followups:
                summary["open_followup_patients"] += 1
            if refill_due:
                summary["refill_due_patients"] += 1
            if no_show:
                summary["no_show_patients"] += 1

            breakdown: list[tuple[str, int]] = []
            score = 0
            reasons: list[str] = []
            if open_followups:
                points = min(open_followups, 3)
                score += points
                breakdown.append((f"{open_followups} پیگیری باز", points))
                reasons.append("پیگیری باز")
            if refill_due:
                points = min(refill_due, 2)
                score += points
                breakdown.append((f"{refill_due} تجدید نسخه", points))
                reasons.append("تجدید نسخه")
            if lapsed:
                score += 2
                breakdown.append(("بدون ثبت دادهٔ اخیر", 2))
                reasons.append("وقفه در ثبت داده")
            if no_show:
                score += 1
                breakdown.append((f"{no_show} عدم مراجعه", 1))
                reasons.append("عدم مراجعه")
            value = revenue.get(patient_id, 0)
            if (
                show_value
                and value_available
                and median_revenue
                and value > median_revenue
                and lapsed
            ):
                score += 1
                breakdown.append(("ارزش وصولی تخصصی بالاتر از میانه", 1))
            if upcoming:
                score = max(0, score - 1)
                breakdown.append(("نوبت پیش‌رو", -1))

            if score <= 0:
                continue
            patients.append(
                {
                    "id": patient_id,
                    "name": row["full_name"],
                    "phone": row["phone_number"],
                    "opt_out": bool(row["opt_out"]),
                    "lapsed": lapsed,
                    "days": days_since_data,
                    "open_fu": open_followups,
                    "refill_due": refill_due,
                    "no_show": no_show,
                    "value": value,
                    "score": score,
                    "breakdown": breakdown,
                    "reasons": reasons,
                    "conditions": conditions.get(patient_id, []),
                    "upcoming": upcoming,
                    "last_fa": (
                        format_jalali_date(last_observation)
                        if last_observation
                        else "—"
                    ),
                }
            )

        patients.sort(key=lambda item: (-item["score"], item["name"], item["id"]))

        def in_cohort(patient: dict, key: str) -> bool:
            if key == "lapsed":
                return patient["lapsed"]
            if key == "overdue_care":
                return patient["open_fu"] > 0
            if key == "refill_due":
                return patient["refill_due"] > 0
            if key == "no_show":
                return patient["no_show"] > 0
            if key == "valuable_lapsed":
                return (
                    show_value
                    and value_available
                    and median_revenue > 0
                    and patient["value"] > median_revenue
                    and patient["lapsed"]
                )
            return False

        cohorts = []
        for key, label in COHORT_DEFS:
            if key == "valuable_lapsed" and (not show_value or not value_available):
                continue
            ids = [patient["id"] for patient in patients if in_cohort(patient, key)]
            cohorts.append({"key": key, "label": label, "count": len(ids), "ids": ids})

        summary["action_required"] = len(patients)
        return {
            "patients": patients,
            "cohorts": cohorts,
            "median_rev": median_revenue,
            "total": len(patients),
            "summary": summary,
            "show_value": show_value,
            "value_available": value_available,
            "value_error": value_error,
            "value_policy": self.VALUE_POLICY,
            "projection_policy": "ADMINISTRATIVE_ONLY",
        }

    def cohort_ids(self, cohort_key: str, show_value: bool = True) -> list[int]:
        data = self.panel(show_value=show_value)
        return next(
            (
                cohort["ids"]
                for cohort in data["cohorts"]
                if cohort["key"] == cohort_key
            ),
            [],
        )

    @staticmethod
    def conversion() -> dict:
        """Legacy booking metric retained but explicitly not called revenue conversion."""
        db = get_db()
        row = db.execute(
            """SELECT COUNT(*) AS resolved,
                      SUM(CASE WHEN appointment_id IS NOT NULL THEN 1 ELSE 0 END)
                          AS booked
               FROM followup_tasks WHERE status='done'"""
        ).fetchone()
        resolved = int(row["resolved"] or 0)
        booked = int(row["booked"] or 0)
        return {
            "resolved": resolved,
            "to_visit": booked,
            "booked": booked,
            "rate": round(booked * 100 / resolved, 1) if resolved else 0,
            "metric": "BOOKING_RATE_NOT_REVENUE_CONVERSION",
        }
