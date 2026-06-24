"""
django-ninja API — halqe platform v1.

Endpoints:
  POST /api/v1/auth/login                                         → JWT token
  GET  /api/v1/patients                                           → paginated enrolled patient list (requires JWT)
  GET  /api/v1/patients/{uuid}                                    → PatientDTO (requires JWT)
  GET  /api/v1/patients/{uuid}/vitals/latest                      → list[VitalReadingDTO] (requires JWT)
  GET  /api/v1/patients/{uuid}/record                             → full clinical record (requires JWT)

  ACT slice (care-loop):
  GET  /api/v1/worklist                                           → paginated follow-up tasks (requires JWT)
  POST /api/v1/worklist/{task_id}/done                            → mark task done (requires JWT)
  POST /api/v1/patients/{uuid}/suggestions/{rule_code}/action     → accept/dismiss suggestion (requires JWT)
"""
import uuid as uuid_module
from typing import Optional
from datetime import datetime, date

from ninja import NinjaAPI, Schema, Query
from django.http import Http404
from django.utils import timezone

from accounting_port.port import (
    get_patient_by_uuid,
    get_patients_by_ids,
    PatientDTO,
)
from clinical.models import (
    VitalReading,
    PatientLink,
    Condition,
    PatientCondition,
    PatientMedication,
    FollowupTask,
    SuggestionLog,
)
import clinical.rule_engine as _rule_engine
from clinical.audit import log_activity
from platform_core.auth_bearer import JWTBearer
from platform_core.auth_service import (
    login,
    InvalidCredentials,
    AccountLocked,
    AccountInactive,
)

# ---------------------------------------------------------------------------
# System sentinel for audit rows where no real tenant can be resolved.
#
# Used ONLY for failed-login audit rows when the supplied username does not
# exist in the DB (User.DoesNotExist or ambiguous multi-tenant collision).
# In those cases there is no user object to extract a real tenant_id from.
#
# We use 1 rather than 0 because clinical.activity_logs.tenant_id has a
# FOREIGN KEY REFERENCES platform.tenants(id), and the schema seeds tenant 1
# as the "پیش‌فرض" (default) tenant (slice0.sql).  Using 0 would violate the
# FK unless a system tenant row is inserted — a schema change deferred to a
# future step.  The constant name makes the intent explicit and distinguishable
# from any accidental hardcoded literal '1' elsewhere.
#
# When real tenant routing (subdomain / host-based) is implemented in a future
# step, these audit rows should carry the resolved tenant or be stored in a
# dedicated "platform audit" table without the FK constraint.
# ---------------------------------------------------------------------------
SYSTEM_TENANT_ID: int = 1

api = NinjaAPI(title="Halqe Platform API", version="0.1.0")

_jwt_auth = JWTBearer()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(Schema):
    username: str
    password: str


class TokenResponse(Schema):
    token: str


class VitalReadingDTO(Schema):
    id: int
    patient_link_id: int
    type: str
    value: float
    unit: Optional[str]
    measured_at: datetime
    source: Optional[str]
    notes: Optional[str]


# ---------------------------------------------------------------------------
# Patient-list schemas
# ---------------------------------------------------------------------------

class EnrolledPatientDTO(Schema):
    """One item in the paginated patient list."""
    link_id: int
    patient_id: int
    is_active: bool
    enrolled_at: datetime
    # Demographics from AccountingReadPort (None if not found in accounting)
    full_name: Optional[str] = None
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    patient_uuid: Optional[str] = None


class PatientListResponse(Schema):
    items: list[EnrolledPatientDTO]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Clinical record schemas
# ---------------------------------------------------------------------------

class ConditionDTO(Schema):
    id: int
    condition_id: int
    condition_name: Optional[str] = None
    condition_code: Optional[str] = None
    stage: Optional[str] = None
    onset_date: Optional[date] = None
    notes: Optional[str] = None
    is_active: bool
    diagnosed_at: datetime


class MedicationDTO(Schema):
    id: int
    drug_name: str
    dose: Optional[str] = None
    schedule: Optional[str] = None
    start_date: Optional[date] = None
    refill_due_date: Optional[date] = None
    drug_class: Optional[str] = None
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime


class ClinicalRecordDTO(Schema):
    """Full clinical record for one patient."""
    patient_link_id: int
    # Demographics via AccountingReadPort
    demographics: Optional[PatientDTO] = None
    # Active chronic conditions
    active_conditions: list[ConditionDTO]
    # Active medications only
    active_medications: list[MedicationDTO]
    # Recent vitals (last ~10, newest first)
    recent_vitals: list[VitalReadingDTO]


# ---------------------------------------------------------------------------
# Auth endpoint — POST /auth/login
# ---------------------------------------------------------------------------

@api.post("/auth/login", response={200: TokenResponse, 401: dict, 423: dict}, auth=None, tags=["auth"])
def auth_login(request, body: LoginRequest):
    """
    Verify credentials against platform.users (bcrypt).
    Returns a signed JWT (8h) on success.
    401 on wrong credentials or inactive account.
    423 on locked account.
    """
    try:
        token = login(body.username, body.password)
        # Resolve user_id from the token claims for the audit row.
        # We decode here rather than issuing a second DB query — the JWT was
        # just signed by auth_service.login so it is guaranteed valid.
        from platform_core.auth_service import decode_jwt
        claims = decode_jwt(token)
        log_activity(
            tenant_id=claims.get("tenant_id", SYSTEM_TENANT_ID),
            user_id=claims.get("user_id"),
            username=body.username,
            action_type="login",
            action_category="auth",
            description="successful login",
        )
        return 200, {"token": token}
    except AccountLocked as exc:
        # exc.tenant_id is set when the user WAS found (wrong password triggers
        # lockout after 5 attempts — user object was resolved before the lock).
        # Falls back to SYSTEM_TENANT_ID only if tenant is truly unknown.
        audit_tenant = exc.tenant_id if exc.tenant_id is not None else SYSTEM_TENANT_ID
        log_activity(
            tenant_id=audit_tenant,
            user_id=None,
            username=body.username,
            action_type="login_failed",
            action_category="auth",
            description="account locked",
        )
        return 423, {"detail": str(exc)}
    except (InvalidCredentials, AccountInactive) as exc:
        # exc.tenant_id is set when the user WAS found (wrong password case).
        # It is None when the username does not exist or is ambiguous (multi-tenant).
        audit_tenant = exc.tenant_id if exc.tenant_id is not None else SYSTEM_TENANT_ID
        log_activity(
            tenant_id=audit_tenant,
            user_id=None,
            username=body.username,
            action_type="login_failed",
            action_category="auth",
            description=str(exc),
        )
        return 401, {"detail": str(exc)}


# ---------------------------------------------------------------------------
# Patient list — GET /patients  (requires JWT, tenant-scoped)
# ---------------------------------------------------------------------------

@api.get(
    "/patients",
    response=PatientListResponse,
    auth=_jwt_auth,
    tags=["patients"],
)
def list_patients(
    request,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    Paginated list of ENROLLED patients for the authenticated tenant.

    Scoped to request.tenant_id (set by JWTBearer from token claims).
    N+1-avoidance: page patient_links first, then batch-fetch demographics
    for the page via AccountingReadPort.get_patients_by_ids().
    """
    tenant_id = request.tenant_id

    # 1. Total count for this tenant
    total = PatientLink.objects.filter(
        tenant_id=tenant_id,
    ).count()

    # 2. Fetch the page (newest enrolled first)
    page_links = list(
        PatientLink.objects.filter(tenant_id=tenant_id)
        .order_by("-enrolled_at")
        [offset: offset + limit]
    )

    # 3. Batch-fetch demographics — single query, no N+1
    patient_ids = [pl.patient_id for pl in page_links]
    demos_by_id: dict[int, PatientDTO] = {
        d.id: d for d in get_patients_by_ids(patient_ids)
    }

    # 4. Build result items
    items: list[EnrolledPatientDTO] = []
    for pl in page_links:
        demo = demos_by_id.get(pl.patient_id)
        items.append(
            EnrolledPatientDTO(
                link_id=pl.id,
                patient_id=pl.patient_id,
                is_active=pl.is_active,
                enrolled_at=pl.enrolled_at,
                full_name=demo.full_name if demo else None,
                national_id=demo.national_id if demo else None,
                phone_number=demo.phone_number if demo else None,
                patient_uuid=str(demo.uuid) if demo else None,
            )
        )

    return PatientListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Clinical record — GET /patients/{uuid}/record  (requires JWT, tenant-scoped)
# ---------------------------------------------------------------------------

@api.get(
    "/patients/{patient_uuid}/record",
    response=ClinicalRecordDTO,
    auth=_jwt_auth,
    tags=["patients"],
)
def get_patient_record(request, patient_uuid: uuid_module.UUID):
    """
    Full clinical record for one patient.

    Tenant-scoped: 404 if no enrollment for this tenant.
    Returns: demographics (via Port) + active conditions + active medications
             + recent vitals (last 10, newest first).
    Reads demographics from 'accounting_read', clinical data from 'default'.
    """
    tenant_id = request.tenant_id

    # 1. Resolve uuid → accounting patient
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    # 2. Find clinical enrollment for THIS tenant
    try:
        link = PatientLink.objects.get(
            tenant_id=tenant_id,
            patient_id=demo.id,
        )
    except PatientLink.DoesNotExist:
        raise Http404(
            f"Patient uuid={patient_uuid} has no enrollment for this tenant."
        )

    # 3. Active conditions with condition metadata (IN query — no N+1)
    patient_conditions = list(
        PatientCondition.objects.filter(
            patient_link_id=link.id,
            is_active=True,
        ).order_by("diagnosed_at")
    )
    # Batch-fetch condition names/codes in one query
    cond_ids = [pc.condition_id for pc in patient_conditions]
    conditions_map: dict[int, Condition] = {}
    if cond_ids:
        conditions_map = {
            c.id: c
            for c in Condition.objects.filter(id__in=cond_ids)
        }

    active_conditions = [
        ConditionDTO(
            id=pc.id,
            condition_id=pc.condition_id,
            condition_name=(
                conditions_map[pc.condition_id].name
                if pc.condition_id in conditions_map else None
            ),
            condition_code=(
                conditions_map[pc.condition_id].code
                if pc.condition_id in conditions_map else None
            ),
            stage=pc.stage,
            onset_date=pc.onset_date,
            notes=pc.notes,
            is_active=pc.is_active,
            diagnosed_at=pc.diagnosed_at,
        )
        for pc in patient_conditions
    ]

    # 4. Active medications only
    active_medications = [
        MedicationDTO(
            id=m.id,
            drug_name=m.drug_name,
            dose=m.dose,
            schedule=m.schedule,
            start_date=m.start_date,
            refill_due_date=m.refill_due_date,
            drug_class=m.drug_class,
            is_active=m.is_active,
            notes=m.notes,
            created_at=m.created_at,
        )
        for m in PatientMedication.objects.filter(
            patient_link_id=link.id,
            is_active=True,
        ).order_by("-created_at")
    ]

    # 5. Recent vitals — last 10, newest first
    recent_vitals = list(
        VitalReading.objects.filter(
            patient_link_id=link.id,
        ).order_by("-measured_at")[:10]
    )

    return ClinicalRecordDTO(
        patient_link_id=link.id,
        demographics=demo,
        active_conditions=active_conditions,
        active_medications=active_medications,
        recent_vitals=[
            VitalReadingDTO(
                id=v.id,
                patient_link_id=v.patient_link_id,
                type=v.type,
                value=v.value,
                unit=v.unit,
                measured_at=v.measured_at,
                source=v.source,
                notes=v.notes,
            )
            for v in recent_vitals
        ],
    )


# ---------------------------------------------------------------------------
# Patient endpoint — requires JWT
# ---------------------------------------------------------------------------

@api.get("/patients/{patient_uuid}", response=PatientDTO, auth=_jwt_auth, tags=["patients"])
def get_patient(request, patient_uuid: uuid_module.UUID):
    """Return patient demographics from accounting schema (read-only). Requires JWT."""
    dto = get_patient_by_uuid(patient_uuid)
    if dto is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")
    return dto


# ---------------------------------------------------------------------------
# Vitals endpoint — requires JWT
# ---------------------------------------------------------------------------

@api.get(
    "/patients/{patient_uuid}/vitals/latest",
    response=list[VitalReadingDTO],
    auth=_jwt_auth,
    tags=["vitals"],
)
def get_latest_vitals(request, patient_uuid: uuid_module.UUID):
    """
    Return the most recent VitalReading for each type for this patient. Requires JWT.

    Lookup chain: accounting.patients(uuid) → clinical.patient_links → vital_readings.
    Raises 404 if the patient or the clinical enrollment doesn't exist.
    """
    # 1. Resolve uuid → accounting patient id (read-only)
    patient_dto = get_patient_by_uuid(patient_uuid)
    if patient_dto is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    # 2. Find the clinical patient_link
    try:
        link = PatientLink.objects.get(patient_id=patient_dto.id, is_active=True)
    except PatientLink.DoesNotExist:
        raise Http404(f"Patient uuid={patient_uuid} has no active clinical enrollment.")

    # 3. Latest reading per type
    latest_per_type = (
        VitalReading.objects.filter(patient_link_id=link.id)
        .order_by("type", "-measured_at")
        .distinct("type")
    )

    return list(latest_per_type)


# ---------------------------------------------------------------------------
# Suggestion engine schemas
# ---------------------------------------------------------------------------

class SuggestionRuleDTO(Schema):
    """One fired clinical rule — suggestion-only framing."""
    rule_code: str
    title: str
    category: str
    condition_code: str
    recommendation: Optional[str] = None
    dosage_titration: Optional[str] = None
    monitoring: Optional[str] = None
    contraindications: Optional[str] = None
    evidence_level: Optional[str] = None
    action_type: str
    severity: str      # info | warn | urgent
    priority: int
    source_ref: Optional[str] = None
    section: str       # UI bucket: redflags | safety | risk | treatment | assessment | monitoring | vaccination | lifestyle
    # Safety marker — always True. Carries the "تأیید با پزشک" obligation.
    suggestion_only: bool


class SuggestionSectionDTO(Schema):
    key: str
    label: str
    rules: list[SuggestionRuleDTO]


class SuggestionsResponseDTO(Schema):
    patient_link_id: int
    count: int
    has_redflag: bool
    # suggestion-only framing label — displayed in the UI
    framing: str
    sections: list[SuggestionSectionDTO]


# ---------------------------------------------------------------------------
# Suggestions endpoint — GET /patients/{uuid}/suggestions
# ---------------------------------------------------------------------------

@api.get(
    "/patients/{patient_uuid}/suggestions",
    response=SuggestionsResponseDTO,
    auth=_jwt_auth,
    tags=["clinical"],
)
def get_suggestions(request, patient_uuid: uuid_module.UUID):
    """
    Return grouped clinical suggestions for one enrolled patient.

    Output is SUGGESTION-ONLY: every rule carries suggestion_only=True and
    the response carries a framing label ("پیشنهاد — تأیید با پزشک").

    Only fired rules are returned (trigger_json evaluated against the patient's
    current facts). Rules with NULL trigger_json (reference-only catalog rows)
    are excluded.

    Requires JWT. Tenant-scoped: 404 if patient has no enrollment for this tenant.
    """
    tenant_id = request.tenant_id

    # 1. Resolve uuid → accounting patient
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    # 2. Find clinical enrollment for THIS tenant
    try:
        link = PatientLink.objects.get(
            tenant_id=tenant_id,
            patient_id=demo.id,
        )
    except PatientLink.DoesNotExist:
        raise Http404(
            f"Patient uuid={patient_uuid} has no enrollment for this tenant."
        )

    # 3. Run the suggestion engine (read-only)
    result = _rule_engine.grouped(
        patient_link_id=link.id,
        demographics=demo,
        tenant_id=tenant_id,
    )

    # 4. Serialise
    sections = [
        SuggestionSectionDTO(
            key=sec["key"],
            label=sec["label"],
            rules=[
                SuggestionRuleDTO(
                    rule_code=r["rule_code"],
                    title=r["title"],
                    category=r["category"],
                    condition_code=r["condition_code"],
                    recommendation=r.get("recommendation"),
                    dosage_titration=r.get("dosage_titration"),
                    monitoring=r.get("monitoring"),
                    contraindications=r.get("contraindications"),
                    evidence_level=r.get("evidence_level"),
                    action_type=r["action_type"],
                    severity=r["severity"],
                    priority=r["priority"],
                    source_ref=r.get("source_ref"),
                    section=r["section"],
                    suggestion_only=r["suggestion_only"],
                )
                for r in sec["rules"]
            ],
        )
        for sec in result["sections"]
    ]

    return SuggestionsResponseDTO(
        patient_link_id=link.id,
        count=result["count"],
        has_redflag=result["has_redflag"],
        framing="پیشنهاد — تأیید با پزشک",
        sections=sections,
    )


# ---------------------------------------------------------------------------
# ACT slice — follow-up worklist + suggestion action
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


class SuggestionActionRequest(Schema):
    """Body for accept/dismiss suggestion action."""
    action: str        # 'accept' | 'dismiss'
    note: Optional[str] = None


class SuggestionLogDTO(Schema):
    """Suggestion log row returned after an action."""
    id: int
    patient_link_id: int
    tenant_id: int
    rule_code: str
    status: str
    acted_by: Optional[str] = None
    acted_at: Optional[datetime] = None
    note: Optional[str] = None
    created_at: datetime


# ── GET /worklist ─────────────────────────────────────────────────────────────

@api.get(
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
):
    """
    Paginated follow-up worklist for the authenticated tenant.

    Default filter: status='open' and due_date <= today (due tasks).
    Pass ?status=done or ?status=dismissed to see other states.
    Ordered by due_date ASC (oldest-due first), then id.

    N+1-avoidance: page tasks first, then batch-fetch demographics for the page
    via AccountingReadPort.get_patients_by_ids().

    Returns 401 without JWT. Tasks from other tenants are never shown.
    """
    tenant_id = request.tenant_id
    today = timezone.now().date()

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

    patient_ids = list({pl.patient_id for pl in links_map.values()})
    demos_by_pid: dict[int, PatientDTO] = {
        d.id: d for d in get_patients_by_ids(patient_ids)
    }

    items: list[WorklistItemDTO] = []
    for task in page_tasks:
        pl = links_map.get(task.patient_link_id)
        demo = demos_by_pid.get(pl.patient_id) if pl else None
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
            )
        )

    return WorklistResponseDTO(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# ── POST /worklist/{task_id}/done ─────────────────────────────────────────────

@api.post(
    "/worklist/{task_id}/done",
    response={200: FollowupTaskDTO, 404: dict, 409: dict},
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
        return 404, {"detail": f"FollowupTask id={task_id} not found for this tenant."}

    if task.status != FollowupTask.STATUS_OPEN:
        return 409, {
            "detail": (
                f"Task id={task_id} is already '{task.status}'; "
                "only open tasks can be marked done."
            )
        }

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


# ── POST /patients/{uuid}/suggestions/{rule_code}/action ─────────────────────

@api.post(
    "/patients/{patient_uuid}/suggestions/{rule_code}/action",
    response={200: SuggestionLogDTO, 400: dict, 404: dict},
    auth=_jwt_auth,
    tags=["clinical"],
)
def suggestion_action(
    request,
    patient_uuid: uuid_module.UUID,
    rule_code: str,
    body: SuggestionActionRequest,
):
    """
    Record physician accept or dismiss of a clinical suggestion.

    Upsert semantics (matching the specialist_clinic Flask app's per-(patient, rule)
    behaviour): if a suggestion_log row for (tenant_id, patient_link_id, rule_code)
    already exists, UPDATE it — do NOT create a duplicate.

    Body: {action: 'accept'|'dismiss', note?: str}

    Returns 404 if no enrollment for this uuid in this tenant.
    Returns 400 if action value is invalid.
    Clinical WRITE — uses 'default' connection (platform_app role).
    Accounting data accessed read-only via AccountingReadPort only.
    """
    tenant_id = request.tenant_id

    # 1. Validate action
    if body.action not in ("accept", "dismiss"):
        return 400, {
            "detail": f"Invalid action '{body.action}'. Must be 'accept' or 'dismiss'."
        }

    # 2. Resolve uuid → accounting patient (read-only via Port)
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    # 3. Find clinical enrollment for THIS tenant
    try:
        link = PatientLink.objects.get(
            tenant_id=tenant_id,
            patient_id=demo.id,
        )
    except PatientLink.DoesNotExist:
        raise Http404(
            f"Patient uuid={patient_uuid} has no enrollment for this tenant."
        )

    # 4. Map action → status
    new_status = (
        SuggestionLog.STATUS_ACCEPTED
        if body.action == "accept"
        else SuggestionLog.STATUS_DISMISSED
    )

    # 5. Determine actor from the JWT user (request.auth is set by JWTBearer)
    actor = getattr(request.auth, "username", None) or "unknown"

    now = timezone.now()

    # 6. Upsert: UPDATE if exists, INSERT if not.
    #    UNIQUE(tenant_id, patient_link_id, rule_code) — one row per (patient, rule).
    try:
        log_row = SuggestionLog.objects.get(
            tenant_id=tenant_id,
            patient_link_id=link.id,
            rule_code=rule_code,
        )
        # Row exists — update status, actor, timestamp, note
        log_row.status = new_status
        log_row.acted_by = actor
        log_row.acted_at = now
        if body.note is not None:
            log_row.note = body.note
        log_row.save(update_fields=["status", "acted_by", "acted_at", "note"])
    except SuggestionLog.DoesNotExist:
        # New row
        log_row = SuggestionLog.objects.create(
            tenant_id=tenant_id,
            patient_link_id=link.id,
            rule_code=rule_code,
            status=new_status,
            acted_by=actor,
            acted_at=now,
            note=body.note,
            created_at=now,
        )

    # Audit: state-changing write — append-only, best-effort
    audit_action_type = (
        "suggestion_accepted" if body.action == "accept" else "suggestion_dismissed"
    )
    log_activity(
        tenant_id=tenant_id,
        user_id=getattr(request.auth, "pk", None),
        username=actor,
        action_type=audit_action_type,
        action_category="clinical",
        target_table="suggestion_log",
        target_id=log_row.id,
        patient_link_id=link.id,
        description=f"rule_code={rule_code}",
    )

    return 200, SuggestionLogDTO(
        id=log_row.id,
        patient_link_id=log_row.patient_link_id,
        tenant_id=log_row.tenant_id,
        rule_code=log_row.rule_code,
        status=log_row.status,
        acted_by=log_row.acted_by,
        acted_at=log_row.acted_at,
        note=log_row.note,
        created_at=log_row.created_at,
    )
