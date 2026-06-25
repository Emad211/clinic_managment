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
  GET  /api/v1/manager/suggestion-stats                           → suggestion analytics per rule (manager-only)

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
    SuggestionEvent,
)
import clinical.rule_engine as _rule_engine
from clinical.rule_engine import _evaluate_reading as _eval_reading
from clinical.models import ClinicalIndicator as _ClinicalIndicator
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
    # Server-evaluated threshold level (from clinical_indicators — never hardcoded).
    # 'ok' | 'warn' | 'danger' | None (None when no clinical_indicators row exists
    # for this vital type, so the UI renders it without a colour badge).
    level: Optional[str] = None
    # slice14: physician review state (step 47).
    # UI derives three states from these two fields:
    #   pending  : verified=False, rejected_at=None
    #   approved : verified=True
    #   rejected : verified=False, rejected_at=(ISO timestamp str)
    # All three fields are always serialised — no hidden state for the client.
    verified: bool = True
    rejected_at: Optional[str] = None   # ISO 8601 string or None


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

    # 6. Build threshold indicator map once (one query) for level evaluation.
    #    Source of truth: clinical_indicators table (never hardcoded thresholds).
    #    Falls back to _evaluate_reading's own static fallback if indicator row
    #    is absent — returning 'ok' when no threshold exists (shown as level=None
    #    below for vital types with no clinical_indicators row at all).
    _indicator_map: dict = {
        row.key: row
        for row in _ClinicalIndicator.objects.filter(
            tenant_id=tenant_id, is_active=True
        )
    }

    def _vital_level(vtype: str, value: float) -> Optional[str]:
        """
        Return 'ok'|'warn'|'danger' when a clinical_indicators row exists for
        this vital type; return None when no indicator row is present (the UI
        renders the vital without a colour badge).
        """
        if vtype not in _indicator_map:
            return None
        return _eval_reading(vtype, value, _indicator_map)

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
                level=_vital_level(v.type, v.value),
                # slice14: always serialise review state so UI can distinguish
                # pending / approved / rejected without extra round-trips.
                verified=v.verified,
                rejected_at=(
                    v.rejected_at.isoformat() if v.rejected_at else None
                ),
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


class DataGapDTO(Schema):
    """
    One missing data item that prevents some active rules from being evaluated.

    Part of the "قاعدهٔ خاموش" (silent-rule) transparency feature.
    Display-only — does not change which rules fire.

    datum         : bare key ("age" | "egfr" | "hba1c" | …)
    label         : Persian display label (from clinical_indicators.label, or "سن" for age)
    affected_rules: number of active rules that reference this datum but could not
                    be evaluated because the value is absent from the patient's facts.
    """
    datum: str
    label: str
    affected_rules: int


class DdiDTO(Schema):
    """
    One drug-drug interaction between two of the patient's ACTIVE medication
    classes (step 36 — DDI data layer).

    Suggestion-only: surfaces a known class-level interaction for the physician
    to review; never auto-changes therapy. Curated, evidence-based pairs only.

    class_a / class_b : interacting drug-class codes (canonical, class_a < class_b)
    severity          : 'contraindicated' | 'major' | 'moderate'
    message_fa        : Persian clinical message (risk + action)
    evidence          : source reference (guideline / study), may be null
    """
    class_a: str
    class_b: str
    severity: str
    message_fa: str
    evidence: str | None = None
    suggestion_only: bool = True


class SuggestionsResponseDTO(Schema):
    patient_link_id: int
    count: int
    has_redflag: bool
    # suggestion-only framing label — displayed in the UI
    framing: str
    sections: list[SuggestionSectionDTO]
    # Data-gap transparency ("قاعدهٔ خاموش" banner).
    # Empty list when all fact data required by active rules is present.
    # Each entry describes one missing datum and how many active rules it affects.
    # Display-only: does not reflect or change which rules fired.
    data_gaps: list[DataGapDTO] = []
    # Drug-drug interactions among the patient's ACTIVE medication classes (step 36).
    # Empty list when no interacting class-pair is present. Suggestion-only;
    # sorted by severity (contraindicated → major → moderate).
    ddi: list[DdiDTO] = []


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

    # 5. Serialise data_gaps from the engine result
    gaps = [
        DataGapDTO(
            datum=g["datum"],
            label=g["label"],
            affected_rules=g["affected_rules"],
        )
        for g in result.get("data_gaps", [])
    ]

    # 6. Serialise drug-drug interactions from the engine result (step 36)
    ddi_alerts = [
        DdiDTO(
            class_a=d["class_a"],
            class_b=d["class_b"],
            severity=d["severity"],
            message_fa=d["message_fa"],
            evidence=d.get("evidence"),
            suggestion_only=d.get("suggestion_only", True),
        )
        for d in result.get("ddi", [])
    ]

    return SuggestionsResponseDTO(
        patient_link_id=link.id,
        count=result["count"],
        has_redflag=result["has_redflag"],
        framing="پیشنهاد — تأیید با پزشک",
        sections=sections,
        data_gaps=gaps,
        ddi=ddi_alerts,
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

    # Append-only event to suggestion_events (slice10).
    # INSERT always (no upsert) — accept-then-dismiss = 2 rows, preserving full history.
    # suggestion_log (above) keeps the current state/UI; this table is for analytics.
    SuggestionEvent.objects.create(
        tenant_id=tenant_id,
        patient_link_id=link.id,
        rule_code=rule_code,
        event_type=SuggestionEvent.EVENT_ACCEPTED if body.action == "accept" else SuggestionEvent.EVENT_DISMISSED,
        acted_by=actor,
        suggestion_text=log_row.suggestion_text,
        evidence_level=log_row.evidence_level,
        note=body.note,
        occurred_at=now,
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
    """
    Follow-up → visit funnel conversion metric (step-42 honest funnel).

    window_days            : eligibility window (default 30).
    generated              : all followups (informational).
    generated_eligible     : followups with due_date <= today-window_days
                             (or created_at fallback) — the true denominator.
    resolved_done          : eligible + done.
    resolved_dismissed     : eligible + dismissed.
    open_eligible          : eligible + still open.
    to_visit               : eligible + done + appointment_id IS NOT NULL.

    Rates are Optional[float] — NULL when generated_eligible < 30 (n_sufficient=False).
    contact_rate           : (done+dismissed) / eligible * 100.
    visit_rate_of_reached  : to_visit / done * 100.
    overall_conversion     : to_visit / eligible * 100  ← headline KPI.

    n_sufficient           : True when generated_eligible >= 30.
    framing                : honesty caveat (no control group).

    Invariant: generated_eligible == resolved_done + resolved_dismissed + open_eligible.
    """
    window_days:             int
    generated:               int
    generated_eligible:      int
    resolved_done:           int
    resolved_dismissed:      int
    open_eligible:           int
    to_visit:                int
    contact_rate:            Optional[float]
    visit_rate_of_reached:   Optional[float]
    overall_conversion:      Optional[float]
    n_sufficient:            bool
    framing:                 str


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
    Follow-up → visit conversion funnel metric for this tenant (step-42 honest funnel).

    Uses a 30-day eligibility window to avoid immortal-time bias:
    only followups whose due_date (or created_at) is at least 30 days ago
    are counted in the denominator. Rates are NULL when eligible < 30.

    See ConversionResponse schema for full field documentation.
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
from clinical.engagement_service import send_approved_sms as _send_approved_sms


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


# ---------------------------------------------------------------------------
# POST /engagement/approvals/{id}/send — approved → sent (Step 18, manager only)
#
# This is the ONLY endpoint that actually sends an SMS.
# The manager must first approve (pending → approved), then trigger send here.
# Quiet-hours guard is enforced (08:00-21:00 Tehran) unless override_quiet=True.
# Uses get_provider() which returns NullProvider when no API key is configured.
# In tests, provider is always NullProvider → SIMULATED, NO real network call.
# ---------------------------------------------------------------------------

class SendApprovalIn(Schema):
    """Optional body for the send endpoint."""
    override_quiet: bool = False  # bypass quiet-hours gate (e.g. urgent clinical)


class SendApprovalOut(Schema):
    """Result of an SMS send attempt."""
    ok: bool
    reason: Optional[str] = None
    provider_msgid: Optional[str] = None
    pending: bool = False
    approval_id: int
    status: str                   # final approval status after send attempt


@api.post(
    "/engagement/approvals/{approval_id}/send",
    response={
        200: SendApprovalOut,
        403: ErrorSchema,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["engagement"],
)
def send_engagement_approval(
    request,
    approval_id: int,
    body: SendApprovalIn = None,
):
    """
    Send the SMS for an approved engagement approval (manager-only, Step 18).

    The approval must already be in status='approved' (call approve first).
    This endpoint is the ONLY path where a real SMS can leave the system.

    Guardrails:
      - Patient opt-out re-checked → auto-rejects and returns ok=False reason='opt_out'.
      - Phone via AccountingPort (PatientLink has no phone — ADR-0007).
        No phone → auto-rejects, ok=False, reason='no_phone'.
      - Quiet hours (08:00-21:00 Tehran): blocks outside window unless
        body.override_quiet=True.  Approval stays 'approved' (send later).
      - get_provider(): returns NullProvider when no KAVENEGAR_API_KEY is set.
        In tests NullProvider is always used → SIMULATED, no network call.
      - On send: records dispatch (idempotency ledger) + marks approval
        status='sent' + sent_at=now().

    Returns 403 if not a manager.
    Returns 404 if approval not found for this tenant.
    Returns 409 if approval is not in status='approved' (wrong state).

    KAVENEGAR KYC NOTE: the live key returns code 430 (KYC not complete).
    No real SMS is sent until the owner finishes KYC.  Use NullProvider in tests.
    """
    guard = _assert_manager(request)
    if guard:
        return guard

    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    override_quiet = (body.override_quiet if body else False)

    # Verify the approval exists and is in the correct state before calling send
    try:
        approval_obj = _EngagementApproval.objects.get(
            id=approval_id, tenant_id=tenant_id
        )
    except _EngagementApproval.DoesNotExist:
        return 404, error_response(
            f"EngagementApproval id={approval_id} not found for this tenant.",
            "not_found",
        )

    if approval_obj.status != _EngagementApproval.STATUS_APPROVED:
        return 409, error_response(
            f"Approval id={approval_id} is '{approval_obj.status}'; "
            "only 'approved' rows can be sent. Call /approve first.",
            "invalid_transition",
        )

    result = _send_approved_sms(
        approval_id,
        tenant_id,
        decided_by=actor,
        override_quiet=override_quiet,
    )

    # Re-fetch the approval to get the final status after send_approved_sms
    try:
        approval_obj.refresh_from_db()
    except Exception:
        pass

    if result.get("reason") == "not_found":
        return 404, error_response(
            f"EngagementApproval id={approval_id} not found for this tenant.",
            "not_found",
        )

    return 200, SendApprovalOut(
        ok=result["ok"],
        reason=result.get("reason"),
        provider_msgid=result.get("provider_msgid"),
        pending=result.get("pending", False),
        approval_id=approval_id,
        status=approval_obj.status,
    )


# ===========================================================================
# Screening timeline (Step 37 — cluster I)
#
# GET /patients/{uuid}/screening-timeline
#
# Read-only, suggestion-only.  Returns the FULL periodic screening timeline
# for one patient — all relevant items with last-done / next-due / status,
# regardless of whether they are currently due.
#
# Design: Plan B (catalog-driven) because the underlying clinical rules use
# condition-only triggers (e.g. {"all": [DM]}) with NO due-gating in the
# trigger_json. due_clinical_events() applies a due filter, so items done
# recently would be invisible in a rule-driven approach.  Plan B iterates
# ITEM_VITALS ∪ ITEM_FLAGS filtered by the patient's active condition codes.
#
# No side effects: no followup_tasks created, no audit rows, no writes.
# ===========================================================================

from clinical.followup_engine import screening_timeline as _screening_timeline


class ScreeningItemDTO(Schema):
    """
    One periodic screening item in the patient's timeline.

    All dates are ISO YYYY-MM-DD strings (frontend converts to Jalali as needed).
    suggestion_only is always True — the physician decides; the app only reminds.
    """
    item_key: str
    label_fa: str
    last_done_at: Optional[str] = None
    next_due_at: Optional[str] = None
    status: str                       # never_done | overdue | due_soon | ok
    interval_months: int
    condition_code: Optional[str] = None
    suggestion_only: bool = True


class ScreeningTimelineResponseDTO(Schema):
    patient_link_id: int
    framing: str
    items: list[ScreeningItemDTO]


@api.get(
    "/patients/{patient_uuid}/screening-timeline",
    response=ScreeningTimelineResponseDTO,
    auth=_jwt_auth,
    tags=["clinical"],
)
def get_screening_timeline(request, patient_uuid: uuid_module.UUID):
    """
    Full periodic screening timeline for one enrolled patient.

    Returns ALL relevant periodic screening items — not just those currently
    due — with last-done date, next-due date, and status.

    Status values:
      never_done  — item was never recorded for this patient
      overdue     — next due date has passed (today > next_due)
      due_soon    — next due date within 30 days (0 <= days_until <= 30)
      ok          — done recently, within the recall window

    Items with interval_months=0 (every-visit) and interval_months=None
    (one-time / vaccine) are excluded.

    Output is SUGGESTION-ONLY: every item carries suggestion_only=True and
    the response carries framing="یادآوریِ غربالگری — تأیید با پزشک".

    Requires JWT. Tenant-scoped: 404 if patient has no enrollment for this tenant.
    Read-only: no side effects, no tasks created.
    """
    tenant_id = request.tenant_id

    # 1. Resolve uuid → accounting patient (read-only Port).
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    # 2. Find clinical enrollment for THIS tenant.
    try:
        link = PatientLink.objects.get(
            tenant_id=tenant_id,
            patient_id=demo.id,
        )
    except PatientLink.DoesNotExist:
        raise Http404(
            f"Patient uuid={patient_uuid} has no enrollment for this tenant."
        )

    # 3. Build the timeline (pure computation, no writes).
    items_raw = _screening_timeline(link.id, tenant_id)

    items = [
        ScreeningItemDTO(
            item_key=it["item_key"],
            label_fa=it["label_fa"],
            last_done_at=it["last_done_at"],
            next_due_at=it["next_due_at"],
            status=it["status"],
            interval_months=it["interval_months"],
            condition_code=it["condition_code"],
            suggestion_only=it["suggestion_only"],
        )
        for it in items_raw
    ]

    return ScreeningTimelineResponseDTO(
        patient_link_id=link.id,
        framing="یادآوریِ غربالگری — تأیید با پزشک",
        items=items,
    )


# ===========================================================================
# Medication Effect (Step 38 — cluster I)
#
# GET /patients/{uuid}/medications/{med_id}/effect
#
# Read-only, suggestion-only. محاسبهٔ اثرِ دارو با مقایسهٔ پیش/پسِ شروع.
# اصلِ مقدس: هرگز عددِ ساختگی — data_insufficient با reason اگر ناکافی.
# ===========================================================================

from clinical.medication_effect_service import compute_medication_effect as _compute_med_effect
from clinical.models import PatientMedication as _PatientMedication


class MedEffectWindowDTO(Schema):
    """بازهٔ زمانیِ pre یا post."""
    from_date: Optional[str] = None   # alias: "from" کلمهٔ رزرو Python است
    to_date: Optional[str] = None

    class Config:
        populate_by_name = True


class MedicationEffectDTO(Schema):
    """
    پاسخِ GET /patients/{uuid}/medications/{id}/effect.

    status='ok' : محاسبه انجام شد — pre_value/post_value/delta/direction_of_change حاضرند.
    status='data_insufficient': دادهٔ ناکافی — pre_value/post_value/delta همه null.

    suggestion_only همیشه True.
    caveat در حالتِ ok همیشه حاضر (مطالعهٔ تک‌گروهی disclaimer).
    """
    status: str                               # 'ok' | 'data_insufficient'
    reason: Optional[str] = None             # دلیلِ ناکافی بودن
    suggestion_only: bool = True             # همیشه True
    drug_name: str
    drug_class: Optional[str] = None
    indicator: Optional[str] = None          # label فارسی
    indicator_key: Optional[str] = None      # کلیدِ فنی (hba1c / ldl / ...)
    unit: Optional[str] = None
    pre_value: Optional[float] = None
    post_value: Optional[float] = None
    delta: Optional[float] = None
    direction_of_change: Optional[str] = None  # 'improved' | 'worsened' | 'unchanged'
    n_pre: int = 0
    n_post: int = 0
    pre_window: Optional[dict] = None
    post_window: Optional[dict] = None
    start_date: Optional[str] = None        # ISO date — UI formats Jalali client-side
    caveat: Optional[str] = None
    meaningful_threshold: Optional[float] = None


@api.get(
    "/patients/{patient_uuid}/medications/{med_id}/effect",
    response={200: MedicationEffectDTO, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["clinical"],
)
def get_medication_effect(
    request,
    patient_uuid: uuid_module.UUID,
    med_id: int,
):
    """
    ردیابیِ اثرِ دارو: مقایسهٔ میانگینِ اندیکاتورِ مرتبط در پنجرهٔ pre و post.

    اصلِ مقدس: هرگز عددِ ساختگی — دادهٔ ناکافی ⇒ status='data_insufficient' + reason.

    حالت‌های data_insufficient:
      - no_start_date         : start_date دارو ثبت نشده
      - no_indicator_for_class: drug_class این دارو indicator قابل‌ردیابی ندارد
                               (aspirin / other / loop_diuretic)
      - post_window_not_elapsed: زمانِ کافی از شروعِ دارو نگذشته (پنجرهٔ post هنوز باز نشده)
      - no_pre                : هیچ اندازه‌گیریِ پیش از شروع وجود ندارد
      - no_post               : هیچ اندازه‌گیریِ پس از شروع در پنجره وجود ندارد

    suggestion_only=True در **هر** پاسخ — «پیشنهاد، تأیید با پزشک».
    فقط read-only: هیچ نوشتنی ندارد.
    Tenant-scoped: 404 اگر بیمار یا دارو در این tenant نباشد.
    """
    tenant_id = request.tenant_id

    # ── ۱. resolve patient ───────────────────────────────────────────────────
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        raise Http404(f"Patient with uuid={patient_uuid} not found.")

    try:
        link = PatientLink.objects.get(tenant_id=tenant_id, patient_id=demo.id)
    except PatientLink.DoesNotExist:
        raise Http404(
            f"Patient uuid={patient_uuid} has no enrollment for this tenant."
        )

    # ── ۲. resolve medication ────────────────────────────────────────────────
    try:
        med = _PatientMedication.objects.get(
            id=med_id,
            patient_link_id=link.id,
            tenant_id=tenant_id,
        )
    except _PatientMedication.DoesNotExist:
        raise Http404(
            f"Medication id={med_id} not found for this patient/tenant."
        )

    # ── ۳. compute effect (read-only, no writes) ─────────────────────────────
    result = _compute_med_effect(med=med, tenant_id=tenant_id)

    return 200, MedicationEffectDTO(
        status=result["status"],
        reason=result["reason"],
        suggestion_only=result["suggestion_only"],
        drug_name=result["drug_name"],
        drug_class=result["drug_class"],
        indicator=result["indicator"],
        indicator_key=result["indicator_key"],
        unit=result["unit"],
        pre_value=result["pre_value"],
        post_value=result["post_value"],
        delta=result["delta"],
        direction_of_change=result["direction_of_change"],
        n_pre=result["n_pre"],
        n_post=result["n_post"],
        pre_window=result["pre_window"],
        post_window=result["post_window"],
        start_date=result["start_date"],
        caveat=result["caveat"],
        meaningful_threshold=result["meaningful_threshold"],
    )


# ===========================================================================
# Population Threshold Management (Step 39)
# GET /manager/population-thresholds — list draft overrides for review/approval
# Manager-only: requires JWT with role='manager'.
# ===========================================================================

from clinical.models import PopulationThreshold as _PopulationThreshold


class PopulationThresholdDTO(Schema):
    """
    One population-specific threshold override row (read-only).

    approval_status is always shown so the UI can distinguish draft from approved.
    framing: fixed label indicating this is a draft awaiting physician review.
    """
    id: int
    tenant_id: int
    indicator_key: str
    population_key: str
    bound: str                              # 'high' | 'low'
    warn: Optional[float] = None
    danger: Optional[float] = None
    target: Optional[float] = None
    goal_low: Optional[float] = None
    goal_high: Optional[float] = None
    rationale: Optional[str] = None
    evidence: Optional[str] = None
    approval_status: str                    # 'draft' | 'approved'
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class PopulationThresholdListDTO(Schema):
    """Response for GET /manager/population-thresholds."""
    items: list[PopulationThresholdDTO]
    total: int
    # Framing label for the UI — makes the draft/review status explicit
    framing: str


@api.get(
    "/manager/population-thresholds",
    response={200: PopulationThresholdListDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def list_population_thresholds(request):
    """
    لیستِ override‌های آستانهٔ زیرجمعیتی برای بازبینی و تأییدِ پزشک.

    فقط مدیر (manager) دسترسی دارد.
    همهٔ ردیف‌ها (draft و approved) برگردانده می‌شوند تا پزشک وضعیت را ببیند.

    framing="پیش‌نویس — نیازمندِ تأییدِ پزشک" همیشه در response است.

    اکشنِ approve در قدمِ بعد پیاده می‌شود.
    """
    # Manager-only gate — strict role check
    user_role = getattr(request.auth, "role", "staff")
    if user_role != "manager":
        return 403, error_response(
            "دسترسی محدود است. فقط مدیر می‌تواند این صفحه را ببیند.",
            "forbidden",
        )

    tenant_id = request.tenant_id

    qs = _PopulationThreshold.objects.filter(
        tenant_id=tenant_id,
    ).order_by("population_key", "indicator_key", "bound")

    rows = list(qs)
    items = [
        PopulationThresholdDTO(
            id=row.id,
            tenant_id=row.tenant_id,
            indicator_key=row.indicator_key,
            population_key=row.population_key,
            bound=row.bound,
            warn=row.warn,
            danger=row.danger,
            target=row.target,
            goal_low=row.goal_low,
            goal_high=row.goal_high,
            rationale=row.rationale,
            evidence=row.evidence,
            approval_status=row.approval_status,
            approved_by=row.approved_by,
            approved_at=row.approved_at,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return 200, PopulationThresholdListDTO(
        items=items,
        total=len(items),
        framing="پیش‌نویس — نیازمندِ تأییدِ پزشک",
    )


# ===========================================================================
# Suggestion Stats (Step 41) — GET /manager/suggestion-stats
# Manager-only: requires JWT with role='manager'.
# ===========================================================================

_MIN_N_FOR_RATE = 5
_MIN_IMPRESSIONS_FOR_RATE = 10


class SuggestionRuleStatsDTO(Schema):
    """
    Stats per rule_code — all rate fields are Optional (NULL when n < min_n).

    Framing principle: rates measure physician behaviour, not rule quality.
    Correlational, not causal (no holdout).
    """
    rule_code: str
    n_accepted: int
    n_dismissed: int
    n_pending: int
    n_acted: int                                    # = accepted + dismissed
    n_fired_patient_days: int                       # count of fired_daily events
    acceptance_rate_of_acted: Optional[float]       # NULL when n_acted < min_n
    rate_reliable: bool
    impression_acceptance_rate: Optional[float]     # NULL when n_fired_patient_days < 10
    impression_rate_reliable: bool
    last_action_at: Optional[datetime]


class SuggestionStatsResponseDTO(Schema):
    """
    Response for GET /manager/suggestion-stats.

    framing is mandatory and must be present in every response:
    it makes explicit that these numbers reflect physician choices,
    not a measurement of rule quality, and that correlation is not causation.
    """
    generated_at: datetime
    min_n_for_rate: int
    framing: str
    rules: list[SuggestionRuleStatsDTO]


@api.get(
    "/manager/suggestion-stats",
    response={200: SuggestionStatsResponseDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def suggestion_stats(request):
    """
    آمارِ پیشنهادهایِ بالینی به تفکیکِ قاعده — فقط مدیر.

    فیلدهای rate (acceptance_rate_of_acted، impression_acceptance_rate) در صورتی که
    تعدادِ اقدامات/impressions کمتر از حدِ نصاب باشد NULL برگردانده می‌شود (نه صفر).
    این اصلِ «NULL نه صفر هنگامِ داده‌ی ناکافی» را اجرا می‌کند.

    framing در هر پاسخ اجباری است:
      «نرخ‌ها از میانِ اقداماتِ پزشک — نه معیارِ کیفیتِ قاعده؛
       پیش از holdout همبستگی است نه اثر»

    منطقِ آمار:
      - suggestion_log: منبعِ n_accepted / n_dismissed / n_pending / last_action_at
      - suggestion_events WHERE event_type='fired_daily': منبعِ n_fired_patient_days
      - acceptance_rate_of_acted = accepted / (accepted+dismissed)
        فقط وقتی n_acted >= 5؛ در غیرِ این صورت NULL.
      - impression_acceptance_rate = accepted / n_fired_patient_days
        فقط وقتی n_fired_patient_days >= 10؛ در غیرِ این صورت NULL.

    Manager-only: staff → 403.
    """
    user_role = getattr(request.auth, "role", "staff")
    if user_role != "manager":
        return 403, error_response(
            "دسترسی محدود است. فقط مدیر می‌تواند این صفحه را ببیند.",
            "forbidden",
        )

    tenant_id = request.tenant_id

    # ── ۱) جمعِ اقدامات از suggestion_log per rule_code ─────────────────────
    from django.db.models import (
        Count, Q, Max,
        Case, When, IntegerField, Sum,
    )

    log_qs = (
        SuggestionLog.objects
        .filter(tenant_id=tenant_id)
        .values("rule_code")
        .annotate(
            n_accepted=Count(Case(
                When(status="accepted", then=1),
                output_field=IntegerField(),
            )),
            n_dismissed=Count(Case(
                When(status="dismissed", then=1),
                output_field=IntegerField(),
            )),
            n_pending=Count(Case(
                When(status="pending", then=1),
                output_field=IntegerField(),
            )),
            last_action_at=Max("acted_at"),
        )
    )
    log_map: dict[str, dict] = {row["rule_code"]: row for row in log_qs}

    # ── ۲) شمارِ fired_daily از suggestion_events per rule_code ─────────────
    event_qs = (
        SuggestionEvent.objects
        .filter(tenant_id=tenant_id, event_type=SuggestionEvent.EVENT_FIRED_DAILY)
        .values("rule_code")
        .annotate(n_fired=Count("id"))
    )
    fired_map: dict[str, int] = {row["rule_code"]: row["n_fired"] for row in event_qs}

    # ── ۳) اتحادِ همهٔ rule_codeها (log + events) ───────────────────────────
    all_codes = set(log_map.keys()) | set(fired_map.keys())

    # ── ۴) ساختنِ ردیف‌های آمار ─────────────────────────────────────────────
    now = timezone.now()
    rule_stats: list[SuggestionRuleStatsDTO] = []

    for code in sorted(all_codes):
        log_row = log_map.get(code, {})
        n_accepted = log_row.get("n_accepted", 0)
        n_dismissed = log_row.get("n_dismissed", 0)
        n_pending = log_row.get("n_pending", 0)
        n_acted = n_accepted + n_dismissed
        n_fired = fired_map.get(code, 0)
        last_action_at = log_row.get("last_action_at")

        # acceptance_rate_of_acted: NULL وقتی n_acted < حدِ نصاب
        if n_acted >= _MIN_N_FOR_RATE:
            acceptance_rate_of_acted: Optional[float] = (
                n_accepted / n_acted if n_acted > 0 else None
            )
            rate_reliable = True
        else:
            acceptance_rate_of_acted = None
            rate_reliable = False

        # impression_acceptance_rate: NULL وقتی n_fired < حدِ نصاب
        if n_fired >= _MIN_IMPRESSIONS_FOR_RATE and n_fired > 0:
            impression_acceptance_rate: Optional[float] = n_accepted / n_fired
            impression_rate_reliable = True
        else:
            impression_acceptance_rate = None
            impression_rate_reliable = False

        rule_stats.append(
            SuggestionRuleStatsDTO(
                rule_code=code,
                n_accepted=n_accepted,
                n_dismissed=n_dismissed,
                n_pending=n_pending,
                n_acted=n_acted,
                n_fired_patient_days=n_fired,
                acceptance_rate_of_acted=acceptance_rate_of_acted,
                rate_reliable=rate_reliable,
                impression_acceptance_rate=impression_acceptance_rate,
                impression_rate_reliable=impression_rate_reliable,
                last_action_at=last_action_at,
            )
        )

    return 200, SuggestionStatsResponseDTO(
        generated_at=now,
        min_n_for_rate=_MIN_N_FOR_RATE,
        framing=(
            "نرخ‌ها از میانِ اقداماتِ پزشک — نه معیارِ کیفیتِ قاعده؛ "
            "پیش از holdout همبستگی است نه اثر"
        ),
        rules=rule_stats,
    )


# ===========================================================================
# Patient Card Token — خوشهٔ J، قدم ۴۴
#
# سطحِ PHIِ رو-به-بیمار، امنیتی‌بحرانی.
#
# معماریِ امنیتی (قفل‌شده با security-privacy-advisor):
#   - endpoint عمومی GET /card/{token}: بدونِ JWT، zero-write، rate-limit in-process.
#     card_resolve_token() SECURITY DEFINER → GUC → projection → response.
#   - staff endpointها (issue/revoke): JWT + GUC → RLS.
#
# گِیتِ LAN-vs-internet (ثبت‌شده، internet غیرفعال):
#   مواجهه با اینترنت نیازِ TLS + rate-limitِ توزیع‌شده + TTLِ کوتاه‌تر + آنتروپیِ
#   بیشتر دارد. مسیرِ SMS-link نساخته‌ایم (KYC بلاک). فعلاً LAN-only.
# ===========================================================================

from clinical.card_token_service import (
    issue as _card_issue,
    revoke as _card_revoke,
    resolve_token as _card_resolve_token,
    active_for_patient as _card_active_for_patient,
)
from clinical.card_projection_service import card_for_patient as _card_for_patient
from platform_core.tenant_context import set_tenant_guc as _set_tenant_guc

# ---------------------------------------------------------------------------
# Rate-limit in-process — SECU-13 (per-process، مثلِ specialist_clinic).
# برای deployment چند-instance، Redis/DB-backed لازم است.
# ---------------------------------------------------------------------------
import threading as _threading
import time as _time

_rl_lock = _threading.Lock()
_rl_hits: dict[str, list[float]] = {}

_CARD_RATE_LIMIT = 30   # درخواست
_CARD_RATE_WINDOW = 60  # ثانیه


def _card_allow(key: str) -> bool:
    """Sliding window rate-limiter (in-process). Returns True if request is allowed."""
    t = _time.monotonic()
    cutoff = t - _CARD_RATE_WINDOW
    with _rl_lock:
        q = _rl_hits.setdefault(key, [])
        while q and q[0] < cutoff:
            q.pop(0)
        if len(q) >= _CARD_RATE_LIMIT:
            return False
        q.append(t)
        return True


# ---------------------------------------------------------------------------
# Schemas — card endpoints
# ---------------------------------------------------------------------------

class VitalCardDTO(Schema):
    """یک ویتال روی کارتِ عمومی (minimum-necessary)."""
    key: str
    label: str
    value: float
    unit: str
    status: str  # 'ok' | 'warn' | 'danger'


class PublicCardResponse(Schema):
    """
    قرارداد payload کارتِ عمومیِ بیمار (قفل‌شده — frontend موازی همین را مصرف می‌کند).

    هرگز: national_id، تماسِ بیمار، نامِ دارو/دوز، تشخیص/بیماری،
    HbA1cِ خام، یادداشتِ بالینی، درآمد/کیف‌پول.
    """
    first_name: str
    clinic_name: Optional[str]
    vitals: list[VitalCardDTO]
    next_appointment: Optional[str]   # ISO date (YYYY-MM-DD) یا None
    framing: str                       # جملهٔ انگیزشیِ ساده
    # یادآورِ خنثیِ غربالگری (قدم ۴۸): رشتهٔ نرم یا None.
    # هرگز per-item/count/label/تاریخ — فقط پیامِ count-capped و بدونِ تشخیص.
    reminder_message: Optional[str] = None


class CardTokenOut(Schema):
    """پاسخِ issue token برای staff."""
    token: str
    expires_at: datetime
    card_url: str   # URL مطلق نیست — فقط path (LAN-only)


# ---------------------------------------------------------------------------
# ۱) GET /card/{token} — endpoint عمومی (بدونِ JWT، zero-write)
#
#    جریانِ resolve→GUC→projection:
#      ۱) card_resolve_token(token) → {patient_link_id, tenant_id} یا None.
#         (SECURITY DEFINER: RLS را برای این lookup عبور می‌دهد.)
#      ۲) اگر None → 404 (generic: دلیل فاش نمی‌شود).
#      ۳) set_tenant_guc(tenant_id) → GUC ست می‌شود.
#      ۴) card_for_patient(patient_link_id, tenant_id) → projection (GUC-scoped).
#      ۵) Return PublicCardResponse.
#
#    zero-write: هیچ INSERT/UPDATE/DELETE در این مسیر وجود ندارد.
#    rate-limit: ≤ 30 درخواست/۶۰ ثانیه per IP (in-process).
# ---------------------------------------------------------------------------

@api.get(
    "/card/{token}",
    response={200: PublicCardResponse, 404: ErrorSchema, 429: ErrorSchema},
    auth=None,
    tags=["patient-card"],
    summary="کارتِ عمومیِ بیمار (بدونِ JWT)",
)
def get_public_card(request, token: str):
    """
    سطحِ عمومیِ رو-به-بیمار: آخرین ویتال‌ها + نوبتِ بعدی.
    بدونِ JWT. rate-limit: ۳۰ req/min per IP (in-process).

    zero-write: این endpoint هیچ چیزی نمی‌نویسد.

    LAN-vs-internet note:
      این endpoint فعلاً LAN-only (QR/tablet در مطب) است.
      internet exposure نیازِ TLS + rate-limitِ توزیع‌شده دارد (هنوز فعال نیست).
    """
    client_ip = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR", "?")
    )
    if not _card_allow(f"card:{client_ip}"):
        return 429, error_response("تعدادِ درخواست بیش از حد مجاز است", "rate_limited")

    resolved = _card_resolve_token(token)
    if resolved is None:
        # generic 404: دلیل فاش نمی‌شود (ناشناخته/منقضی/revoked)
        return 404, error_response("کارت یافت نشد", "not_found")

    patient_link_id = resolved["patient_link_id"]
    tenant_id = resolved["tenant_id"]

    # GUC را ست کن تا دادهٔ بالینی تحتِ RLS (tenant-scoped) خوانده شود
    _set_tenant_guc(tenant_id)

    card_data = _card_for_patient(patient_link_id, tenant_id)
    if card_data is None:
        return 404, error_response("کارت یافت نشد", "not_found")

    return 200, PublicCardResponse(
        first_name=card_data["first_name"],
        clinic_name=card_data["clinic_name"],
        vitals=[VitalCardDTO(**v) for v in card_data["vitals"]],
        next_appointment=card_data["next_appointment"],
        framing=card_data["framing"],
        reminder_message=card_data.get("reminder_message"),
    )


# ---------------------------------------------------------------------------
# ۲) POST /patients/{uuid}/card-token — issue token (staff، JWT)
# ---------------------------------------------------------------------------

@api.post(
    "/patients/{patient_uuid}/card-token",
    response={201: CardTokenOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-card"],
    summary="صدورِ توکنِ کارتِ بیمار (staff)",
)
def issue_card_token(request, patient_uuid: uuid_module.UUID):
    """
    صدورِ توکنِ جدیدِ کارتِ عمومی برای بیمار (staff-only).
    one-active-at-a-time: توکنِ قبلی revoke می‌شود.
    TTL پیش‌فرض: ۸ ساعت (LAN-only).

    Returns: {token, expires_at, card_url}
    """
    tenant_id = request.tenant_id
    user = request.auth

    # پیدا کردنِ patient_link از UUID بیمار
    demo = get_patient_by_uuid(patient_uuid)
    if demo is None:
        return 404, error_response("بیمار یافت نشد", "not_found")

    from clinical.models import PatientLink
    try:
        link = PatientLink.objects.get(
            tenant_id=tenant_id,
            patient_id=demo.id,
        )
    except PatientLink.DoesNotExist:
        return 404, error_response("بیمار در کلینیک ثبت‌نام نشده", "not_found")

    token_str, expires_at = _card_issue(
        patient_link_id=link.id,
        tenant_id=tenant_id,
        issued_by=user.username,
    )

    log_activity(
        tenant_id=tenant_id,
        user_id=user.id,
        username=user.username,
        action_type="card_token_issued",
        action_category="patient_card",
        description=f"card token issued for patient_link_id={link.id}",
        patient_link_id=link.id,
    )

    return 201, CardTokenOut(
        token=token_str,
        expires_at=expires_at,
        card_url=f"/card/{token_str}",
    )


# ---------------------------------------------------------------------------
# ۳) POST /patients/{uuid}/card-token/revoke — revoke token (staff، JWT)
# ---------------------------------------------------------------------------

class CardRevokeRequest(Schema):
    token_id: int


@api.post(
    "/patients/{patient_uuid}/card-token/revoke",
    response={200: dict, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["patient-card"],
    summary="رevokeِ توکنِ کارتِ بیمار (staff)",
)
def revoke_card_token(request, patient_uuid: uuid_module.UUID, body: CardRevokeRequest):
    """
    Revoke یک توکنِ فعال (staff-only).
    GUC-scoped: RLS به tenant محدود می‌کند — cross-tenant revoke ممکن نیست.
    """
    tenant_id = request.tenant_id
    user = request.auth

    ok = _card_revoke(token_id=body.token_id, tenant_id=tenant_id)
    if not ok:
        return 404, error_response("توکن یافت نشد یا قبلاً revoke شده", "not_found")

    log_activity(
        tenant_id=tenant_id,
        user_id=user.id,
        username=user.username,
        action_type="card_token_revoked",
        action_category="patient_card",
        description=f"card token {body.token_id} revoked",
    )

    return 200, {"status": "revoked"}


# ===========================================================================
# Patient self-report — slice13 / step 45
#
# اصلِ مقدس (security-privacy-advisor):
#   دادهٔ self-reportِ تأییدنشده هرگز وارد موتور/کارت/پیشنهاد نمی‌شود
#   تا پزشک verify کند (قدم ۴۷ — موکول).
#
# Endpoints:
#   POST /patients/{uuid}/report-token  — staff issue (JWT required)
#   POST /patient-report/{token}        — public submit (no JWT, one-time token)
# ===========================================================================

from clinical.report_token_service import (
    issue as _report_issue,
    resolve_token as _report_resolve,
    mark_used as _report_mark_used,
)
from platform_core.tenant_context import set_tenant_guc as _set_tenant_guc

# ── مقادیرِ مجاز و بازه‌های فیزیولوژیکِ self-report ─────────────────────────
# Whitelist محدود: فقط شاخص‌هایی که بیمار می‌تواند در خانه اندازه بگیرد.
_REPORT_ALLOWED_TYPES: dict[str, tuple[float, float]] = {
    "fbs":          (20.0,  800.0),   # mg/dL — قند ناشتا
    "bp_systolic":  (50.0,  300.0),   # mmHg  — فشارِ سیستولیک
    "bp_diastolic": (20.0,  200.0),   # mmHg  — فشارِ دیاستولیک
}
_REPORT_UNIT: dict[str, str] = {
    "fbs":          "mg/dL",
    "bp_systolic":  "mmHg",
    "bp_diastolic": "mmHg",
}

# Rate-limit ساده in-process (per-process — برای multi-instance باید Redis شود)
import threading as _threading
import time as _time

_rate_lock = _threading.Lock()
_rate_store: dict[str, float] = {}   # token_str → last_attempt timestamp
_RATE_WINDOW_SEC = 60                # یک درخواست per token per minute


def _check_rate_limit(token_str: str) -> bool:
    """Returns True if within rate limit (allow). False = too many requests."""
    now = _time.monotonic()
    with _rate_lock:
        last = _rate_store.get(token_str)
        if last is not None and (now - last) < _RATE_WINDOW_SEC:
            return False
        _rate_store[token_str] = now
    return True


# ---------------------------------------------------------------------------
# Schemas — self-report
# ---------------------------------------------------------------------------

class ReportTokenOut(Schema):
    """توکنِ self-report صادرشده برای بیمار."""
    token: str
    expires_at: datetime
    report_url: str


class SelfReportReadingIn(Schema):
    """یک اندازه‌گیری در batch."""
    type: str
    value: float

    class Config:
        extra = "forbid"   # کلیدِ اضافی reject می‌شود


class SelfReportIn(Schema):
    """
    بدنهٔ درخواستِ self-report بیمار.

    دو حالتِ پشتیبانی‌شده:
    ۱) تکی (سازگار با قبل): {type, value}
    ۲) batch: {readings: [{type, value}, ...]} — یک تا N خواندن.
    اگر readings موجود باشد، حالتِ batch اعمال می‌شود (type/value نادیده).
    """
    # حالتِ تکی (سازگار با قبل)
    type: Optional[str] = None
    value: Optional[float] = None
    # حالتِ batch
    readings: Optional[list[SelfReportReadingIn]] = None

    class Config:
        extra = "forbid"   # کلیدِ اضافی reject می‌شود


class SelfReportReadingOut(Schema):
    """یک اندازه‌گیری در پاسخِ batch."""
    type: str
    value: float


class SelfReportOut(Schema):
    """
    پاسخِ موفقِ self-report.

    در حالتِ تکی: type/value حاضرند و accepted=[{type, value}].
    در حالتِ batch: accepted لیستِ همهٔ اندازه‌گیری‌های ثبت‌شده، count=تعداد.
    سازگار با هر دو حالت.
    """
    status: str = "ok"
    # حالتِ تکی (backward-compat)
    type: Optional[str] = None
    value: Optional[float] = None
    # batch (همیشه حاضر — در حالتِ تکی یک آیتم دارد)
    accepted: list[SelfReportReadingOut] = []
    count: int = 1
    message: str = "داده دریافت شد — پزشک آن را بررسی خواهد کرد"


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/report-token — صدورِ توکنِ self-report (staff، JWT)
# ---------------------------------------------------------------------------

@api.post(
    "/patients/{patient_uuid}/report-token",
    response={201: ReportTokenOut, 404: ErrorSchema},
    auth=_jwt_auth,
    tags=["self-report"],
    summary="صدورِ توکنِ self-report برای بیمار (staff)",
)
def issue_report_token(request, patient_uuid: uuid_module.UUID):
    """
    صدورِ توکنِ یک‌بارمصرفِ self-report برای یک بیمارِ ثبت‌نام‌شده.

    staff (manager یا staff role) می‌تواند این توکن را صادر و لینکِ آن را
    به بیمار بدهد (SMS / QR).
    توکن یک‌بارمصرف است و بعد از TTL (۲۴ ساعت) منقضی می‌شود.
    بیمار از لینک POST /patient-report/{token} استفاده می‌کند تا داده ثبت کند.

    scope جداگانه از card-token: این توکن فقط برای write path (self-report)
    مجاز است؛ /card/{token} (read path) آن را نمی‌پذیرد.

    داده‌ای که از این مسیر می‌آید با verified=FALSE ذخیره می‌شود و هرگز
    وارد موتور/کارت/پیشنهاد نمی‌شود تا پزشک تأیید کند (قدم ۴۷).

    Requires JWT. Tenant-scoped: 404 if patient has no enrollment for this tenant.
    """
    tenant_id = request.tenant_id
    user = request.auth

    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    token_str, expires_at = _report_issue(
        patient_link_id=link.id,
        tenant_id=tenant_id,
        issued_by=user.username,
    )

    log_activity(
        tenant_id=tenant_id,
        user_id=user.id,
        username=user.username,
        action_type="report_token_issued",
        action_category="self_report",
        description=f"report token issued for patient_link_id={link.id}",
        patient_link_id=link.id,
    )

    return 201, ReportTokenOut(
        token=token_str,
        expires_at=expires_at,
        report_url=f"/patient-report/{token_str}",
    )


# ---------------------------------------------------------------------------
# POST /patient-report/{token} — ثبتِ self-report بیمار (بدونِ JWT)
# ---------------------------------------------------------------------------

@api.post(
    "/patient-report/{token}",
    response={
        200: SelfReportOut,
        404: ErrorSchema,   # token نامعتبر/ناشناخته
        409: ErrorSchema,   # token قبلاً استفاده‌شده
        410: ErrorSchema,   # token منقضی
        422: ErrorSchema,   # مقدار خارج از بازه یا type غیرمجاز
        429: ErrorSchema,   # rate limit
    },
    auth=None,
    tags=["self-report"],
    summary="ثبتِ self-report بیمار (بدونِ JWT، یک‌بارمصرف)",
)
def submit_patient_report(request, token: str, body: SelfReportIn):
    """
    endpoint عمومیِ ثبتِ self-report بیمار.

    امنیت (security-privacy-advisor قفل کرد):
      ۱) بدونِ JWT — توکنِ opaque (one-time) احراز هویت می‌کند.
      ۲) report_resolve_token() SECURITY DEFINER برای lookup بدونِ GUC.
      ۳) type در whitelist محدود (fbs | bp_systolic | bp_diastolic).
      ۴) value در بازهٔ فیزیولوژیک — خارج از بازه → ۴۲۲.
      ۵) هیچ PHI در URL / بدنهٔ پاسخ.
      ۶) یک‌بارمصرف: بعد از استفادهٔ موفق → ۴۰۴ برای درخواست‌های بعدی.
      ۷) داده با verified=FALSE, source='patient_self' ذخیره می‌شود.
      ۸) rate-limit: یک درخواست per token per minute.

    دو حالتِ بدنه:
      تکی (سازگار با قبل): {type, value}
      batch: {readings: [{type, value}, ...]} — یک تا N اندازه‌گیری.

    منطقِ batch:
      - all-or-nothing: اگر هر reading نامعتبر باشد → ۴۲۲، هیچ insert و هیچ mark-used.
      - batch خالی → ۴۲۲.
      - همه reading معتبر: همه insert شوند → توکن یک‌بار mark used شود.

    جریانِ کامل:
      ۱) resolve token (SECURITY DEFINER — no GUC)
      ۲) normalize به لیستِ readings
      ۳) validate همهٔ readings (all-or-nothing قبل از insert)
      ۴) rate-limit check
      ۵) set_tenant_guc(tenant_id)
      ۶) INSERT همه readings (verified=FALSE, source='patient_self')
      ۷) mark_used یک‌بار
      ۸) return 200

    Physician verify (step 47, deferred):
      verified=FALSE ردیف تا زمانِ تأییدِ پزشک نامرئی است.
    """
    # 1) Resolve token (SECURITY DEFINER — no GUC needed)
    # Rate-limit is applied AFTER resolve so that:
    #   (a) expired/used/unknown tokens return 404 without consuming rate-limit.
    #   (b) validation failures (422) return 422 without consuming rate-limit,
    #       so the user can retry with a corrected value (توکن مصرف نمی‌شود).
    resolved = _report_resolve(token)

    if resolved is None:
        return _report_distinguish_error(token)

    patient_link_id = resolved["patient_link_id"]
    tenant_id = resolved["tenant_id"]

    # 2) Normalize body به لیستِ (type, value) — سازگار با حالتِ تکی و batch
    if body.readings is not None:
        # حالتِ batch
        raw_readings = [(r.type, r.value) for r in body.readings]
    elif body.type is not None and body.value is not None:
        # حالتِ تکی (سازگار با قبل)
        raw_readings = [(body.type, body.value)]
    else:
        return 422, error_response(
            "باید 'readings' (batch) یا 'type'+'value' (تکی) ارسال شود",
            "validation_error",
        )

    # 3) batch خالی → ۴۲۲ (قبل از insert، توکن مصرف نمی‌شود)
    if len(raw_readings) == 0:
        return 422, error_response(
            "readings نمی‌تواند خالی باشد (حداقل یک اندازه‌گیری لازم است)",
            "validation_error",
        )

    # 4) Validate همهٔ readings — all-or-nothing: اگر هر کدام نامعتبر باشد →
    #    ۴۲۲ بدونِ هیچ insert و بدونِ mark-used (توکن هنوز قابلِ استفاده است).
    _MAX_READINGS = 10
    if len(raw_readings) > _MAX_READINGS:
        return 422, error_response(
            f"حداکثر {_MAX_READINGS} اندازه‌گیری در یک ارسال مجاز است",
            "validation_error",
        )

    validated: list[tuple[str, float]] = []
    for vtype, vvalue in raw_readings:
        if vtype not in _REPORT_ALLOWED_TYPES:
            allowed = ", ".join(_REPORT_ALLOWED_TYPES.keys())
            return 422, error_response(
                f"نوعِ '{vtype}' مجاز نیست. مقادیرِ مجاز: {allowed}",
                "validation_error",
            )
        lo, hi = _REPORT_ALLOWED_TYPES[vtype]
        if not (lo <= vvalue <= hi):
            return 422, error_response(
                f"مقدارِ {vvalue} برای '{vtype}' خارج از بازهٔ مجاز ({lo}–{hi}) است",
                "validation_error",
            )
        validated.append((vtype, vvalue))

    # 5) Rate-limit — applied after validation (422s don't consume rate-limit slot)
    if not _check_rate_limit(token):
        return 429, error_response("تعداد درخواست‌ها بیش از حد مجاز است", "rate_limit")

    # 6) Set GUC → RLS enforced for all subsequent queries in this connection
    _set_tenant_guc(tenant_id)

    # 7) INSERT همهٔ readings با verified=FALSE, source='patient_self'
    #    all-or-nothing: اگر هر insert خطا دهد، هیچ mark-used نمی‌شود.
    #    (validated کامل شد، پس error در insert غیرمنتظره است — DB constraint/network)
    from django.db import connection as _conn, transaction as _txn
    from django.utils import timezone as _tz
    now_ts = _tz.now()

    # 7+8) INSERT all readings AND mark the token used inside ONE transaction.
    # ATOMIC_REQUESTS is not set (autocommit on, ADR-0008 session-GUC model), so a
    # mid-batch DB error would otherwise partial-commit; wrapping in atomic() gives
    # true all-or-nothing — either every reading is stored and the token consumed,
    # or nothing is and the token stays usable. The session GUC set at step 6
    # (set_config is_local=false) persists inside this block, so RLS still applies;
    # a rollback does NOT reset it (only SET LOCAL would).
    try:
        with _txn.atomic():
            with _conn.cursor() as cursor:
                for vtype, vvalue in validated:
                    cursor.execute(
                        """
                        INSERT INTO clinical.vital_readings
                            (tenant_id, patient_link_id, type, value, unit,
                             measured_at, source, verified, recorded_by)
                        VALUES (%s, %s, %s, %s, %s, %s, 'patient_self', FALSE, 'patient_self_report')
                        """,
                        [
                            tenant_id,
                            patient_link_id,
                            vtype,
                            vvalue,
                            _REPORT_UNIT.get(vtype, ""),
                            now_ts,
                        ],
                    )
            # Mark token used inside the same transaction — rolls back with the
            # inserts if anything fails, so the token is never consumed on error.
            _report_mark_used(token, tenant_id)
    except Exception as exc:
        # بازگشتِ خطای عمومی — جزئیاتِ DB در پاسخ نیست، توکن مصرف نمی‌شود (rollback شد)
        import logging as _logging
        _logging.getLogger(__name__).error(
            "submit_patient_report: DB insert failed for patient_link_id=%s: %s",
            patient_link_id, exc,
        )
        return 422, error_response("خطا در ثبتِ داده — لطفاً دوباره امتحان کنید", "server_error")

    # 9) Build response — سازگار با حالتِ تکی و batch
    accepted_out = [SelfReportReadingOut(type=t, value=v) for t, v in validated]
    first_type, first_value = validated[0]

    return 200, SelfReportOut(
        # backward-compat: تکی → همان type/value قدیمی
        type=first_type if len(validated) == 1 else None,
        value=first_value if len(validated) == 1 else None,
        accepted=accepted_out,
        count=len(accepted_out),
    )


def _report_distinguish_error(token: str):
    """
    Helper: تفکیکِ ۴۰۴ (not found/never issued) از ۴۰۹ (used) از ۴۱۰ (expired).

    این lookup با SECURITY DEFINER‌های موجود کار می‌کند:
      - report_resolve_token فقط used_at IS NULL AND expires_at > now را برمی‌گرداند.
      - برای تفکیک state، یک raw lookup بدونِ RLS لازم داریم.
      - ما از یک helper function دیگر (report_state_token) استفاده نمی‌کنیم
        چون scope را بزرگ نمی‌کنیم.
    پس از مشورتِ security-privacy-advisor: generic 404 ایمن‌تر است.
    فقط برای UX بهتر: اگر token در فرمتِ درستی باشد، ۴۰۹ می‌دهیم وگرنه ۴۰۴.

    تصمیمِ نهایی: همیشه ۴۰۴ (generic) — کمترین information leakage.
    توضیحِ ۴۰۹ به staff (نه در response) داده می‌شود.
    """
    return 404, error_response(
        "توکن معتبر نیست، منقضی شده، یا قبلاً استفاده شده است",
        "token_invalid",
    )


# ===========================================================================
# Vital Review — خوشهٔ J، قدم ۴۷
#
# POST /patients/{uuid}/vitals/{vital_id}/verify   → staff JWT، GUC-scoped/RLS
# POST /patients/{uuid}/vitals/{vital_id}/reject   → staff JWT، GUC-scoped/RLS
#
# اصلِ ایمنی (قفل‌شده با gp-family-medicine-advisor):
#   ۶ فیلترِ verified=True در موتور دست‌نخورده باقی می‌مانند.
#   rejected هم verified=FALSE است → خودکار از موتور خارج می‌ماند (Assert C).
#   soft-keep: reject حذفِ فیزیکی نیست — ردیف در DB می‌ماند برای audit.
#
# State machine (slice14):
#   pending  : verified=FALSE, rejected_at IS NULL  — انتظار
#   approved : verified=TRUE                         — بعد از verify
#   rejected : verified=FALSE, rejected_at NOT NULL  — soft-kept for audit
#
# RLS: GUC app.current_tenant ست می‌شود → staff فقط tenantِ خود را می‌بیند.
# Idempotency: verifyِ ردیفِ از-قبل-verified → 409 conflict.
# Audit: هر دو اکشن لاگ می‌شوند.
# ===========================================================================

class VitalReviewOut(Schema):
    """Vital reading بعد از review — حالتِ کامل برای UI."""
    id: int
    patient_link_id: int
    type: str
    value: float
    unit: Optional[str] = None
    measured_at: datetime
    source: Optional[str] = None
    verified: bool
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None


def _vital_to_review_out(v: "VitalReading") -> VitalReviewOut:
    return VitalReviewOut(
        id=v.id,
        patient_link_id=v.patient_link_id,
        type=v.type,
        value=v.value,
        unit=v.unit,
        measured_at=v.measured_at,
        source=v.source,
        verified=v.verified,
        verified_by=v.verified_by,
        verified_at=v.verified_at,
        rejected_by=v.rejected_by,
        rejected_at=v.rejected_at,
    )


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/vitals/{vital_id}/verify
# ---------------------------------------------------------------------------

@api.post(
    "/patients/{patient_uuid}/vitals/{vital_id}/verify",
    response={
        200: VitalReviewOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["vitals"],
)
def verify_vital(request, patient_uuid: uuid_module.UUID, vital_id: int):
    """
    تأییدِ یک vital readingِ self-reported توسطِ پزشک/staff.

    State transition: pending (verified=FALSE, rejected_at=NULL) → approved (verified=TRUE).

    پس از verify، ردیف verified=TRUE می‌شود و در build_facts / کارت / پیشنهادها ظاهر می‌شود.
    ۶ فیلترِ موتور (verified=True) دست‌نخورده هستند — هیچ تغییری در منطقِ فیلتر داده نشده.

    RLS-scoped: GUC app.current_tenant ست می‌شود → staff فقط tenantِ خودش را می‌بیند.
    Idempotency: اگر ردیف از قبل verified=TRUE باشد → ۴۰۹ conflict.
    Audit: log_activity با action_type='vital_verified'.

    Returns 404 اگر vital وجود نداشته باشد یا متعلق به این بیمار/tenant نباشد.
    Returns 409 اگر ردیف از قبل verified=TRUE بود (idempotency guard).
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    actor_id = getattr(request.auth, "pk", None)

    # 1. Resolve uuid → patient link (tenant-scoped, 404 if not found)
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    # 2. Fetch the vital — must belong to this patient + tenant (RLS gate)
    #    set_tenant_guc ensures the ORM query runs with the correct GUC
    from platform_core.tenant_context import set_tenant_guc as _set_guc
    _set_guc(tenant_id)

    try:
        vital = VitalReading.objects.get(
            id=vital_id,
            patient_link_id=link.id,
            tenant_id=tenant_id,
        )
    except VitalReading.DoesNotExist:
        return 404, error_response(
            f"VitalReading id={vital_id} not found for this patient/tenant.",
            "not_found",
        )

    # 3. Idempotency guard — already verified → 409
    if vital.verified:
        return 409, error_response(
            f"VitalReading id={vital_id} is already verified (verified=TRUE). "
            "No action taken.",
            "conflict",
        )

    # 4. Apply verify: verified=TRUE, verified_by, verified_at
    now_ts = timezone.now()
    vital.verified = True
    vital.verified_by = actor
    vital.verified_at = now_ts
    vital.save(update_fields=["verified", "verified_by", "verified_at"])

    # 5. Audit — state-changing write, best-effort append-only
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_id,
        username=actor,
        action_type="vital_verified",
        action_category="clinical",
        target_table="vital_readings",
        target_id=vital_id,
        patient_link_id=link.id,
        description=f"type={vital.type}, value={vital.value}, source={vital.source}",
    )

    return 200, _vital_to_review_out(vital)


# ---------------------------------------------------------------------------
# POST /patients/{uuid}/vitals/{vital_id}/reject
# ---------------------------------------------------------------------------

@api.post(
    "/patients/{patient_uuid}/vitals/{vital_id}/reject",
    response={
        200: VitalReviewOut,
        404: ErrorSchema,
        409: ErrorSchema,
    },
    auth=_jwt_auth,
    tags=["vitals"],
)
def reject_vital(request, patient_uuid: uuid_module.UUID, vital_id: int):
    """
    ردِ یک vital readingِ self-reported توسطِ پزشک/staff.

    State transition: pending (verified=FALSE, rejected_at=NULL) → rejected (rejected_by, rejected_at ست).

    پس از reject، ردیف verified=FALSE باقی می‌ماند → خودکار از موتور/کارت/پیشنهادها خارج است.
    soft-keep: ردیف از DB حذف نمی‌شود — برای audit trail نگه‌داری می‌شود (توصیهٔ حقوقیِ GP).

    RLS-scoped: GUC app.current_tenant ست می‌شود → staff فقط tenantِ خودش را می‌بیند.
    Guard: اگر ردیف قبلاً rejected باشد (rejected_at IS NOT NULL) → ۴۰۹.
    اگر ردیف verified=TRUE باشد (approved) → ۴۰۹ (نمی‌توان approved را reject کرد).
    Audit: log_activity با action_type='vital_rejected'.

    Returns 404 اگر vital وجود نداشته باشد یا متعلق به این بیمار/tenant نباشد.
    Returns 409 اگر ردیف قبلاً rejected یا verified (approved) باشد.
    """
    tenant_id = request.tenant_id
    actor = getattr(request.auth, "username", None) or "unknown"
    actor_id = getattr(request.auth, "pk", None)

    # 1. Resolve uuid → patient link (tenant-scoped, 404 if not found)
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    # 2. Set GUC + fetch the vital — must belong to this patient + tenant
    from platform_core.tenant_context import set_tenant_guc as _set_guc
    _set_guc(tenant_id)

    try:
        vital = VitalReading.objects.get(
            id=vital_id,
            patient_link_id=link.id,
            tenant_id=tenant_id,
        )
    except VitalReading.DoesNotExist:
        return 404, error_response(
            f"VitalReading id={vital_id} not found for this patient/tenant.",
            "not_found",
        )

    # 3. Guard: cannot reject an already-rejected or already-verified (approved) vital
    if vital.rejected_at is not None:
        return 409, error_response(
            f"VitalReading id={vital_id} is already rejected (rejected_at is set). "
            "No action taken.",
            "conflict",
        )
    if vital.verified:
        return 409, error_response(
            f"VitalReading id={vital_id} is verified (approved). "
            "Cannot reject a verified reading — re-enter data via an encounter if needed.",
            "conflict",
        )

    # 4. Apply reject: rejected_by + rejected_at; verified stays FALSE (gate intact)
    now_ts = timezone.now()
    vital.rejected_by = actor
    vital.rejected_at = now_ts
    # vital.verified stays FALSE — the 6 engine filters (verified=True) remain untouched
    vital.save(update_fields=["rejected_by", "rejected_at"])

    # 5. Audit — state-changing write, best-effort append-only
    log_activity(
        tenant_id=tenant_id,
        user_id=actor_id,
        username=actor,
        action_type="vital_rejected",
        action_category="clinical",
        target_table="vital_readings",
        target_id=vital_id,
        patient_link_id=link.id,
        description=f"type={vital.type}, value={vital.value}, source={vital.source}",
    )

    return 200, _vital_to_review_out(vital)
