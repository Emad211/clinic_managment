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

  Encounter write-path (Step 10):
  POST /api/v1/patients/{uuid}/encounters                         → create encounter (requires JWT) → 201 EncounterOut
  GET  /api/v1/patients/{uuid}/encounters                         → paginated encounter list (requires JWT)
  POST /api/v1/encounters/{encounter_id}/vitals                   → add vitals list (requires JWT)
  POST /api/v1/encounters/{encounter_id}/labs                     → add labs list (requires JWT)
  POST /api/v1/encounters/{encounter_id}/complete                 → complete encounter (requires JWT)
  POST /api/v1/encounters/{encounter_id}/cancel                   → cancel encounter (requires JWT)
"""
import uuid as uuid_module
from typing import Optional
from datetime import datetime, date

from ninja import NinjaAPI, Schema, Query
from django.http import Http404
from django.utils import timezone

from config.errors import ErrorSchema, error_response
from config.pagination import paginate
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
from clinical.suggestion_service import grouped_for_patient as _grouped_for_patient
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
# Global exception handler — Http404 → uniform error contract
#
# django-ninja converts Http404 to {"detail": "Not Found"} by default,
# which lacks the `code` field the contract requires.  By registering a
# handler here, every `raise Http404(...)` in any endpoint of *this* API
# returns the standard ErrorSchema shape, so the web client still reads
# `detail` and new consumers can branch on `code`.
# ---------------------------------------------------------------------------
from django.http import JsonResponse as _JsonResponse


@api.exception_handler(Http404)
def _handle_404(request, exc):
    return _JsonResponse(
        error_response(str(exc) or "Not Found", "not_found"),
        status=404,
    )


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

@api.post("/auth/login", response={200: TokenResponse, 401: ErrorSchema, 423: ErrorSchema}, auth=None, tags=["auth"])
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
        return 423, error_response(str(exc), "account_locked")
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
        return 401, error_response(str(exc), "invalid_credentials")


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

    return PatientListResponse(**paginate(total, items, limit, offset))


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
    # Prior physician action for this rule, if any: 'accepted' | 'dismissed' | None
    prior_action: Optional[str] = None


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

    # 3. Run the suggestion engine via the canonical bridge helper.
    # grouped_for_patient resolves demographics from the Port internally,
    # ensuring age-gated rules always have a birthdate — even when this
    # endpoint is refactored or reused in batch/non-HTTP contexts.
    # Note: demo was already fetched above (step 1) to locate the PatientLink.
    # grouped_for_patient performs one additional Port fetch (same patient,
    # single indexed PK lookup) — acceptable overhead for centralisation.
    result = _grouped_for_patient(
        patient_link_id=link.id,
        tenant_id=tenant_id,
    )

    # 3b. Collect all fired rule_codes from the engine result, then fetch
    # SuggestionLog rows in ONE query (no N+1). Build a {rule_code: status} map.
    fired_codes = [
        r["rule_code"]
        for sec in result["sections"]
        for r in sec["rules"]
    ]
    prior_action_map: dict[str, str] = {}
    if fired_codes:
        logs = SuggestionLog.objects.filter(
            tenant_id=tenant_id,
            patient_link_id=link.id,
            rule_code__in=fired_codes,
        ).values("rule_code", "status")
        prior_action_map = {row["rule_code"]: row["status"] for row in logs}

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
                    prior_action=prior_action_map.get(r["rule_code"]),
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

@api.post(
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


# ── POST /patients/{uuid}/suggestions/{rule_code}/action ─────────────────────

@api.post(
    "/patients/{patient_uuid}/suggestions/{rule_code}/action",
    response={200: SuggestionLogDTO, 400: ErrorSchema, 404: ErrorSchema},
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
        return 400, error_response(
            f"Invalid action '{body.action}'. Must be 'accept' or 'dismiss'.",
            "validation_error",
        )

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


# ===========================================================================
# Encounter write-path (Step 10)
# ===========================================================================

from typing import List as _List
from clinical.models import Encounter as _Encounter
from clinical.encounter_service import (
    create_encounter as _create_encounter,
    add_vital_to_encounter as _add_vital_to_encounter,
    add_lab_to_encounter as _add_lab_to_encounter,
    complete_encounter as _complete_encounter,
    cancel_encounter as _cancel_encounter,
    add_prescription_to_encounter as _add_prescription_to_encounter,
    EncounterNotFound as _EncounterNotFound,
    InvalidEncounterTransition as _InvalidEncounterTransition,
    EncounterSealed as _EncounterSealed,
    InvalidEncounterType as _InvalidEncounterType,
    DuplicateVitalReading as _DuplicateVitalReading,
    InsurancePrescriptionNotSupported as _InsurancePrescriptionNotSupported,
    PrescriptionItemValidationError as _PrescriptionItemValidationError,
)


# ---------------------------------------------------------------------------
# Input/Output schemas
# ---------------------------------------------------------------------------

class CreateEncounterIn(Schema):
    """Body for POST /patients/{uuid}/encounters."""
    encounter_type: str = "visit"
    encounter_at: Optional[datetime] = None
    chief_complaint: Optional[str] = None
    doctor_id: Optional[int] = None
    appointment_id: Optional[int] = None


class EncounterOut(Schema):
    """Encounter representation returned from all encounter endpoints."""
    id: int
    tenant_id: int
    patient_link_id: int
    encounter_type: str
    encounter_at: datetime
    status: str
    chief_complaint: Optional[str] = None
    doctor_id: Optional[int] = None
    appointment_id: Optional[int] = None
    accounting_invoice_id: Optional[int] = None
    completed_at: Optional[datetime] = None
    summary_note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EncounterListResponse(Schema):
    items: list[EncounterOut]
    total: int
    limit: int
    offset: int


class VitalIn(Schema):
    """One vital reading to add under an encounter."""
    type: str
    value: float
    unit: Optional[str] = None
    source: str = "clinic"
    measured_at: Optional[datetime] = None


class VitalReadingCreatedDTO(Schema):
    """A created vital reading."""
    id: int
    patient_link_id: int
    type: str
    value: float
    unit: Optional[str] = None
    source: Optional[str] = None
    measured_at: datetime
    recorded_by: Optional[str] = None


class LabIn(Schema):
    """
    One lab result to add under an encounter.

    test_key is a soft FK to lab_test_catalog.test_key — pass null if the catalog
    row does not exist yet; the LabResult will still be saved (test_name is the
    required human-readable label).
    """
    test_name: str
    test_key: Optional[str] = None   # nullable; must match lab_test_catalog if supplied
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    taken_at: Optional[datetime] = None


class LabResultCreatedDTO(Schema):
    """A created lab result."""
    id: int
    patient_link_id: int
    encounter_id: Optional[int] = None
    test_name: str
    test_key: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    taken_at: datetime
    recorded_by: Optional[str] = None


class VitalsAddedResponse(Schema):
    """Response from POST /encounters/{id}/vitals (list add)."""
    count: int
    vitals: list[VitalReadingCreatedDTO]


class LabsAddedResponse(Schema):
    """Response from POST /encounters/{id}/labs (list add)."""
    count: int
    labs: list[LabResultCreatedDTO]


class CompleteEncounterIn(Schema):
    summary_note: Optional[str] = None


class CancelEncounterIn(Schema):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encounter_to_out(enc: _Encounter) -> EncounterOut:
    return EncounterOut(
        id=enc.id,
        tenant_id=enc.tenant_id,
        patient_link_id=enc.patient_link_id,
        encounter_type=enc.encounter_type,
        encounter_at=enc.encounter_at,
        status=enc.status,
        chief_complaint=enc.chief_complaint,
        doctor_id=enc.doctor_id,
        appointment_id=enc.appointment_id,
        accounting_invoice_id=enc.accounting_invoice_id,
        completed_at=enc.completed_at,
        summary_note=enc.summary_note,
        created_by=enc.created_by,
        created_at=enc.created_at,
        updated_at=enc.updated_at,
    )


def _resolve_patient_link_for_tenant(
    patient_uuid: uuid_module.UUID,
    tenant_id: int,
) -> "PatientLink":
    """
    Resolve patient_uuid → accounting patient → clinical PatientLink for tenant.
    Raises Http404 at each step (handled by the global handler).
    """
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")
    try:
        link = PatientLink.objects.get(
            tenant_id=tenant_id,
            patient_id=demo.id,
        )
    except PatientLink.DoesNotExist:
        raise Http404(
            f"Patient uuid={patient_uuid} has no enrollment for this tenant."
        )
    return link


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/encounters — create encounter
# ---------------------------------------------------------------------------

@api.post(
    "/patients/{patient_uuid}/encounters",
    response={
        201: EncounterOut,
        404: ErrorSchema,
        422: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def create_encounter_endpoint(
    request,
    patient_uuid: uuid_module.UUID,
    body: CreateEncounterIn,
):
    """
    Create a new encounter (status=open) for an enrolled patient.

    encounter_type: 'visit' (default) | 'follow_up' | 'phone' | 'remote'.
    doctor_id / appointment_id / accounting_invoice_id are stored id snapshots —
    they reference existing rows but are NEVER accounting writes.
    Returns 201 on success, 404 if patient/enrollment not found,
    422 if encounter_type is invalid.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    try:
        enc = _create_encounter(
            patient_link_id=link.id,
            tenant_id=tenant_id,
            encounter_type=body.encounter_type,
            encounter_at=body.encounter_at,
            chief_complaint=body.chief_complaint,
            doctor_id=body.doctor_id,
            appointment_id=body.appointment_id,
            created_by=actor,
        )
    except _InvalidEncounterType as exc:
        return 422, error_response(str(exc), "validation_error")

    return 201, _encounter_to_out(enc)


# ---------------------------------------------------------------------------
# GET /patients/{uuid}/encounters — paginated list
# ---------------------------------------------------------------------------

@api.get(
    "/patients/{patient_uuid}/encounters",
    response=EncounterListResponse,
    auth=_jwt_auth,
    tags=["encounters"],
)
def list_encounters(
    request,
    patient_uuid: uuid_module.UUID,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    Paginated list of encounters for one enrolled patient, newest first.

    Tenant-scoped: 404 if no enrollment for this uuid in this tenant.
    """
    tenant_id = request.tenant_id
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    qs = _Encounter.objects.filter(
        patient_link_id=link.id,
        tenant_id=tenant_id,
    )
    total = qs.count()
    page = list(qs.order_by("-encounter_at")[offset: offset + limit])

    return EncounterListResponse(
        **paginate(total, [_encounter_to_out(e) for e in page], limit, offset)
    )


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/vitals — add list of vitals
# ---------------------------------------------------------------------------

@api.post(
    "/encounters/{encounter_id}/vitals",
    response={
        200: VitalsAddedResponse,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def add_vitals(
    request,
    encounter_id: int,
    body: _List[VitalIn],
):
    """
    Add one or more vital readings to an open encounter.

    Accepts a JSON array of VitalIn objects.
    Returns 409 with code='encounter_sealed' if the encounter is not open.
    Returns 409 with code='duplicate_vital' if any vital would violate the UNIQUE key.
    The service is called per item; on error after partial success the already-written
    items remain (each item is individually audited by the service).

    Note: test_key for each vital is NOT a lab field here — VitalIn.type is the
    vital_readings.type value (e.g. 'bp_systolic', 'hba1c').
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    created = []
    try:
        for item in body:
            reading = _add_vital_to_encounter(
                encounter_id,
                tenant_id,
                type=item.type,
                value=item.value,
                unit=item.unit,
                source=item.source,
                measured_at=item.measured_at,
                recorded_by=actor,
            )
            created.append(
                VitalReadingCreatedDTO(
                    id=reading.id,
                    patient_link_id=reading.patient_link_id,
                    type=reading.type,
                    value=reading.value,
                    unit=reading.unit,
                    source=reading.source,
                    measured_at=reading.measured_at,
                    recorded_by=reading.recorded_by,
                )
            )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _EncounterSealed as exc:
        return 409, error_response(str(exc), "encounter_sealed")
    except _DuplicateVitalReading as exc:
        return 409, error_response(str(exc), "duplicate_vital")

    return 200, VitalsAddedResponse(count=len(created), vitals=created)


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/labs — add list of labs
# ---------------------------------------------------------------------------

@api.post(
    "/encounters/{encounter_id}/labs",
    response={
        200: LabsAddedResponse,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def add_labs(
    request,
    encounter_id: int,
    body: _List[LabIn],
):
    """
    Add one or more lab results to an open encounter.

    Accepts a JSON array of LabIn objects.
    test_key is a soft FK to lab_test_catalog.test_key — if non-null, the
    catalog row must already exist (the DB will reject it otherwise).
    Returns 409 with code='encounter_sealed' if encounter is not open.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    created = []
    try:
        for item in body:
            lab = _add_lab_to_encounter(
                encounter_id,
                tenant_id,
                test_name=item.test_name,
                test_key=item.test_key,
                value=item.value,
                unit=item.unit,
                ref_low=item.ref_low,
                ref_high=item.ref_high,
                taken_at=item.taken_at,
                recorded_by=actor,
            )
            created.append(
                LabResultCreatedDTO(
                    id=lab.id,
                    patient_link_id=lab.patient_link_id,
                    encounter_id=lab.encounter_id,
                    test_name=lab.test_name,
                    test_key=lab.test_key,
                    value=lab.value,
                    unit=lab.unit,
                    ref_low=lab.ref_low,
                    ref_high=lab.ref_high,
                    taken_at=lab.taken_at,
                    recorded_by=lab.recorded_by,
                )
            )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _EncounterSealed as exc:
        return 409, error_response(str(exc), "encounter_sealed")

    return 200, LabsAddedResponse(count=len(created), labs=created)


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/complete — complete an open encounter
# ---------------------------------------------------------------------------

@api.post(
    "/encounters/{encounter_id}/complete",
    response={
        200: EncounterOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def complete_encounter_endpoint(
    request,
    encounter_id: int,
    body: CompleteEncounterIn,
):
    """
    Transition an open encounter to 'completed'.

    Returns 409 with code='invalid_transition' if the encounter is not open.
    Returns 404 with code='not_found' if the encounter does not exist for this tenant.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    try:
        enc = _complete_encounter(
            encounter_id,
            tenant_id,
            summary_note=body.summary_note,
            completed_by=actor,
        )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _InvalidEncounterTransition as exc:
        return 409, error_response(str(exc), "invalid_transition")

    return 200, _encounter_to_out(enc)


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/cancel — cancel an open encounter
# ---------------------------------------------------------------------------

@api.post(
    "/encounters/{encounter_id}/cancel",
    response={
        200: EncounterOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def cancel_encounter_endpoint(
    request,
    encounter_id: int,
    body: CancelEncounterIn,
):
    """
    Transition an open encounter to 'cancelled'.

    reason is stored in summary_note (no dedicated cancel_reason column).
    Returns 409 with code='invalid_transition' if the encounter is not open.
    Returns 404 with code='not_found' if not found for this tenant.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    try:
        enc = _cancel_encounter(
            encounter_id,
            tenant_id,
            reason=body.reason,
            cancelled_by=actor,
        )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _InvalidEncounterTransition as exc:
        return 409, error_response(str(exc), "invalid_transition")

    return 200, _encounter_to_out(enc)


# ===========================================================================
# Prescription write-path (Step 11) — mode='free' only
# Insurance/MV3 bridge is BLOCKED — do NOT add mode='insurance' support here.
# ===========================================================================

from decimal import Decimal as _Decimal
from clinical.models import Prescription as _Prescription, PrescriptionItem as _PrescriptionItem


# ---------------------------------------------------------------------------
# Prescription schemas
# ---------------------------------------------------------------------------

class PrescriptionItemIn(Schema):
    """
    One prescription item.

    drug_name is required; all other fields are optional.
    frequency must be one of: od, bid, tid, qid, qod, weekly, monthly, prn,
      with_meal, bedtime, other (or omitted).
    route must be one of: oral, sublingual, sc, im, iv, topical, inhaled, other
      (or omitted).
    quantity and duration_days must be > 0 if provided.
    """
    drug_name: str
    drug_class: Optional[str] = None
    dose_value: Optional[float] = None         # NUMERIC(10,3) — float in API, Decimal in DB
    dose_unit: Optional[str] = None
    frequency: Optional[str] = None            # validated by service against allowed set
    route: Optional[str] = None                # validated by service against allowed set
    quantity: Optional[int] = None             # > 0
    duration_days: Optional[int] = None        # > 0
    instructions: Optional[str] = None


class CreatePrescriptionIn(Schema):
    """Body for POST /encounters/{encounter_id}/prescriptions."""
    kind: str
    items: list[PrescriptionItemIn]
    mode: str = "free"                         # default free; 'insurance' is rejected


class PrescriptionItemOut(Schema):
    """One created prescription item."""
    id: int
    tenant_id: int
    prescription_id: int
    drug_name: str
    drug_class: Optional[str] = None
    dose_value: Optional[float] = None
    dose_unit: Optional[str] = None
    frequency: Optional[str] = None
    route: Optional[str] = None
    quantity: Optional[int] = None
    duration_days: Optional[int] = None
    instructions: Optional[str] = None


class PrescriptionOut(Schema):
    """Created prescription header + items."""
    id: int
    tenant_id: int
    patient_link_id: int
    encounter_id: Optional[int] = None
    kind: str
    mode: str
    prescriber_user_id: Optional[int] = None
    followup_task_id: Optional[int] = None
    issued_at: datetime
    items_structured: list[PrescriptionItemOut]


# ---------------------------------------------------------------------------
# Helper — build PrescriptionOut from ORM objects
# ---------------------------------------------------------------------------

def _prescription_to_out(
    rx: "_Prescription",
    item_rows: "list[_PrescriptionItem]",
) -> PrescriptionOut:
    return PrescriptionOut(
        id=rx.id,
        tenant_id=rx.tenant_id,
        patient_link_id=rx.patient_link_id,
        encounter_id=rx.encounter_id,
        kind=rx.kind,
        mode=rx.mode,
        prescriber_user_id=rx.prescriber_user_id,
        followup_task_id=rx.followup_task_id,
        issued_at=rx.issued_at,
        items_structured=[
            PrescriptionItemOut(
                id=item.id,
                tenant_id=item.tenant_id,
                prescription_id=item.prescription_id,
                drug_name=item.drug_name,
                drug_class=item.drug_class,
                dose_value=float(item.dose_value) if item.dose_value is not None else None,
                dose_unit=item.dose_unit,
                frequency=item.frequency,
                route=item.route,
                quantity=item.quantity,
                duration_days=item.duration_days,
                instructions=item.instructions,
            )
            for item in item_rows
        ],
    )


# ---------------------------------------------------------------------------
# POST /encounters/{encounter_id}/prescriptions — create free prescription
# ---------------------------------------------------------------------------

@api.post(
    "/encounters/{encounter_id}/prescriptions",
    response={
        201: PrescriptionOut,
        400: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
        422: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["encounters"],
)
def create_prescription(
    request,
    encounter_id: int,
    body: CreatePrescriptionIn,
):
    """
    Add a free-mode prescription (header + structured items) to an open encounter.

    Only mode='free' is supported. Passing mode='insurance' returns 422
    (insurance_prescription_not_supported) — the insurance/MV3 bridge track
    is blocked pending owner live access.

    The prescription header and all items are created in a single transaction:
    either all items are saved or none (no orphaned header on item failure).

    Returns 201 with the created prescription + items on success.
    Returns 404 if the encounter does not exist for this tenant.
    Returns 409 (encounter_sealed) if the encounter is not open.
    Returns 422 for mode='insurance' or item validation errors (bad frequency,
    bad route, quantity/duration_days <= 0, empty drug_name).
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    user_id = getattr(request.auth, "pk", None)

    # Convert Pydantic schema list to plain dicts for the service layer
    items_dicts = [item.dict() for item in body.items]

    try:
        rx = _add_prescription_to_encounter(
            encounter_id,
            tenant_id,
            kind=body.kind,
            items=items_dicts,
            mode=body.mode,
            prescriber_user_id=user_id,
            created_by=actor,
        )
    except _EncounterNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _EncounterSealed as exc:
        return 409, error_response(str(exc), "encounter_sealed")
    except _InsurancePrescriptionNotSupported as exc:
        return 422, error_response(str(exc), "insurance_prescription_not_supported")
    except _PrescriptionItemValidationError as exc:
        return 422, error_response(str(exc), "validation_error")

    # Fetch created items (single query, ordered by id)
    item_rows = list(
        _PrescriptionItem.objects.filter(
            prescription_id=rx.id,
            tenant_id=tenant_id,
        ).order_by("id")
    )

    return 201, _prescription_to_out(rx, item_rows)


# ===========================================================================
# Doctor visit queue (Step 14) — read-only accounting + local state
#
# GET  /doctor-queue?work_date=YYYY-MM-DD  → {waiting, done, work_date}
# POST /doctor-queue/{accounting_invoice_id}/start  → DoctorVisitLogOut
# POST /doctor-queue/{accounting_invoice_id}/done   → DoctorVisitLogOut
#
# NEVER writes accounting. Queue state lives ONLY in clinical.doctor_visit_log.
# Open invoices are fetched via accounting_port.fetch_open_visit_invoices
# (SELECT-only at Postgres DB level — enforced by GRANTs in slice0/slice3).
# ===========================================================================

from clinical.doctor_queue_service import (
    get_queue as _get_queue,
    start_visit as _start_visit,
    end_visit as _end_visit,
    InvoiceNotOpen as _InvoiceNotOpen,
    VisitAlreadyDone as _VisitAlreadyDone,
)


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

@api.get(
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

@api.post(
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

@api.post(
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


# ===========================================================================
# Control Room (Step 15) — prioritized cohort targeting
#
# GET  /control-room              → panel (JWT required; show_value = role=='manager')
# GET  /control-room/conversion   → funnel conversion metric (JWT required)
# GET  /control-room/cohort/{key} → recomputed cohort patient ids (JWT required)
#
# Clinical-first priority score; revenue is manager-only seasoning.
# Non-managers: show_value=False (no revenue column, no valuable_drifting cohort).
# NEVER writes accounting.  All revenue reads via accounting_port (read-only).
# ===========================================================================

import clinical.control_room_service as _cr_svc


# ---------------------------------------------------------------------------
# Control Room schemas
# ---------------------------------------------------------------------------

class ControlRoomFlagDTO(Schema):
    """A danger or warn indicator flag for a patient."""
    label: str
    value: float


class ControlRoomPatientDTO(Schema):
    """One patient entry in the control-room panel."""
    id: int                                   # patient_link_id
    patient_id: int                           # accounting patient id
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    opt_out: bool
    control: str                              # uncontrolled | borderline | controlled | unknown
    flags: list[ControlRoomFlagDTO]
    warns: list[ControlRoomFlagDTO]
    lapsed: bool
    days_since_last: Optional[int] = None
    last_observed_at: Optional[str] = None   # ISO datetime or null
    open_fu: int
    value: Optional[int] = None              # revenue Toman (manager-only; null for staff)
    score: int
    breakdown: list                           # [(label, points), ...]
    conditions: list[str]
    upcoming: bool


class ControlRoomCohortDTO(Schema):
    """A cohort bucket with count and member ids."""
    key: str
    label: str
    count: int
    ids: list[int]


class ControlRoomPanelResponse(Schema):
    """Full control-room panel response."""
    patients: list[ControlRoomPatientDTO]
    cohorts: list[ControlRoomCohortDTO]
    median_rev: int
    total: int
    show_value: bool


class ConversionResponse(Schema):
    """Follow-up → visit funnel conversion metric."""
    resolved: int       # total resolved (status='done') tasks
    to_visit: int       # of those, linked to an appointment
    rate: float         # to_visit * 100 / resolved (0 if no resolved)


class CohortIdsResponse(Schema):
    cohort_key: str
    ids: list[int]
    count: int


# ---------------------------------------------------------------------------
# GET /control-room — full panel
# ---------------------------------------------------------------------------

@api.get(
    "/control-room",
    response=ControlRoomPanelResponse,
    auth=_jwt_auth,
    tags=["control_room"],
)
def control_room_panel(request):
    """
    Return the prioritized control-room panel for the authenticated tenant.

    show_value = (role == 'manager'):
      - Managers see revenue values per patient + the 'valuable_drifting' cohort.
      - Staff see show_value=False — no revenue, no valuable_drifting cohort.

    Clinical-first scoring:
      danger flags×3 + warn flags×1 + lapsed+2 + no-baseline+1 + open_fu capped 3
      + valuable+1 (manager only) − upcoming_appt 2.
    Only patients with score>0 are returned, sorted by score descending.

    Control vitals (hba1c, fbs, bp_systolic, bp_diastolic, ldl, egfr, uacr)
    are read from the unified observations VIEW (vitals+labs) using live
    clinical_indicators thresholds — consistent with the rule engine.

    Demographics batched from accounting_port.get_patients_by_ids().
    Revenue batched from accounting_port.get_revenue_by_patient_ids() (manager only).
    NEVER writes accounting.  Requires JWT (tenant-scoped).
    """
    tenant_id = request.tenant_id
    user_role = getattr(request.auth, "role", "staff")
    show_value = (user_role == "manager")

    data = _cr_svc.panel(tenant_id=tenant_id, show_value=show_value)

    patients_out = [
        ControlRoomPatientDTO(
            id=p["id"],
            patient_id=p["patient_id"],
            full_name=p["full_name"],
            phone_number=p["phone_number"],
            opt_out=p["opt_out"],
            control=p["control"],
            flags=[ControlRoomFlagDTO(**f) for f in p["flags"]],
            warns=[ControlRoomFlagDTO(**f) for f in p["warns"]],
            lapsed=p["lapsed"],
            days_since_last=p["days_since_last"],
            last_observed_at=p["last_observed_at"],
            open_fu=p["open_fu"],
            value=p["value"],
            score=p["score"],
            breakdown=p["breakdown"],
            conditions=p["conditions"],
            upcoming=p["upcoming"],
        )
        for p in data["patients"]
    ]
    cohorts_out = [
        ControlRoomCohortDTO(**c) for c in data["cohorts"]
    ]

    return ControlRoomPanelResponse(
        patients=patients_out,
        cohorts=cohorts_out,
        median_rev=data["median_rev"],
        total=data["total"],
        show_value=data["show_value"],
    )


# ---------------------------------------------------------------------------
# GET /control-room/conversion — funnel metric
# ---------------------------------------------------------------------------

@api.get(
    "/control-room/conversion",
    response=ConversionResponse,
    auth=_jwt_auth,
    tags=["control_room"],
)
def control_room_conversion(request):
    """
    Follow-up → visit conversion funnel metric for this tenant.

    Of all resolved (status='done') follow-ups, the share linked to an
    appointment (appointment_id IS NOT NULL) indicates whether the recall
    funnel actually lands patients in a visit.

    Returns: {resolved, to_visit, rate}.
    Requires JWT (tenant-scoped).
    """
    tenant_id = request.tenant_id
    result = _cr_svc.conversion(tenant_id=tenant_id)
    return ConversionResponse(**result)


# ---------------------------------------------------------------------------
# GET /control-room/cohort/{key} — recomputed cohort ids
# ---------------------------------------------------------------------------

@api.get(
    "/control-room/cohort/{cohort_key}",
    response={200: CohortIdsResponse, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["control_room"],
)
def control_room_cohort_ids(request, cohort_key: str):
    """
    Recompute a cohort's patient_link_ids server-side (never trust posted ids).

    Valid cohort keys: uncontrolled_lapsed, valuable_drifting (manager only),
    overdue_care, uncontrolled.

    Returns 404 if the key is unknown or not accessible (e.g. valuable_drifting
    for a staff user).
    Requires JWT (tenant-scoped).
    """
    tenant_id = request.tenant_id
    user_role = getattr(request.auth, "role", "staff")
    show_value = (user_role == "manager")

    # Reject valuable_drifting for non-managers (manager-only gate)
    if cohort_key == "valuable_drifting" and not show_value:
        return 404, error_response(
            "valuable_drifting cohort is only accessible to managers.",
            "not_found",
        )

    valid_keys = {k for k, _ in _cr_svc.COHORT_DEFS}
    if cohort_key not in valid_keys:
        return 404, error_response(
            f"Unknown cohort key '{cohort_key}'. "
            f"Valid keys: {sorted(valid_keys)}.",
            "not_found",
        )

    ids = _cr_svc.cohort_ids(
        cohort_key=cohort_key,
        tenant_id=tenant_id,
        show_value=show_value,
    )

    return 200, CohortIdsResponse(
        cohort_key=cohort_key,
        ids=ids,
        count=len(ids),
    )


# ===========================================================================
# Engagement Approval Queue (Step 17) — physician hard gate before any SMS.
#
# GET  /engagement/approvals                  → pending queue (any authed user)
# POST /engagement/approvals/{id}/approve     → pending → approved (manager only)
# POST /engagement/approvals/{id}/reject      → pending → rejected (manager only)
#
# NO SMS is sent here.  Sending (Step 18) ONLY reads approved rows.
# The approve/reject actions are manager-only — the safety gate MUST be privileged.
# ===========================================================================

from clinical.models import EngagementApproval as _EngagementApproval
from clinical.engagement_approval_service import (
    list_pending as _list_pending_approvals,
    approve as _approve_approval,
    reject as _reject_approval,
    ApprovalNotFound as _ApprovalNotFound,
    InvalidApprovalTransition as _InvalidApprovalTransition,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EngagementApprovalDTO(Schema):
    """
    One engagement approval row.

    status values: 'pending' | 'approved' | 'rejected' | 'sent' (Step 18).
    """
    id: int
    tenant_id: int
    patient_link_id: int
    event_key: str
    channel: Optional[str] = None
    due_date: Optional[date] = None
    message: Optional[str] = None
    offer: Optional[str] = None
    status: str
    period_key: Optional[str] = None
    appointment_id: Optional[int] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: datetime


class ApprovalListResponse(Schema):
    """Pending queue list."""
    items: list[EngagementApprovalDTO]
    total: int


class ApproveRejectIn(Schema):
    """Optional body for approve/reject endpoints."""
    reason: Optional[str] = None   # only used by reject; ignored on approve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approval_to_dto(approval: "_EngagementApproval") -> EngagementApprovalDTO:
    return EngagementApprovalDTO(
        id=approval.id,
        tenant_id=approval.tenant_id,
        patient_link_id=approval.patient_link_id,
        event_key=approval.event_key,
        channel=approval.channel,
        due_date=approval.due_date,
        message=approval.message,
        offer=approval.offer,
        status=approval.status,
        period_key=approval.period_key,
        appointment_id=approval.appointment_id,
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        sent_at=approval.sent_at,
        created_at=approval.created_at,
    )


def _assert_manager(request) -> Optional[tuple]:
    """
    Return (403, error_response(...)) if the authenticated user is not a manager.

    Usage in an endpoint:
        guard = _assert_manager(request)
        if guard:
            return guard
    """
    user_role = getattr(request.auth, "role", "staff")
    if user_role != "manager":
        return 403, error_response(
            "This action requires manager role.",
            "forbidden",
        )
    return None


# ---------------------------------------------------------------------------
# GET /engagement/approvals — pending queue (any authed user can VIEW)
# ---------------------------------------------------------------------------

@api.get(
    "/engagement/approvals",
    response=ApprovalListResponse,
    auth=_jwt_auth,
    tags=["engagement"],
)
def list_engagement_approvals(request):
    """
    Return the pending engagement approval queue for the authenticated tenant.

    Any authenticated user (staff or manager) can VIEW the queue.
    Only managers can approve or reject items (see the POST endpoints below).

    Ordered by due_date ASC (nulls last), then newest first within the same day.
    Returns only status='pending' items — use the admin panel or DB directly to
    review approved/rejected history.

    NO SMS is sent here.  Requires JWT (tenant-scoped).
    """
    tenant_id = request.tenant_id
    rows = _list_pending_approvals(tenant_id)
    return ApprovalListResponse(
        items=[_approval_to_dto(r) for r in rows],
        total=len(rows),
    )


# ---------------------------------------------------------------------------
# POST /engagement/approvals/{id}/approve — pending → approved (manager only)
# ---------------------------------------------------------------------------

@api.post(
    "/engagement/approvals/{approval_id}/approve",
    response={
        200: EngagementApprovalDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["engagement"],
)
def approve_engagement_approval(request, approval_id: int, body: ApproveRejectIn = None):
    """
    Approve a pending engagement approval (manager-only).

    Transitions status: pending → approved.
    Sets decided_by (JWT username) and decided_at (now()).
    Does NOT send any SMS — Step 18 will process approved rows.

    Returns 403 if the authenticated user is not a manager.
    Returns 404 if the approval does not exist for this tenant.
    Returns 409 if the approval is not in 'pending' status (already decided).
    Requires JWT (tenant-scoped, manager role).
    """
    # Manager gate — the approval is the privileged safety gate
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"

    try:
        approval = _approve_approval(approval_id, tenant_id, decided_by=actor)
    except _ApprovalNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _InvalidApprovalTransition as exc:
        return 409, error_response(str(exc), "invalid_transition")

    return 200, _approval_to_dto(approval)


# ---------------------------------------------------------------------------
# POST /engagement/approvals/{id}/reject — pending → rejected (manager only)
# ---------------------------------------------------------------------------

@api.post(
    "/engagement/approvals/{approval_id}/reject",
    response={
        200: EngagementApprovalDTO,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["engagement"],
)
def reject_engagement_approval(request, approval_id: int, body: ApproveRejectIn = None):
    """
    Reject a pending engagement approval (manager-only).

    Transitions status: pending → rejected.
    Sets decided_by (JWT username) and decided_at (now()).
    The optional body.reason is appended to the message field for audit trail.

    Returns 403 if the authenticated user is not a manager.
    Returns 404 if the approval does not exist for this tenant.
    Returns 409 if the approval is not in 'pending' status (already decided).
    Requires JWT (tenant-scoped, manager role).
    """
    # Manager gate — the approval is the privileged safety gate
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    reason = body.reason if body else None

    try:
        approval = _reject_approval(approval_id, tenant_id, decided_by=actor, reason=reason)
    except _ApprovalNotFound as exc:
        return 404, error_response(str(exc), "not_found")
    except _InvalidApprovalTransition as exc:
        return 409, error_response(str(exc), "invalid_transition")

    return 200, _approval_to_dto(approval)
