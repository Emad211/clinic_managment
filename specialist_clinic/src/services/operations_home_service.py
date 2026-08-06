"""Exception-first home context for daily clinic operation.

The service composes existing authoritative read models. It does not create a second
workflow, revenue model or clinical interpretation layer.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.growth_waitlist_repo import GrowthWaitlistRepository
from src.adapters.sqlite.leads_repo import LeadRepository
from src.common.utils import iran_now
from src.services.growth_automation_service import GrowthAutomationService
from src.services.growth_closed_loop_service import GrowthClosedLoopService
from src.services.growth_messaging_playbook_service import (
    GrowthMessagingPlaybookService,
)
from src.services.growth_revenue_cockpit_service import (
    GrowthRevenueCockpitService,
)
from src.services.growth_waitlist_service import GrowthWaitlistService


class OperationsHomeService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self.db = db or get_db()

    @staticmethod
    def _now() -> datetime:
        current = iran_now()
        if current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        return current.replace(microsecond=0)

    def _work_summary(self) -> dict:
        current = self._now().isoformat(sep=" ", timespec="seconds")
        row = self.db.execute(
            """SELECT
                 COUNT(*) AS open_count,
                 SUM(CASE WHEN due_date IS NOT NULL
                           AND datetime(due_date)<=datetime(?)
                          THEN 1 ELSE 0 END) AS due_count,
                 SUM(CASE WHEN assigned_to IS NULL OR TRIM(assigned_to)=''
                          THEN 1 ELSE 0 END) AS unassigned_count
               FROM followup_tasks
               WHERE status='open'""",
            (current,),
        ).fetchone()
        next_row = self.db.execute(
            """SELECT task.id,task.reason,task.detail,task.due_date,
                      task.assigned_to,patient.id AS patient_link_id,
                      patient.full_name AS patient_name
               FROM followup_tasks task
               JOIN patient_links patient ON patient.id=task.patient_link_id
               WHERE task.status='open'
               ORDER BY CASE WHEN task.due_date IS NULL THEN 1 ELSE 0 END,
                        datetime(task.due_date),task.id LIMIT 1"""
        ).fetchone()
        return {
            "open": int(row["open_count"] or 0),
            "due": int(row["due_count"] or 0),
            "unassigned": int(row["unassigned_count"] or 0),
            "next": dict(next_row) if next_row else None,
        }

    def _appointment_summary(self) -> dict:
        today = self._now().date().isoformat()
        row = self.db.execute(
            """SELECT
                 SUM(CASE WHEN status='scheduled' THEN 1 ELSE 0 END) AS scheduled,
                 SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done,
                 SUM(CASE WHEN status='no_show' THEN 1 ELSE 0 END) AS no_show,
                 SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancelled
               FROM appointments WHERE date(scheduled_at)=date(?)""",
            (today,),
        ).fetchone()
        next_row = self.db.execute(
            """SELECT appointment.*,patient.full_name AS patient_name
               FROM appointments appointment
               JOIN patient_links patient ON patient.id=appointment.patient_link_id
               WHERE appointment.status='scheduled'
                 AND datetime(appointment.scheduled_at)>=
                     datetime('now','+3 hours','+30 minutes')
               ORDER BY appointment.scheduled_at,appointment.id LIMIT 1"""
        ).fetchone()
        return {
            "scheduled": int(row["scheduled"] or 0),
            "done": int(row["done"] or 0),
            "no_show": int(row["no_show"] or 0),
            "cancelled": int(row["cancelled"] or 0),
            "next": dict(next_row) if next_row else None,
        }

    def _lead_summary(self) -> dict:
        repository = LeadRepository(self.db)
        counts = repository.counts()
        now_text = self._now().isoformat(sep=" ", timespec="seconds")
        due = repository.due(now_text)
        return {
            "counts": counts,
            "due": len(due),
            "next": due[0] if due else None,
        }

    def _quality_summary(self) -> dict:
        row = self.db.execute(
            """SELECT
                 SUM(CASE WHEN phone_number IS NULL OR TRIM(phone_number)=''
                          THEN 1 ELSE 0 END) AS missing_phone,
                 SUM(CASE WHEN national_id IS NULL OR TRIM(national_id)=''
                          THEN 1 ELSE 0 END) AS missing_national_id,
                 SUM(CASE WHEN birthdate IS NULL OR TRIM(birthdate)=''
                          THEN 1 ELSE 0 END) AS missing_birthdate
               FROM patient_links WHERE is_active=1"""
        ).fetchone()
        legacy_medications = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM patient_medications
                   WHERE is_active=1 AND drug_catalog_id IS NULL"""
            ).fetchone()["count"]
            or 0
        )
        legacy_labs = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM lab_results
                   WHERE test_key IS NULL OR TRIM(test_key)=''"""
            ).fetchone()["count"]
            or 0
        )
        stale_appointments = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM appointments
                   WHERE status='scheduled'
                     AND datetime(scheduled_at)<
                         datetime('now','+3 hours','+30 minutes')"""
            ).fetchone()["count"]
            or 0
        )
        missing_source = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM patient_links patient
                   WHERE patient.is_active=1
                     AND NOT EXISTS (
                       SELECT 1 FROM growth_leads lead
                       WHERE lead.patient_link_id=patient.id
                         AND lead.status='CONVERTED'
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM growth_patient_acquisition acquisition
                       WHERE acquisition.patient_link_id=patient.id
                     )"""
            ).fetchone()["count"]
            or 0
        )
        result = {
            "missing_phone": int(row["missing_phone"] or 0),
            "missing_national_id": int(row["missing_national_id"] or 0),
            "missing_birthdate": int(row["missing_birthdate"] or 0),
            "legacy_medications": legacy_medications,
            "legacy_labs": legacy_labs,
            "stale_appointments": stale_appointments,
            "missing_source": missing_source,
        }
        result["total"] = sum(result.values())
        return result

    @staticmethod
    def _priority_actions(context: dict) -> list[dict]:
        actions = []
        if context["leads"]["due"]:
            actions.append(
                {
                    "key": "due_leads",
                    "priority": 10,
                    "tone": "danger",
                    "title": "پیگیری سرنخ‌های سررسیدشده",
                    "detail": f"{context['leads']['due']} سرنخ اکنون منتظر اقدام است.",
                    "endpoint": "leads.index",
                    "query": {"status": "NEW"},
                    "label": "شروع پیگیری",
                }
            )
        if context["work"]["due"]:
            actions.append(
                {
                    "key": "due_work",
                    "priority": 20,
                    "tone": "warn",
                    "title": "کارهای سررسیدشده",
                    "detail": f"{context['work']['due']} کار بیمار باید امروز رسیدگی شود.",
                    "endpoint": "unified_followups.index",
                    "query": {"view": "mine"},
                    "label": "بازکردن مرکز کارها",
                }
            )
        recovery = context["automation"]
        recovery_total = int(recovery["no_show"] + recovery["cancelled"] + recovery["inactive"])
        if recovery_total:
            actions.append(
                {
                    "key": "recovery",
                    "priority": 30,
                    "tone": "info",
                    "title": "فرصت‌های بازگشت بیمار",
                    "detail": f"{recovery_total} No-show، لغو یا بیمار غیرفعال قابل‌بازیابی است.",
                    "endpoint": "growth.automation",
                    "query": {},
                    "label": "ساخت کارهای بازیابی",
                }
            )
        finance_total = int(
            context["closed_loop"]["missing_financial_observations"]
            + context["closed_loop"]["incomplete_collection"]
        )
        if finance_total:
            actions.append(
                {
                    "key": "finance_exceptions",
                    "priority": 40,
                    "tone": "warn",
                    "title": "استثناهای درآمد و وصول",
                    "detail": f"{finance_total} فاکتور منتسب نیازمند مشاهده یا وصول است.",
                    "endpoint": "growth.automation",
                    "query": {},
                    "label": "تطبیق نتیجه و وصول",
                }
            )
        if context["waitlist"]["open_slots"]:
            actions.append(
                {
                    "key": "empty_slots",
                    "priority": 50,
                    "tone": "info",
                    "title": "ظرفیت خالی قابل‌پرکردن",
                    "detail": f"{context['waitlist']['open_slots']} Slot لغوشده با صف انتظار قابل تطبیق است.",
                    "endpoint": "growth_waitlist.index",
                    "query": {},
                    "label": "پرکردن ظرفیت",
                }
            )
        if context["messaging"]["total_candidates"]:
            actions.append(
                {
                    "key": "messages",
                    "priority": 60,
                    "tone": "info",
                    "title": "پیام‌های معتبر آماده صف",
                    "detail": f"{context['messaging']['total_candidates']} پیام رشد یا یادآوری هنوز معتبر است.",
                    "endpoint": "growth.automation",
                    "query": {},
                    "label": "به‌روزرسانی صف پیام",
                }
            )
        return sorted(actions, key=lambda item: item["priority"])

    def build(self) -> dict:
        leads = self._lead_summary()
        work = self._work_summary()
        appointments = self._appointment_summary()
        automation = GrowthAutomationService(self.db).preview(inactive_days=180)
        closed_loop = GrowthClosedLoopService(self.db).preview()
        messaging = GrowthMessagingPlaybookService(self.db).preview()
        waitlist_service = GrowthWaitlistService(self.db)
        waitlist = waitlist_service.dashboard()
        revenue = GrowthRevenueCockpitService().build()
        quality = self._quality_summary()
        context = {
            "leads": leads,
            "work": work,
            "appointments": appointments,
            "automation": automation,
            "closed_loop": closed_loop,
            "messaging": messaging,
            "waitlist": {
                "counts": waitlist["counts"],
                "open_slots": waitlist["open_slots"],
            },
            "revenue": revenue,
            "quality": quality,
        }
        context["priority_actions"] = self._priority_actions(context)
        return context


__all__ = ["OperationsHomeService"]
