"""Closed-loop growth reconciliation using existing authoritative evidence.

This is a small set of explicit rules, not a generic workflow engine:

- recovery/recall work closes when a replacement appointment or attendance exists;
- eligible specialist invoices without an observation create a finance exception;
- unpaid/partial specialist observations create a collection task;
- finance exceptions and collection tasks close when later evidence satisfies them.
"""
from __future__ import annotations

from datetime import datetime
import sqlite3

from src.adapters.sqlite.core import get_db
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.specialist_financial_funnel_repo import (
    SpecialistFinancialFunnelRepository,
)
from src.common.utils import iran_now


_RECOVERY_REASONS = {
    "no_show_recovery",
    "cancellation_recovery",
    "inactive_patient_recall",
}
_COLLECTION_OPEN_STATES = {"UNPAID", "PARTIALLY_COLLECTED"}
_COLLECTION_CLOSED_STATES = {"COLLECTED", "CLOSED_NO_BILLABLE_ITEMS"}


class GrowthClosedLoopService:
    def __init__(self, db: sqlite3.Connection | None = None):
        self.db = db or get_db()
        self.followups = FollowupRepository(self.db)
        self.finance = SpecialistFinancialFunnelRepository(self.db)

    @staticmethod
    def _now_text() -> str:
        current = iran_now()
        if current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        return current.replace(microsecond=0).isoformat(
            sep=" ", timespec="seconds"
        )

    def _open_task(self, source_rule: str) -> dict | None:
        row = self.db.execute(
            """SELECT * FROM followup_tasks
               WHERE source_rule=? AND status='open'
                 AND COALESCE(source_engine,'') NOT IN (
                     'clinical_v2','encounter_plan'
                 )
               ORDER BY id DESC LIMIT 1""",
            (str(source_rule),),
        ).fetchone()
        return dict(row) if row else None

    def _create_task_once(
        self,
        *,
        patient_link_id: int,
        reason: str,
        detail: str,
        source_rule: str,
        source_event: str,
        appointment_id: int | None = None,
        assigned_to: str | None = None,
    ) -> int | None:
        if self._open_task(source_rule):
            return None
        return self.followups.create(
            int(patient_link_id),
            reason=reason,
            detail=detail,
            due_date=self._now_text(),
            assigned_to=assigned_to,
            source_rule=source_rule,
            source_event=source_event,
            appointment_id=appointment_id,
            fulfillment="remote",
        )

    def reconcile_recovery_tasks(self) -> dict:
        rows = self.db.execute(
            """SELECT task.*
               FROM followup_tasks task
               WHERE task.status='open'
                 AND task.reason IN (
                   'no_show_recovery',
                   'cancellation_recovery',
                   'inactive_patient_recall'
                 )
                 AND COALESCE(task.source_engine,'') NOT IN (
                   'clinical_v2','encounter_plan'
                 )
               ORDER BY task.id"""
        ).fetchall()
        closed = []
        linked = []
        waiting = []
        for raw in rows:
            task = dict(raw)
            appointment = self.db.execute(
                """SELECT * FROM appointments
                   WHERE patient_link_id=?
                     AND status IN ('scheduled','done')
                     AND (
                       datetime(scheduled_at)>=datetime(COALESCE(?,created_at))
                       OR status='scheduled'
                     )
                   ORDER BY CASE status WHEN 'done' THEN 0 ELSE 1 END,
                            scheduled_at DESC,id DESC LIMIT 1""",
                (
                    int(task["patient_link_id"]),
                    task.get("created_at"),
                ),
            ).fetchone()
            if not appointment:
                waiting.append(int(task["id"]))
                continue
            appointment = dict(appointment)
            if task.get("appointment_id") != appointment["id"]:
                self.followups.set_appointment(
                    int(task["id"]), int(appointment["id"])
                )
                linked.append(int(task["id"]))
            evidence = (
                "مراجعه انجام شد"
                if appointment["status"] == "done"
                else "نوبت جایگزین ثبت شد"
            )
            self.followups.resolve(
                int(task["id"]),
                "done",
                call_log=(
                    f"{evidence}; appointment={appointment['id']} "
                    f"scheduled_at={appointment['scheduled_at']}"
                ),
            )
            closed.append(int(task["id"]))
        return {
            "eligible": len(rows),
            "closed": len(closed),
            "linked": len(linked),
            "waiting": len(waiting),
            "closed_task_ids": closed,
            "waiting_task_ids": waiting,
        }

    def reconcile_finance_observations(
        self,
        *,
        assigned_to: str | None = None,
    ) -> dict:
        eligible = self.finance.eligible_invoice_contexts()
        observations = {
            int(row["accounting_invoice_id"]): row
            for row in self.finance.latest_observations()
        }
        created = []
        closed = []
        waiting = []
        for context in eligible:
            invoice_id = int(context["accounting_invoice_id"])
            source_rule = f"growth:finance-observation:{invoice_id}"
            observation = observations.get(invoice_id)
            task = self._open_task(source_rule)
            if observation:
                if task:
                    self.followups.resolve(
                        int(task["id"]),
                        "done",
                        call_log=(
                            "مشاهده مالی ثبت شد; "
                            f"invoice={invoice_id} "
                            f"state={observation['collection_state']}"
                        ),
                    )
                    closed.append(int(task["id"]))
                continue
            task_id = self._create_task_once(
                patient_link_id=int(context["patient_link_id"]),
                reason="financial_observation_missing",
                detail=(
                    f"فاکتور تخصصی {invoice_id} به Encounter متصل است اما "
                    "مشاهده مالی به‌روز ندارد."
                ),
                source_rule=source_rule,
                source_event="specialist_financial_observation_missing",
                appointment_id=(
                    int(context["appointment_id"])
                    if context.get("appointment_id") is not None
                    else None
                ),
                assigned_to=assigned_to,
            )
            if task_id is None:
                waiting.append(invoice_id)
            else:
                created.append(task_id)
        return {
            "eligible_invoices": len(eligible),
            "created": len(created),
            "closed": len(closed),
            "waiting": len(waiting),
            "created_task_ids": created,
            "closed_task_ids": closed,
        }

    def reconcile_collection_tasks(
        self,
        *,
        assigned_to: str | None = None,
    ) -> dict:
        observations = self.finance.latest_observations()
        created = []
        closed = []
        waiting = []
        for observation in observations:
            if str(observation.get("invoice_status") or "") != "closed":
                continue
            invoice_id = int(observation["accounting_invoice_id"])
            state = str(observation.get("collection_state") or "")
            source_rule = f"growth:collection:{invoice_id}"
            task = self._open_task(source_rule)
            if state in _COLLECTION_CLOSED_STATES:
                if task:
                    self.followups.resolve(
                        int(task["id"]),
                        "done",
                        call_log=(
                            f"وصول نهایی مشاهده شد; invoice={invoice_id} "
                            f"state={state} collected="
                            f"{int(observation.get('collected_amount') or 0)}"
                        ),
                    )
                    closed.append(int(task["id"]))
                continue
            if state not in _COLLECTION_OPEN_STATES:
                continue
            billed = int(observation.get("billed_amount") or 0)
            collected = int(observation.get("collected_amount") or 0)
            outstanding = max(billed - collected, 0)
            if task:
                waiting.append(int(task["id"]))
                continue
            task_id = self._create_task_once(
                patient_link_id=int(observation["patient_link_id"]),
                reason="payment_collection",
                detail=(
                    f"پیگیری وصول فاکتور تخصصی {invoice_id}; "
                    f"صورتحساب={billed} وصول={collected} مانده={outstanding}"
                ),
                source_rule=source_rule,
                source_event="specialist_collection_incomplete",
                appointment_id=(
                    int(observation["appointment_id"])
                    if observation.get("appointment_id") is not None
                    else None
                ),
                assigned_to=assigned_to,
            )
            if task_id is not None:
                created.append(task_id)
        return {
            "observations": len(observations),
            "created": len(created),
            "closed": len(closed),
            "waiting": len(waiting),
            "created_task_ids": created,
            "closed_task_ids": closed,
        }

    def preview(self) -> dict:
        recovery_open = int(
            self.db.execute(
                """SELECT COUNT(*) AS count FROM followup_tasks
                   WHERE status='open' AND reason IN (
                     'no_show_recovery','cancellation_recovery',
                     'inactive_patient_recall'
                   )"""
            ).fetchone()["count"]
            or 0
        )
        eligible = self.finance.eligible_invoice_contexts()
        observed_ids = {
            int(row["accounting_invoice_id"])
            for row in self.finance.latest_observations()
        }
        missing_observations = sum(
            1
            for context in eligible
            if int(context["accounting_invoice_id"]) not in observed_ids
        )
        incomplete_collection = sum(
            1
            for row in self.finance.latest_observations()
            if str(row.get("invoice_status") or "") == "closed"
            and str(row.get("collection_state") or "")
            in _COLLECTION_OPEN_STATES
        )
        return {
            "recovery_open": recovery_open,
            "missing_financial_observations": missing_observations,
            "incomplete_collection": incomplete_collection,
        }

    def run(
        self,
        *,
        assigned_to: str | None = None,
    ) -> dict:
        return {
            "recovery": self.reconcile_recovery_tasks(),
            "finance": self.reconcile_finance_observations(
                assigned_to=assigned_to
            ),
            "collection": self.reconcile_collection_tasks(
                assigned_to=assigned_to
            ),
        }


__all__ = ["GrowthClosedLoopService"]
