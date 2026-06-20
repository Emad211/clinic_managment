"""Physician visit-queue service (phase3_doctor_queue_plan.md).

Builds the live queue from OPEN visit invoices (read-only bridge) merged with the local
`doctor_visit_log` state, and records start / end-of-visit. NEVER writes the accounting DB.
"""
from src.adapters import accounting_bridge
from src.adapters.sqlite.doctor_queue_repo import DoctorQueueRepository
from src.adapters.sqlite.patients_repo import PatientRepository
from src.common.utils import today_str


class DoctorQueueService:
    def __init__(self):
        self.repo = DoctorQueueRepository()
        self.patients = PatientRepository()

    def queue(self, work_date: str | None = None) -> dict:
        """Return {'waiting', 'done', 'work_date'} for the physician panel — today's OPEN
        visit invoices, each tagged with the local در‌نوبت/انجام‌شده state and mapped to a
        patient_links row when the patient is enrolled."""
        wd = work_date or today_str()
        opens = accounting_bridge.fetch_open_visit_invoices(work_date=wd)
        log = self.repo.log_map(wd)
        waiting, done = [], []
        for inv in opens:
            entry = log.get(inv["invoice_id"]) or {}
            status = entry.get("status", "waiting")
            nid = (inv.get("national_id") or "").strip() or None
            link = self.patients.get_by_national_id(nid) if nid else None
            row = {
                "invoice_id": inv["invoice_id"], "national_id": nid,
                "full_name": inv.get("full_name"), "phone_number": inv.get("phone_number"),
                "opened_at": inv.get("opened_at"), "work_date": inv.get("work_date") or wd,
                "status": status, "patient_link_id": link["id"] if link else None,
                "enrolled": bool(link), "done_by": entry.get("done_by"),
            }
            (done if status == "done" else waiting).append(row)
        return {"waiting": waiting, "done": done, "work_date": wd}

    def start(self, snapshot: dict) -> None:
        self.repo.start(**snapshot)

    def end_visit(self, snapshot: dict, done_by: str, notes: str | None = None) -> None:
        self.repo.mark_done(done_by=done_by, notes=notes, **snapshot)
