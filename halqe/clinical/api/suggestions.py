"""
Suggestions domain router (cleanup step 7 — god-file split).

Migrated verbatim out of the ``config/api.py`` god-file. Holds the clinical
decision-support surfaces — all SUGGESTION-ONLY, all JWT, all tenant-scoped:

  GET  /patients/{uuid}/suggestions                       → grouped fired rules
  POST /patients/{uuid}/suggestions/{rule_code}/action    → accept/dismiss
  GET  /patients/{uuid}/screening-timeline                → periodic screening
  GET  /patients/{uuid}/medications/{med_id}/effect       → pre/post drug effect

URLs are preserved byte-for-byte: ``config.api`` wires this router with
``api.add_router("", suggestions_router)`` and the routes carry their full short
paths, so ``/api/v1`` (urls.py) + the path == the same full paths as before.

SUGGESTION-ONLY framing is preserved verbatim on every surface — the physician
decides; the app only suggests/reminds. The accept/dismiss action upserts the
current state into ``suggestion_log`` AND appends an immutable row to
``suggestion_events`` (full history) — both behaviours unchanged.

This module imports FROM ``config.api_base`` (shared ``_jwt_auth``); nothing in
``api_base`` imports a router, so the package stays free of cycles.
"""
from __future__ import annotations

import uuid as uuid_module
from typing import Optional
from datetime import datetime

from ninja import Router, Schema
from django.http import Http404
from django.utils import timezone

from config.api_base import _jwt_auth
from config.errors import ErrorSchema, error_response
from clinical.api._shared import _resolve_patient_link_for_tenant

from clinical.models import (
    SuggestionLog,
    SuggestionEvent,
    PatientMedication as _PatientMedication,
)
from clinical.suggestion_service import grouped_for_patient as _grouped_for_patient
from clinical.followup_engine import screening_timeline as _screening_timeline
from clinical.medication_effect_service import compute_medication_effect as _compute_med_effect
from clinical.audit import log_activity

router = Router()


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

@router.get(
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

    # 1-2. Resolve uuid → accounting patient → clinical enrollment for THIS
    #      tenant (shared helper; same Http404 messages as before, step 62).
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

    # 3. Run the suggestion engine via the canonical bridge helper.
    # grouped_for_patient resolves demographics from the Port internally,
    # ensuring age-gated rules always have a birthdate — even when this
    # endpoint is refactored or reused in batch/non-HTTP contexts.
    # Note: demographics were already fetched while resolving the PatientLink
    # (inside the shared helper above). grouped_for_patient performs one
    # additional Port fetch (same patient, single indexed PK lookup) —
    # acceptable overhead for centralisation.
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
# Suggestion action schemas
# ---------------------------------------------------------------------------

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


# ── POST /patients/{uuid}/suggestions/{rule_code}/action ─────────────────────

@router.post(
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

    # 2-3. Resolve uuid → accounting patient (read-only via Port) → clinical
    #      enrollment for THIS tenant (shared helper, same 404s — step 62).
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

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


@router.get(
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

    # 1-2. Resolve uuid → accounting patient (read-only Port) → clinical
    #      enrollment for THIS tenant (shared helper, same 404s — step 62).
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

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


@router.get(
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

    # ── ۱. resolve patient (shared helper, same 404s — step 62) ──────────────
    link = _resolve_patient_link_for_tenant(patient_uuid, tenant_id)

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
