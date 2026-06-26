"""
Worklist domain router (cleanup step 7 — god-file split).

Migrated verbatim out of the ``config/api.py`` god-file (ACT slice — care-loop).
Holds the follow-up worklist read + the mark-done write (both JWT, tenant-scoped):

  GET  /worklist                 → paginated follow-up tasks
  POST /worklist/{task_id}/done  → mark a task done

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", worklist_router)`` and the routes carry their full short
paths, so ``/api/v1`` (urls.py) + the path == the same full paths as before.

Manager-only revenue gate (preserved verbatim): ``?include_revenue=true`` only
populates the per-task ``revenue`` column when the JWT user role is 'manager';
for staff it is always null. This is a hard gate — revenue is manager-only.

This module imports FROM ``config.api_base`` (shared ``_jwt_auth``); nothing in
``api_base`` imports a router, so the package stays free of cycles.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime, date

from ninja import Router, Schema, Query
from django.utils import timezone

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response
from config.pagination import paginate

from accounting_port.port import get_patients_by_ids, PatientDTO
from clinical.models import FollowupTask, PatientLink
from clinical.audit import log_activity

router = Router()


# ---------------------------------------------------------------------------
# Worklist schemas
# ---------------------------------------------------------------------------

class WorklistItemDTO(Schema):
    """One follow-up task enriched with patient demographics."""
    id: int
    patient_uuid: Optional[str] = None
    patient_full_name: Optional[str] = None
    kind: Optional[str] = None        # maps from reason field
    reason: Optional[str] = None
    due_date: Optional[date] = None
    status: str
    fulfillment: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    # Manager-only revenue column — null for staff even if include_revenue=true
    revenue: Optional[int] = None


class WorklistResponseDTO(Schema):
    items: list[WorklistItemDTO]
    total: int
    limit: int
    offset: int


class FollowupTaskDTO(Schema):
    """Full task DTO returned after a state change."""
    id: int
    patient_link_id: int
    tenant_id: int
    reason: Optional[str] = None
    detail: Optional[str] = None
    due_date: Optional[date] = None
    status: str
    fulfillment: Optional[str] = None
    source_rule: Optional[str] = None
    source_event: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None


# ── GET /worklist ─────────────────────────────────────────────────────────────

@router.get(
    "/worklist",
    response=WorklistResponseDTO,
    auth=_jwt_auth,
    tags=["worklist"],
)
def list_worklist(
    request,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_revenue: bool = Query(default=False),
):
    """
    Paginated follow-up worklist for the authenticated tenant.

    Default filter: status='open' and due_date <= today (due tasks).
    Pass ?status=done or ?status=dismissed to see other states.
    Ordered by due_date ASC (oldest-due first), then id.

    N+1-avoidance: page tasks first, then batch-fetch demographics for the page
    via AccountingReadPort.get_patients_by_ids().

    include_revenue=true: when the authenticated user is a MANAGER, each task
    gains a `revenue` field (Toman int from accounting, read-only, batched).
    For non-managers, `revenue` is always null even if include_revenue=true.
    This is a hard gate — revenue is manager-only.

    Returns 401 without JWT. Tasks from other tenants are never shown.
    """
    tenant_id = request.tenant_id
    today = timezone.now().date()

    # Manager gate: revenue column only for managers, never for staff
    user_role = getattr(request.auth, "role", "staff")
    effective_include_revenue = include_revenue and (user_role == "manager")

    # Build queryset — always tenant-scoped
    qs = FollowupTask.objects.filter(tenant_id=tenant_id)

    if status is not None:
        qs = qs.filter(status=status)
    else:
        # Default: open and due (due_date <= today OR due_date is NULL)
        from django.db.models import Q
        qs = qs.filter(
            status=FollowupTask.STATUS_OPEN,
        ).filter(
            Q(due_date__lte=today) | Q(due_date__isnull=True)
        )

    total = qs.count()
    page_tasks = list(qs.order_by("due_date", "id")[offset: offset + limit])

    # Batch-fetch demographics — collect unique patient_link_ids on this page,
    # look up patient_ids, then batch-fetch from accounting.
    link_ids_on_page = [t.patient_link_id for t in page_tasks]
    # Fetch the PatientLink rows to get patient_id → uuid mapping
    links_map: dict[int, PatientLink] = {}
    if link_ids_on_page:
        for pl in PatientLink.objects.filter(id__in=link_ids_on_page):
            links_map[pl.id] = pl

    patient_ids_on_page = list({pl.patient_id for pl in links_map.values()})
    demos_by_pid: dict[int, PatientDTO] = {
        d.id: d for d in get_patients_by_ids(patient_ids_on_page)
    }

    # Revenue batch (manager-only) — one call for the whole page
    from accounting_port.port import get_revenue_by_patient_ids as _get_rev
    rev_by_pid: dict[int, int] = {}
    if effective_include_revenue and patient_ids_on_page:
        rev_by_pid = _get_rev(patient_ids_on_page)

    items: list[WorklistItemDTO] = []
    for task in page_tasks:
        pl = links_map.get(task.patient_link_id)
        demo = demos_by_pid.get(pl.patient_id) if pl else None
        revenue_val: Optional[int] = None
        if effective_include_revenue and pl:
            revenue_val = rev_by_pid.get(pl.patient_id)

        items.append(
            WorklistItemDTO(
                id=task.id,
                patient_uuid=str(demo.uuid) if demo else None,
                patient_full_name=demo.full_name if demo else None,
                kind=task.reason,          # reason is the "kind" of follow-up
                reason=task.reason,
                due_date=task.due_date,
                status=task.status,
                fulfillment=task.fulfillment,
                created_at=task.created_at,
                resolved_at=task.resolved_at,
                revenue=revenue_val,
            )
        )

    return WorklistResponseDTO(**paginate(total, items, limit, offset))


# ── POST /worklist/{task_id}/done ─────────────────────────────────────────────

@router.post(
    "/worklist/{task_id}/done",
    response={200: FollowupTaskDTO, 404: ErrorSchema, 409: ErrorSchema},
    auth=_jwt_auth,
    tags=["worklist"],
)
def mark_task_done(request, task_id: int):
    """
    Mark a follow-up task as done.

    Sets status='done' and resolved_at=now().
    Returns 404 if the task does not exist for this tenant.
    Returns 409 if the task is already done or dismissed.
    Clinical WRITE — uses 'default' connection (platform_app role).
    """
    tenant_id = request.tenant_id

    try:
        task = FollowupTask.objects.get(id=task_id, tenant_id=tenant_id)
    except FollowupTask.DoesNotExist:
        return 404, error_response(
            f"FollowupTask id={task_id} not found for this tenant.", "not_found"
        )

    if task.status != FollowupTask.STATUS_OPEN:
        return 409, error_response(
            f"Task id={task_id} is already '{task.status}'; only open tasks can be marked done.",
            "conflict",
        )

    task.status = FollowupTask.STATUS_DONE
    task.resolved_at = timezone.now()
    task.save(update_fields=["status", "resolved_at"])

    # Audit: state-changing write — append-only, best-effort
    actor = getattr(request.auth, "username", None) or "unknown"
    log_activity(
        tenant_id=tenant_id,
        user_id=getattr(request.auth, "pk", None),
        username=actor,
        action_type="followup_done",
        action_category="clinical",
        target_table="followup_tasks",
        target_id=task.id,
        patient_link_id=task.patient_link_id,
    )

    return 200, FollowupTaskDTO(
        id=task.id,
        patient_link_id=task.patient_link_id,
        tenant_id=task.tenant_id,
        reason=task.reason,
        detail=task.detail,
        due_date=task.due_date,
        status=task.status,
        fulfillment=task.fulfillment,
        source_rule=task.source_rule,
        source_event=task.source_event,
        created_at=task.created_at,
        resolved_at=task.resolved_at,
    )
