"""
Doctor visit queue domain router (Step 14) — read-only accounting + local state.

Migrated out of the ``config/api.py`` god-file in cleanup step 4.

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", doctor_queue_router)`` and the routes below carry their
full sub-paths, so ``/api/v1`` (urls.py) + ``""`` (prefix) + ``"/doctor-queue…"``
== the same paths as before:

  GET  /api/v1/doctor-queue?work_date=YYYY-MM-DD       → {waiting, done, work_date}
  POST /api/v1/doctor-queue/{accounting_invoice_id}/start  → DoctorVisitLogOut
  POST /api/v1/doctor-queue/{accounting_invoice_id}/done   → DoctorVisitLogOut

NEVER writes accounting. Queue state lives ONLY in clinical.doctor_visit_log.
Open invoices are fetched via accounting_port.fetch_open_visit_invoices
(SELECT-only at Postgres DB level — enforced by GRANTs in slice0/slice3).
"""
from typing import Optional
from datetime import datetime

from ninja import Router, Schema, Query

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response
from clinical.doctor_queue_service import (
    get_queue as _get_queue,
    start_visit as _start_visit,
    end_visit as _end_visit,
    InvoiceNotOpen as _InvoiceNotOpen,
    VisitAlreadyDone as _VisitAlreadyDone,
)

router = Router()


# ---------------------------------------------------------------------------
# Doctor-queue schemas
# ---------------------------------------------------------------------------

class DoctorQueueEntryDTO(Schema):
    """One open invoice merged with its local queue state and enrollment info."""
    invoice_id: int
    patient_id: int
    patient_uuid: Optional[str] = None
    full_name: str
    phone_number: Optional[str] = None
    opened_at: Optional[str] = None
    work_date: Optional[str] = None
    status: str                          # waiting | in_progress | done
    patient_link_id: Optional[int] = None
    enrolled: bool
    done_by: Optional[str] = None
    started_at: Optional[str] = None
    done_at: Optional[str] = None


class DoctorQueueResponse(Schema):
    """Full queue for one work_date: waiting (waiting+in_progress) + done lists."""
    waiting: list[DoctorQueueEntryDTO]
    done: list[DoctorQueueEntryDTO]
    work_date: str


class DoctorVisitLogOut(Schema):
    """Local state row returned after a start/done transition."""
    id: int
    tenant_id: int
    accounting_invoice_id: int
    patient_link_id: Optional[int] = None
    patient_uuid: Optional[str] = None
    full_name: str
    work_date: str
    status: str
    started_at: Optional[datetime] = None
    done_at: Optional[datetime] = None
    physician_notes: Optional[str] = None
    done_by: Optional[str] = None
    created_at: Optional[datetime] = None


class DoneVisitIn(Schema):
    """Optional body for POST /doctor-queue/{id}/done."""
    notes: Optional[str] = None


def _log_row_to_out(row) -> DoctorVisitLogOut:
    """Convert a DoctorVisitLog ORM instance to the output schema."""
    # work_date may be a date object (from DB) or a str (passed via get_or_create defaults)
    wd = row.work_date
    if wd is None:
        work_date_str = ""
    elif hasattr(wd, "isoformat"):
        work_date_str = wd.isoformat()
    else:
        work_date_str = str(wd)

    return DoctorVisitLogOut(
        id=row.id,
        tenant_id=row.tenant_id,
        accounting_invoice_id=row.accounting_invoice_id,
        patient_link_id=row.patient_link_id,
        patient_uuid=str(row.patient_uuid) if row.patient_uuid else None,
        full_name=row.full_name,
        work_date=work_date_str,
        status=row.status,
        started_at=row.started_at,
        done_at=row.done_at,
        physician_notes=row.physician_notes,
        done_by=row.done_by,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# GET /doctor-queue — returns today's queue (or requested work_date)
# ---------------------------------------------------------------------------

@router.get(
    "/doctor-queue",
    response={200: DoctorQueueResponse, 400: ErrorSchema},
    auth=_jwt_auth,
    tags=["doctor_queue"],
)
def doctor_queue(
    request,
    work_date: Optional[str] = Query(default=None),
):
    """
    Return the physician visit queue for a given work_date (default: today).

    Merges OPEN visit-invoices from accounting (read-only) with local
    clinical.doctor_visit_log state and PatientLink enrollment data.

    No accounting writes ever occur. Requires JWT (tenant-scoped).

    work_date format: YYYY-MM-DD. Defaults to today (Tehran / server TZ).
    Response: {waiting: [...], done: [...], work_date: 'YYYY-MM-DD'}.
    Each entry includes: invoice_id, patient_id, patient_uuid, full_name,
    phone_number, opened_at, work_date, status, patient_link_id, enrolled,
    done_by, started_at, done_at.
    """
    tenant_id = request.tenant_id

    # Validate work_date format if provided
    if work_date:
        try:
            from datetime import date as _date
            _date.fromisoformat(work_date)
        except ValueError:
            return 400, error_response(
                f"Invalid work_date format '{work_date}'. Expected YYYY-MM-DD.",
                "validation_error",
            )

    queue = _get_queue(work_date=work_date, tenant_id=tenant_id)

    return 200, DoctorQueueResponse(
        waiting=[DoctorQueueEntryDTO(**e) for e in queue["waiting"]],
        done=[DoctorQueueEntryDTO(**e) for e in queue["done"]],
        work_date=queue["work_date"],
    )


# ---------------------------------------------------------------------------
# POST /doctor-queue/{accounting_invoice_id}/start — waiting → in_progress
# ---------------------------------------------------------------------------

@router.post(
    "/doctor-queue/{accounting_invoice_id}/start",
    response={
        200: DoctorVisitLogOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["doctor_queue"],
)
def start_visit_endpoint(request, accounting_invoice_id: int):
    """
    Start a queued visit: transition status waiting → in_progress.

    Creates a doctor_visit_log row (or updates an existing 'waiting' row).
    Returns 409 if the visit is already in_progress or done.

    Fetches the snapshot (full_name, work_date, patient_uuid, patient_link_id)
    from the accounting port (read-only) and existing PatientLink — these values
    are persisted as an immutable snapshot in doctor_visit_log.

    NEVER writes accounting.  Requires JWT (tenant-scoped).
    """
    from accounting_port.port import fetch_open_visit_invoices as _fetch
    from clinical.models import PatientLink as _PL

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    actor_id = getattr(request.auth, "pk", None)

    # Fetch the invoice to build the snapshot
    # We need the full_name, work_date, patient_uuid from the open invoice.
    # fetch_open_visit_invoices is tenant-scoped; we search today's + all open.
    # The most reliable path: fetch without date filter, find this invoice_id.
    invoices = _fetch(work_date=None, tenant_id=tenant_id, limit=500)
    inv = next((i for i in invoices if i.invoice_id == accounting_invoice_id), None)

    if inv is None:
        return 404, error_response(
            f"Open visit invoice {accounting_invoice_id} not found for this tenant. "
            "It may be closed, belong to another tenant, or have no visit item.",
            "not_found",
        )

    # Resolve PatientLink for the snapshot
    patient_link_id: Optional[int] = None
    try:
        pl = _PL.objects.get(tenant_id=tenant_id, patient_id=inv.patient_id, is_active=True)
        patient_link_id = pl.id
    except _PL.DoesNotExist:
        pass

    snapshot = {
        "full_name": inv.full_name,
        "work_date": inv.work_date,
        "patient_uuid": inv.patient_uuid,
        "patient_link_id": patient_link_id,
    }

    try:
        row = _start_visit(
            accounting_invoice_id=accounting_invoice_id,
            tenant_id=tenant_id,
            snapshot=snapshot,
            actor_user_id=actor_id,
            actor_username=actor,
        )
    except _InvoiceNotOpen as exc:
        return 409, error_response(str(exc), "conflict")

    return 200, _log_row_to_out(row)


# ---------------------------------------------------------------------------
# POST /doctor-queue/{accounting_invoice_id}/done — → done
# ---------------------------------------------------------------------------

@router.post(
    "/doctor-queue/{accounting_invoice_id}/done",
    response={
        200: DoctorVisitLogOut,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["doctor_queue"],
)
def done_visit_endpoint(
    request,
    accounting_invoice_id: int,
    body: DoneVisitIn,
):
    """
    Mark a visit as done: transition status in_progress (or waiting) → done.

    Sets done_at=now(), done_by (JWT username), physician_notes (optional body).
    Returns 409 if the visit is already done.

    Creates a done row if no log row exists yet (edge case: done without start).

    NEVER writes accounting.  Requires JWT (tenant-scoped).
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    actor_id = getattr(request.auth, "pk", None)

    try:
        row = _end_visit(
            accounting_invoice_id=accounting_invoice_id,
            tenant_id=tenant_id,
            done_by=actor,
            notes=body.notes,
            actor_user_id=actor_id,
            actor_username=actor,
        )
    except _VisitAlreadyDone as exc:
        return 409, error_response(str(exc), "conflict")

    return 200, _log_row_to_out(row)
