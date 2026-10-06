"""Doctor queue (docs/06 §4-1, Q-1, Q-3, Q-4). Reads only the mirror."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..adapters.sqlite import mirror_repo
from ..domain.categories import LABELS_FA
from ..domain.identity import mask_national_id
from .shift import ShiftInfo

STATUS_PENDING, STATUS_DONE, STATUS_NO_FOLLOWUP = "pending", "done", "no_followup"
STATUS_LABELS = {STATUS_PENDING: "در انتظار", STATUS_DONE: "ثبت شد", STATUS_NO_FOLLOWUP: "بدون پیگیری"}


@dataclass(frozen=True)
class QueueRow:
    visit_id: int
    invoice_id: int
    patient_id: int
    name: str
    identity_ok: bool
    national_id_masked: str
    services: tuple[str, ...]
    time: str                  # HH:MM or ''
    status: str

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


def doctor_queue(conn: sqlite3.Connection, staff_id: int, shift: ShiftInfo) -> list[QueueRow]:
    rows = []
    for r in mirror_repo.doctor_queue(conn, staff_id, shift.work_date, shift.shift):
        cats = sorted(set((r["other_categories"] or "").split(",")) - {""})
        status = (STATUS_PENDING if r["decision"] is None
                  else STATUS_NO_FOLLOWUP if r["decision"] == "no_followup" else STATUS_DONE)
        name = " ".join(x for x in (r["name"], r["family_name"]) if x) or f"پرونده {r['acc_patient_id']}"
        at = r["item_at"] or ""
        rows.append(QueueRow(
            visit_id=r["visit_id"], invoice_id=r["acc_invoice_id"], patient_id=r["acc_patient_id"],
            name=name, identity_ok=bool(r["identity_ok"]), national_id_masked=mask_national_id(r["national_id"]),
            services=tuple(LABELS_FA[c] for c in cats if c in LABELS_FA),
            time=at[11:16] if len(at) >= 16 else "", status=status))
    return rows
