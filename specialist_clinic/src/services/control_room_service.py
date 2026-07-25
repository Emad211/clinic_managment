"""Administrative patient worklist and cohort projection.

This service deliberately does not inspect clinical values, thresholds, targets or
risk weights.  It ranks only operational work already present in the record: stale
data collection, open follow-ups, refill dates, missed appointments and an optional
manager-only business-value dimension.  Clinical priority is owned exclusively by
Clinical Engine v2 and its audited follow-up tasks.
"""
from __future__ import annotations

from datetime import datetime

from src.adapters import accounting_bridge
from src.adapters.sqlite.core import get_db
from src.common.utils import format_jalali_date, iran_now


LAPSED_DAYS = 120
COHORT_DEFS = (
    ("lapsed", "بدون ثبت دادهٔ اخیر"),
    ("overdue_care", "پیگیری باز"),
    ("refill_due", "تجدید نسخه سررسیده"),
    ("no_show", "عدم مراجعه ثبت‌شده"),
    ("valuable_lapsed", "ارزشمند و بدون مراجعه اخیر"),
)


class ControlRoomService:
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
        if show_value and accounting_bridge.is_available():
            pairs = [
                (
                    int(row["accounting_patient_id"]),
                    str(row["enrolled_at"])[:10] if row["enrolled_at"] else None,
                )
                for row in rows
                if row["accounting_patient_id"]
            ]
            by_accounting_id = accounting_bridge.revenue_by_patient(pairs)
            for row in rows:
                accounting_id = row["accounting_patient_id"]
                if accounting_id and int(accounting_id) in by_accounting_id:
                    revenue[int(row["id"])] = int(by_accounting_id[int(accounting_id)] or 0)
            values = sorted(value for value in revenue.values() if value > 0)
            median_revenue = values[len(values) // 2] if values else 0

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
            open_followups = int(row["open_fu"] or 0)
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
            if show_value and median_revenue and value > median_revenue and lapsed:
                score += 1
                breakdown.append(("ارزش مالی بالاتر از میانه", 1))
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

        patients.sort(
            key=lambda item: (-item["score"], item["name"], item["id"])
        )

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
                    and median_revenue > 0
                    and patient["value"] > median_revenue
                    and patient["lapsed"]
                )
            return False

        cohorts = []
        for key, label in COHORT_DEFS:
            if key == "valuable_lapsed" and not show_value:
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
            "projection_policy": "ADMINISTRATIVE_ONLY",
        }

    def cohort_ids(self, cohort_key: str, show_value: bool = True) -> list[int]:
        """Recompute a cohort server-side; posted recipient ids are never trusted."""
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
        """Administrative follow-up-to-visit conversion, not a clinical outcome."""
        db = get_db()
        row = db.execute(
            """SELECT COUNT(*) AS resolved,
                      SUM(CASE WHEN appointment_id IS NOT NULL THEN 1 ELSE 0 END)
                          AS to_visit
               FROM followup_tasks WHERE status='done'"""
        ).fetchone()
        resolved = int(row["resolved"] or 0)
        to_visit = int(row["to_visit"] or 0)
        return {
            "resolved": resolved,
            "to_visit": to_visit,
            "rate": round(to_visit * 100 / resolved, 1) if resolved else 0,
        }
