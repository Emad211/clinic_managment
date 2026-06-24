"""
Doctor visit-queue service — halqe platform Step 14.

Faithful adaptation of specialist_clinic/src/services/doctor_queue_service.py
for the Django/Postgres stack.

Key design decisions (matching the faithful source + ADR-0007):
  - READ ONLY from accounting: open invoices fetched via accounting_port.port
    (SELECT-only Postgres role — any accounting write raises at DB level).
  - WRITE ONLY to clinical.doctor_visit_log (local state tracker).
  - Patient mapping: accounting.patient_id → PatientLink (NOT national_id;
    ADR-0007 §2.1 keeps national_id out of clinical; uuid snapshot used).
  - UNIQUE(tenant_id, accounting_invoice_id): get_or_create + update pattern
    for idempotent upsert on start/done transitions.
  - Status transitions: waiting → in_progress → done.
  - Timezone: django.utils.timezone.now() (UTC-aware) for all timestamps.
  - Audit: every state-changing write is appended to clinical.activity_logs
    via clinical.audit.log_activity (best-effort, never 500s the caller).

Public API:
  get_queue(work_date, tenant_id) → {"waiting": [...], "done": [...], "work_date": str}
  start_visit(accounting_invoice_id, tenant_id, snapshot) → DoctorVisitLog
  end_visit(accounting_invoice_id, tenant_id, done_by, notes) → DoctorVisitLog

Exceptions:
  InvoiceNotOpen   — raised by start_visit when status is already past waiting
  VisitAlreadyDone — raised by end_visit when status is already done
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from django.utils import timezone

from accounting_port.port import fetch_open_visit_invoices, OpenVisitInvoiceDTO
from clinical.models import DoctorVisitLog, PatientLink
from clinical.audit import log_activity


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------

class InvoiceNotOpen(Exception):
    """Raised when start_visit is called on a visit already in_progress or done."""


class VisitAlreadyDone(Exception):
    """Raised when end_visit is called on a visit that is already done."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today_str() -> str:
    """Today's date as 'YYYY-MM-DD' in the server's local timezone (Tehran via Django TZ)."""
    return date.today().isoformat()


def _build_queue_entry(
    inv: OpenVisitInvoiceDTO,
    log_row: Optional[DoctorVisitLog],
    link: Optional[PatientLink],
    work_date: str,
) -> dict:
    """Merge one open invoice with its local queue state and enrollment."""
    status = log_row.status if log_row else "waiting"
    return {
        "invoice_id": inv.invoice_id,
        "patient_id": inv.patient_id,
        "patient_uuid": str(inv.patient_uuid),
        "full_name": inv.full_name,
        "phone_number": inv.phone_number,
        "opened_at": inv.opened_at,
        "work_date": inv.work_date or work_date,
        "status": status,
        "patient_link_id": link.id if link else None,
        "enrolled": bool(link),
        "done_by": log_row.done_by if log_row else None,
        "started_at": log_row.started_at.isoformat() if log_row and log_row.started_at else None,
        "done_at": log_row.done_at.isoformat() if log_row and log_row.done_at else None,
    }


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def get_queue(
    work_date: Optional[str] = None,
    tenant_id: int = 1,
) -> dict:
    """
    Build the physician visit queue for a given date.

    Steps:
      1. Fetch OPEN visit-invoices for work_date from accounting (read-only port).
      2. Load all doctor_visit_log rows for those invoice ids (one query, no N+1).
      3. Map each invoice's patient_id to a PatientLink (batch query, no N+1).
      4. Merge: each invoice → status from log (default 'waiting') + enrolled flag.
      5. Partition into waiting (waiting/in_progress) and done lists.

    Returns:
      {"waiting": [entry, ...], "done": [entry, ...], "work_date": "YYYY-MM-DD"}

    Never raises (accounting read is best-effort; empty lists returned on failure).
    """
    wd = work_date or _today_str()

    # 1. Fetch open visit invoices (read-only; [] on accounting-unavailable)
    open_invoices = fetch_open_visit_invoices(work_date=wd, tenant_id=tenant_id)

    if not open_invoices:
        return {"waiting": [], "done": [], "work_date": wd}

    invoice_ids = [inv.invoice_id for inv in open_invoices]

    # 2. Load log state for all these invoices in ONE query (no N+1)
    log_rows = DoctorVisitLog.objects.filter(
        tenant_id=tenant_id,
        accounting_invoice_id__in=invoice_ids,
    )
    log_map: dict[int, DoctorVisitLog] = {row.accounting_invoice_id: row for row in log_rows}

    # 3. Map accounting patient_id → PatientLink for enrolled patients (ONE query, no N+1)
    patient_ids = list({inv.patient_id for inv in open_invoices})
    links_by_patient_id: dict[int, PatientLink] = {}
    if patient_ids:
        for pl in PatientLink.objects.filter(
            tenant_id=tenant_id,
            patient_id__in=patient_ids,
            is_active=True,
        ):
            links_by_patient_id[pl.patient_id] = pl

    # 4. Merge and partition
    waiting: list[dict] = []
    done: list[dict] = []
    for inv in open_invoices:
        log_row = log_map.get(inv.invoice_id)
        link = links_by_patient_id.get(inv.patient_id)
        entry = _build_queue_entry(inv, log_row, link, wd)
        if entry["status"] == "done":
            done.append(entry)
        else:
            waiting.append(entry)

    return {"waiting": waiting, "done": done, "work_date": wd}


def start_visit(
    accounting_invoice_id: int,
    tenant_id: int,
    snapshot: dict,
    actor_user_id: Optional[int] = None,
    actor_username: Optional[str] = None,
) -> DoctorVisitLog:
    """
    Transition a queue entry from 'waiting' to 'in_progress'.

    snapshot must contain: full_name, work_date, patient_uuid (nullable),
    patient_link_id (nullable).

    Upsert semantics: if no log row exists, create one (status='in_progress').
    If row exists in 'waiting', promote to 'in_progress' + set started_at.
    Raises InvoiceNotOpen if row already in 'in_progress' or 'done'.

    Writes ONLY to clinical.doctor_visit_log.  NEVER touches accounting.
    """
    now = timezone.now()

    log_row, created = DoctorVisitLog.objects.get_or_create(
        tenant_id=tenant_id,
        accounting_invoice_id=accounting_invoice_id,
        defaults={
            "full_name": snapshot.get("full_name", ""),
            "work_date": snapshot.get("work_date", _today_str()),
            "patient_uuid": snapshot.get("patient_uuid"),
            "patient_link_id": snapshot.get("patient_link_id"),
            "status": DoctorVisitLog.STATUS_IN_PROGRESS,
            "started_at": now,
        },
    )

    if not created:
        if log_row.status != DoctorVisitLog.STATUS_WAITING:
            raise InvoiceNotOpen(
                f"Visit for invoice {accounting_invoice_id} is already "
                f"'{log_row.status}'; cannot start."
            )
        log_row.status = DoctorVisitLog.STATUS_IN_PROGRESS
        log_row.started_at = now
        log_row.save(update_fields=["status", "started_at"])

    # Audit — best-effort, never crashes the caller
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_user_id,
        username=actor_username,
        action_type="visit_started",
        action_category="doctor_queue",
        target_table="doctor_visit_log",
        target_id=log_row.id,
        patient_link_id=log_row.patient_link_id,
        description=f"accounting_invoice_id={accounting_invoice_id}",
    )

    return log_row


def end_visit(
    accounting_invoice_id: int,
    tenant_id: int,
    done_by: str,
    notes: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    actor_username: Optional[str] = None,
) -> DoctorVisitLog:
    """
    Transition a queue entry from 'in_progress' (or 'waiting') to 'done'.

    Get-or-create semantics: if no log row exists (visit ended without explicit
    start — edge case), create a done row directly.
    If row is already 'done', raises VisitAlreadyDone.
    Sets done_at=now(), done_by, physician_notes.

    Writes ONLY to clinical.doctor_visit_log.  NEVER touches accounting.
    """
    now = timezone.now()

    try:
        log_row = DoctorVisitLog.objects.get(
            tenant_id=tenant_id,
            accounting_invoice_id=accounting_invoice_id,
        )
        if log_row.status == DoctorVisitLog.STATUS_DONE:
            raise VisitAlreadyDone(
                f"Visit for invoice {accounting_invoice_id} is already done."
            )
        log_row.status = DoctorVisitLog.STATUS_DONE
        log_row.done_at = now
        log_row.done_by = done_by
        if notes is not None:
            log_row.physician_notes = notes
        log_row.save(update_fields=["status", "done_at", "done_by", "physician_notes"])
    except DoctorVisitLog.DoesNotExist:
        # Edge case: visit ended without an explicit start
        log_row = DoctorVisitLog.objects.create(
            tenant_id=tenant_id,
            accounting_invoice_id=accounting_invoice_id,
            full_name="",          # snapshot unknown at this point
            work_date=_today_str(),
            status=DoctorVisitLog.STATUS_DONE,
            done_at=now,
            done_by=done_by,
            physician_notes=notes,
        )

    # Audit — best-effort
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_user_id,
        username=actor_username,
        action_type="visit_done",
        action_category="doctor_queue",
        target_table="doctor_visit_log",
        target_id=log_row.id,
        patient_link_id=log_row.patient_link_id,
        description=f"accounting_invoice_id={accounting_invoice_id} done_by={done_by}",
    )

    return log_row
