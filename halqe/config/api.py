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

from ninja import Schema, Query
from django.http import Http404
from django.utils import timezone

# Shared API base — the single NinjaAPI instance, JWT auth dependency, the
# Http404 exception handler and the SYSTEM_TENANT_ID sentinel now live in
# config.api_base (cleanup step 3).  This module wires domain routers onto
# `api` and still holds the not-yet-extracted endpoints (steps 4-7 move them).
#
# SYSTEM_TENANT_ID is re-exported here (not used by the endpoints still in this
# module) so that existing `from config.api import SYSTEM_TENANT_ID` consumers
# (e.g. tests/test_tenant_context.py) keep working unchanged.
from config.api_base import api, _jwt_auth, SYSTEM_TENANT_ID  # noqa: F401  (re-export)
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

# ---------------------------------------------------------------------------
# Domain routers (cleanup step 3+).  Each is wired below with add_router using
# a prefix that keeps the full URL byte-identical to the pre-split paths.
# ---------------------------------------------------------------------------
from clinical.api.auth import router as auth_router
from clinical.api.control_room import router as control_room_router
from clinical.api.doctor_queue import router as doctor_queue_router
from clinical.api.engagement import router as engagement_router

# auth domain: route is "/auth/login"; prefix "" → /api/v1/auth/login (unchanged).
api.add_router("", auth_router)
# control-room domain (step 4): routes carry "/control-room…"; prefix "" keeps
# /api/v1/control-room, /api/v1/control-room/conversion,
# /api/v1/control-room/cohort/{cohort_key} byte-identical.
api.add_router("", control_room_router)
# doctor-queue domain (step 4): routes carry "/doctor-queue…"; prefix "" keeps
# /api/v1/doctor-queue and the /start | /done sub-paths byte-identical.
api.add_router("", doctor_queue_router)
# engagement domain (step 4): routes carry "/engagement/approvals…"; prefix ""
# keeps the list + approve | reject | send sub-paths byte-identical.
api.add_router("", engagement_router)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

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
# Auth endpoint — POST /auth/login — MOVED to clinical/api/auth.py (step 3).
# Wired above via api.add_router("", auth_router); URL unchanged.
# ---------------------------------------------------------------------------


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


# ===========================================================================
# Cohort Outcomes (Step 49, cluster K) — GET /manager/cohort-outcomes
# Manager-only: requires JWT with role='manager'.
#
# نمای توصیفیِ تک‌گروهیِ outcome per-condition. on-the-fly، read-only، NULL نه عددِ ساختگی.
# framing/caveat همیشه حاضر؛ تمایزِ engagement-holdout صریح. هیچ ادعای علّی.
# همهٔ فیلدها سریال می‌شوند (درسِ DTOِ قدم ۳۶/۳۸) — تستِ API-shape این را اثبات می‌کند.
# ===========================================================================

from clinical.cohort_outcome_service import cohort_outcomes as _cohort_outcomes


class CohortWindowDTO(Schema):
    """یک پنجره (۳ یا ۶ ماه) از یک متریک — همهٔ rateها Optional (NULL هنگامِ n کم)."""
    n: int                              # تعدادِ بیمارانِ دارای قرائت در پنجره
    mean: Optional[float] = None        # میانگین/٪ in-range across-patient؛ NULL اگر n<min_n
    n_paired: int                       # زیرمجموعهٔ paired (baseline + این پنجره)
    delta: Optional[float] = None       # تغییر روی subsetِ paired؛ NULL اگر n_paired<min_n
    reason: Optional[str] = None        # window_n_insufficient | paired_n_insufficient | None


class CohortMetricDTO(Schema):
    """یک متریکِ یک بیماری (hba1c/ldl/egfr/uacr/tsh/…)."""
    metric_key: str
    metric_type: str                    # mean_delta | relative_median | percent_in_range
    unit: Optional[str] = None
    direction: str                      # high | low
    n_baseline: int
    m3: CohortWindowDTO
    m6: CohortWindowDTO


class CohortSubgroupDTO(Schema):
    """یک زیرگروهِ stratification (frail/non_frail یا ascvd/non_ascvd)."""
    key: str
    metric: CohortMetricDTO


class CohortStratificationDTO(Schema):
    """نتیجهٔ stratification یک بیماری (مشروط به n_subgroup>=min_n)."""
    by: str                             # frailty | ascvd
    reason: Optional[str] = None        # subgroup_too_small | None
    subgroups: Optional[list[CohortSubgroupDTO]] = None
    n_positive: Optional[int] = None
    n_negative: Optional[int] = None


class CohortConditionDTO(Schema):
    """outcomeِ توصیفیِ یک بیماری."""
    condition_code: str
    condition_label: str
    anchor: str                         # indicatorِ کلیدیِ baseline
    n_cohort: int                       # کلِ بیمارانِ فعالِ این بیماری
    n_baseline: int                     # دارایِ baselineِ کافی
    reason: Optional[str] = None        # cohort_too_small | None
    metrics: Optional[list[CohortMetricDTO]] = None   # NULL اگر cohort_too_small
    stratification: Optional[CohortStratificationDTO] = None


class CohortOutcomesResponseDTO(Schema):
    """
    پاسخِ GET /manager/cohort-outcomes.

    framing و caveat اجباری‌اند و در هر پاسخ حاضرند:
      - framing: غیرعلّی بودنِ نمای تک‌گروهی (regression-to-mean، سوگیری، Simpson).
      - caveat: تمایزِ حیاتیِ engagement-holdout از clinical-holdout.
    """
    tenant_id: int
    framing: str
    caveat: str
    n_sufficient: int
    conditions: list[CohortConditionDTO]


@api.get(
    "/manager/cohort-outcomes",
    response={200: CohortOutcomesResponseDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def manager_cohort_outcomes(request):
    """
    نمای توصیفیِ outcomeِ کوهورت per-condition — فقط مدیر.

    on-the-fly، read-only مطلق، بدونِ slice. NULL نه عددِ ساختگی:
      - کوهورتِ کوچک (n_baseline<۳۰) → reason='cohort_too_small'، metrics=null.
      - پنجرهٔ کم‌داده (n<۳۰) → mean=null + reason='window_n_insufficient'.
      - paired کم (n_paired<۳۰) → delta=null + reason='paired_n_insufficient'.
      - زیرگروهِ کوچک → stratification.subgroups=null + reason='subgroup_too_small'.

    metricهای خاص: uacr کاهشِ نسبیِ میانه (٪)، tsh ٪ in-range (نه mean delta).
    verified=True در همهٔ queryها. هیچ ادعای علّی — framing/caveat همیشه.

    Manager-only: staff → 403.
    """
    user_role = getattr(request.auth, "role", "staff")
    if user_role != "manager":
        return 403, error_response(
            "دسترسی محدود است. فقط مدیر می‌تواند این صفحه را ببیند.",
            "forbidden",
        )

    data = _cohort_outcomes(tenant_id=request.tenant_id)
    return 200, data


# ===========================================================================
# Outcome dashboard endpoints (Step 50, cluster K)
#   GET /manager/lapsed-return   — نرخِ بازگشتِ کوهورتِ lapsed (closed-window)
#   GET /manager/control-trend   — ۱۲ باکتِ ماهانهٔ ٪کنترل (per-condition + all)
#
# هر دو manager-only، on-the-fly، read-only، NULL-not-fabricated، غیرعلّی.
# روی seed (۱۰ بیمار) باید NULL برگردانند — اثباتِ گِیت، نه شکست.
# همهٔ فیلدها سریال (درسِ DTOِ قدم ۳۶/۳۸).
# ===========================================================================

from clinical.outcome_trend_service import (
    lapsed_return as _lapsed_return,
    control_trend as _control_trend,
)


class LapsedReturnResponseDTO(Schema):
    """
    پاسخِ GET /manager/lapsed-return.

    «رویدادِ معنادار» = Appointment(done) ∪ vital(verified) ∪ FollowupTask(done).
    خروجیِ SMS/recall عمداً شامل نیست (پرهیز از tautology).
    return_rate همیشه Optional — NULL وقتی denominator < min_n.
    """
    denominator: int                       # کوهورتِ lapsed در زمانِ T0
    returned: int                          # از مخرج، آن‌ها که در پنجرهٔ بازگشت برگشتند
    return_rate: Optional[float] = None     # درصد ۱ رقم؛ NULL اگر denominator<min_n
    lapse_window_days: int                 # 120
    return_window_days: int                # 120
    min_n: int                             # 30
    framing: str                           # غیرعلّی، همیشه


class ControlTrendBucketDTO(Schema):
    """یک باکتِ ماهانه از یک سری (per-condition یا 'all')."""
    ym: str                                # 'YYYY-MM' میلادی (نمایشِ جلالی در UI)
    condition: str                         # diabetes|hypertension|...|all
    assessable_n: int                      # بیمارانِ دارای ≥۱ قرائت تا پایانِ ماه
    controlled_n: int                      # از assessable، آن‌ها که controlled بودند
    pct_controlled: Optional[float] = None  # درصد ۱ رقم؛ NULL اگر assessable_n<min_n


class ControlTrendResponseDTO(Schema):
    """
    پاسخِ GET /manager/control-trend.

    روندِ زمانیِ توصیفی (secular trend، نه اثرِ مداخله). framing همیشه حاضر.
    """
    buckets: list[ControlTrendBucketDTO]
    min_n: int
    framing: str


@api.get(
    "/manager/lapsed-return",
    response={200: LapsedReturnResponseDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def manager_lapsed_return(request):
    """
    نرخِ بازگشتِ کوهورتِ lapsed — فقط مدیر.

    closed-window: T0 = now-240d (lapse 120 + return 120) تا پنجرهٔ بازگشت کاملاً
    سپری شده باشد (رفعِ immortal-time/survivorship). مخرج = بیمارانِ activeِ
    دارای رویدادِ معنادارِ پیش از T0 که آخرین رویدادشان ≤ T0-120d بوده. صورت =
    آن‌ها که در (T0, T0+120d] رویدادِ معنادار داشتند. SMS/recall شمرده نمی‌شود.
    return_rate = NULL اگر denominator < 30 (NULL نه عددِ ساختگی).

    Manager-only: staff → 403.
    """
    user_role = getattr(request.auth, "role", "staff")
    if user_role != "manager":
        return 403, error_response(
            "دسترسی محدود است. فقط مدیر می‌تواند این صفحه را ببیند.",
            "forbidden",
        )
    return 200, _lapsed_return(tenant_id=request.tenant_id)


@api.get(
    "/manager/control-trend",
    response={200: ControlTrendResponseDTO, 403: ErrorSchema},
    auth=_jwt_auth,
    tags=["manager"],
)
def manager_control_trend(request):
    """
    روندِ ماهانهٔ ٪کنترل (۱۲ باکت)، per-condition + سریِ 'all' — فقط مدیر.

    as-of: برای هر ماه، آخرین قرائتِ verified هر vitalِ کنترلی تا پایانِ ماه؛
    طبقه‌بندیِ control (uncontrolled/borderline/controlled/unknown). مخرجِ هر باکت =
    assessable (unknown خارج)؛ صورت = controlled. pct_controlled = NULL اگر
    assessable < 30. روندِ توصیفی — secular trend، نه اثرِ مداخله.

    Manager-only: staff → 403.
    """
    user_role = getattr(request.auth, "role", "staff")
    if user_role != "manager":
        return 403, error_response(
            "دسترسی محدود است. فقط مدیر می‌تواند این صفحه را ببیند.",
            "forbidden",
        )
    return 200, _control_trend(tenant_id=request.tenant_id)
