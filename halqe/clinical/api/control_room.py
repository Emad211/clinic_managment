"""
Control Room domain router (Step 15) — prioritized cohort targeting.

Migrated out of the ``config/api.py`` god-file in cleanup step 4.

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", control_room_router)`` and the routes below carry their
full sub-paths, so ``/api/v1`` (urls.py) + ``""`` (prefix) + ``"/control-room…"``
== the same paths as before:

  GET  /api/v1/control-room              → panel (JWT; show_value = role=='manager')
  GET  /api/v1/control-room/conversion   → funnel conversion metric (JWT)
  GET  /api/v1/control-room/cohort/{key} → recomputed cohort patient ids (JWT)

Clinical-first priority score; revenue is manager-only seasoning.
Non-managers: show_value=False (no revenue column, no valuable_drifting cohort).
NEVER writes accounting.  All revenue reads via accounting_port (read-only).
"""
from typing import Optional

from ninja import Router, Schema

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response
import clinical.control_room_service as _cr_svc

router = Router()


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

@router.get(
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

@router.get(
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

@router.get(
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
