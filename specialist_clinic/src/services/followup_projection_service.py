"""One canonical projection for administrative and clinical follow-up tasks."""
from __future__ import annotations

from datetime import date, datetime
import secrets

from src.adapters.sqlite.followup_operations_repo import (
    FollowupOperationsRepository,
)
from src.adapters.sqlite.followups_repo import FollowupRepository
from src.adapters.sqlite.clinical_task_contract_repo import (
    ClinicalTaskContractRepository,
)


OPEN_STATUSES = frozenset(
    {"OPEN", "ASSIGNED", "SCHEDULED", "IN_PROGRESS", "DEFERRED", "open"}
)
TERMINAL_SUCCESS = frozenset({"COMPLETED", "done"})


class FollowupProjectionService:
    def __init__(
        self,
        *,
        tasks: FollowupRepository | None = None,
        contacts: FollowupOperationsRepository | None = None,
    ):
        self.tasks = tasks or FollowupRepository()
        self.contacts = contacts or FollowupOperationsRepository()

    @staticmethod
    def _normalize(row: dict) -> dict:
        item = dict(row)
        current = item.get("current_status") or item.get("status") or "open"
        item["current_status"] = current
        item["is_open"] = current in OPEN_STATUSES
        item["is_completed"] = current in TERMINAL_SUCCESS
        item["current_due_at"] = (
            item.get("current_due_at") or item.get("due_date")
        )
        item["current_assigned_to"] = (
            item.get("current_assigned_to") or item.get("assigned_to")
        )
        item["current_appointment_id"] = (
            item.get("current_appointment_id") or item.get("appointment_id")
        )
        item["contact_form_token"] = secrets.token_urlsafe(18)
        return item

    def _augment(self, rows: list[dict]) -> list[dict]:
        normalized = [self._normalize(row) for row in rows]
        summaries = self.contacts.summaries(
            [int(row["id"]) for row in normalized]
        )
        contracts = ClinicalTaskContractRepository()
        for row in normalized:
            row.update(
                summaries.get(
                    int(row["id"]),
                    {
                        "contact_count": 0,
                        "last_contact_id": None,
                        "last_contact_at": None,
                        "last_contact_channel": None,
                        "last_contact_outcome": None,
                        "last_contact_note": None,
                        "next_contact_at": None,
                    },
                )
            )
            row["task_contract"] = (
                contracts.get(int(row["id"]))
                if row.get("source_engine") == "clinical_v2"
                else None
            )
        return normalized

    def open_tasks(
        self,
        *,
        reason: str | None = None,
        query: str | None = None,
    ) -> list[dict]:
        rows = (
            self.tasks.search_open(query)
            if query
            else self.tasks.list_open(reason)
        )
        return self._augment(rows)

    def patient_tasks(
        self,
        patient_link_id: int,
        *,
        include_terminal: bool = True,
    ) -> list[dict]:
        rows = self.tasks.list_for_patient(int(patient_link_id))
        if not include_terminal:
            rows = [row for row in rows if self._normalize(row)["is_open"]]
        return self._augment(rows)

    def due_tasks(
        self,
        *,
        as_of: date | datetime | str,
        limit: int | None = None,
    ) -> list[dict]:
        if isinstance(as_of, datetime):
            current = as_of.date()
        elif isinstance(as_of, date):
            current = as_of
        else:
            current = datetime.fromisoformat(str(as_of)[:10]).date()
        result: list[dict] = []
        for task in self.open_tasks():
            raw_due = task.get("current_due_at")
            due = None
            if raw_due:
                try:
                    due = datetime.fromisoformat(str(raw_due)[:10]).date()
                except ValueError:
                    due = None
            if due is None or due <= current:
                result.append(task)
        result.sort(
            key=lambda task: (
                task.get("current_due_at") is None,
                task.get("current_due_at") or "9999-12-31",
                -int(task["id"]),
            )
        )
        return result[: int(limit)] if limit else result

    def open_counts_by_patient(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for task in self.open_tasks():
            patient_id = int(task["patient_link_id"])
            counts[patient_id] = counts.get(patient_id, 0) + 1
        return counts

    def summary(self, *, as_of: date | datetime | str) -> dict:
        open_rows = self.open_tasks()
        due_rows = self.due_tasks(as_of=as_of)
        callbacks = self.contacts.due_callbacks(as_of)
        patients = {int(row["patient_link_id"]) for row in open_rows}
        return {
            "open_tasks": len(open_rows),
            "open_patients": len(patients),
            "due_tasks": len(due_rows),
            "due_callbacks": len(callbacks),
            "tasks": open_rows,
            "due": due_rows,
            "callbacks": callbacks,
            "projection_policy": "UNIFIED_EVENT_AWARE_V1",
        }
