"""
clinical/encounter_service.py — Encounter aggregate-root service (Step 9).

State machine
─────────────
  open → completed   (complete_encounter)
  open → cancelled   (cancel_encounter)
  completed, cancelled → terminal (any other transition raises InvalidEncounterTransition)

Write rules
───────────
  - Adding vitals/labs to an encounter requires status == 'open'.
    A sealed (completed/cancelled) encounter is immutable — raises EncounterSealed.
  - Tenant scoping: every query filters (id, tenant_id); a wrong tenant raises
    EncounterNotFound so callers cannot probe other tenants' data.

Duplicate-vital decision
────────────────────────
  Step 4 added UNIQUE NULLS NOT DISTINCT (tenant_id, patient_link_id, type,
  measured_at, source) on clinical.vital_readings.
  Decision: on a duplicate natural-key collision, raise DuplicateVitalReading
  (a sub-class of EncounterServiceError) with a clear message.
  Rationale: silently returning the existing row would confuse callers about
  which encounter_id (if any) owns the reading.  Raising lets Step 10's endpoint
  map to 409 Conflict so the caller can de-dupe before retrying.

Audit
─────
  Every state-changing call appends one row to clinical.activity_logs via
  clinical.audit.log_activity (best-effort; audit failure never aborts the
  main operation).

  log_activity signature (see clinical/audit.py):
    log_activity(
        *,
        tenant_id, user_id, username,
        action_type,
        action_category=None, description=None,
        target_table=None, target_id=None, patient_link_id=None,
    )

  Mapping used here:
    action_type     = 'encounter_created' | 'encounter_completed' |
                      'encounter_cancelled' | 'vital_added' | 'lab_added'
    action_category = 'encounter'
    target_table    = 'clinical.encounters' (or 'vital_readings' / 'lab_results')
    target_id       = the PK of the created/mutated row
    patient_link_id = encounter.patient_link_id

Timestamps
──────────
  django.utils.timezone.now() → aware datetime (Django USE_TZ=True, Asia/Tehran).
  updated_at on encounters is managed by a DB trigger (slice4b) — never set it here.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.db import IntegrityError
from django.utils import timezone

from clinical.models import Encounter, VitalReading, LabResult, Prescription, PrescriptionItem
from clinical.audit import log_activity

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Domain exceptions
# ─────────────────────────────────────────────────────────────────────────────

class EncounterServiceError(Exception):
    """Base class for all domain errors in this service."""


class EncounterNotFound(EncounterServiceError):
    """
    Raised when an encounter does not exist for the given (id, tenant_id).
    Deliberately the same message for 'not found' and 'wrong tenant' so callers
    cannot probe other tenants' data through error differentiation.
    """


class InvalidEncounterTransition(EncounterServiceError):
    """
    Raised when a state transition is not allowed by the state machine.
    e.g. complete_encounter on an already-completed encounter.
    """


class EncounterSealed(EncounterServiceError):
    """
    Raised when trying to add vitals/labs to a non-open encounter.
    A completed or cancelled encounter is immutable.
    """


class InvalidEncounterType(EncounterServiceError):
    """
    Raised when encounter_type is not in the allowed set.
    Validated in the service BEFORE hitting the DB (the DB CHECK is a backstop).
    """


class DuplicateVitalReading(EncounterServiceError):
    """
    Raised when add_vital_to_encounter would violate the UNIQUE natural key
    (tenant_id, patient_link_id, type, measured_at, source) from Step 4.
    Callers should surface this as HTTP 409 Conflict.
    """


class InsurancePrescriptionNotSupported(EncounterServiceError):
    """
    Raised when a caller attempts to create a prescription with mode='insurance'.

    The insurance/MV3 bridge track is BLOCKED until the owner provides live access
    and the final structure of the insurance portal prescription page.
    Only mode='free' prescriptions are supported in this step.
    Callers should surface this as HTTP 422 Unprocessable Entity.
    """


class PrescriptionItemValidationError(EncounterServiceError):
    """
    Raised when a prescription item fails service-layer validation BEFORE the DB.

    Covers: invalid frequency, invalid route, quantity <= 0, duration_days <= 0.
    The DB CHECK constraints are a backstop; this exception lets the caller
    surface a clear domain error before hitting the DB.
    Callers should surface this as HTTP 422.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_ENCOUNTER_TYPES = frozenset({"visit", "follow_up", "phone", "remote"})


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_encounter(encounter_id: int, tenant_id: int) -> Encounter:
    """
    Fetch the encounter by (id, tenant_id).
    Raises EncounterNotFound if absent (including wrong-tenant case).
    """
    try:
        return Encounter.objects.get(id=encounter_id, tenant_id=tenant_id)
    except Encounter.DoesNotExist:
        raise EncounterNotFound(
            f"Encounter {encounter_id} not found for tenant {tenant_id}."
        )


def _require_open(encounter: Encounter) -> None:
    """
    Guard: raise EncounterSealed if the encounter is not 'open'.
    Used before adding vitals/labs.
    """
    if encounter.status != Encounter.STATUS_OPEN:
        raise EncounterSealed(
            f"Encounter {encounter.id} is '{encounter.status}' — "
            "vitals and labs can only be added to an open encounter."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def create_encounter(
    patient_link_id: int,
    tenant_id: int,
    *,
    encounter_type: str = "visit",
    encounter_at=None,
    doctor_id: Optional[int] = None,
    chief_complaint: Optional[str] = None,
    appointment_id: Optional[int] = None,
    created_by: Optional[str] = None,
) -> Encounter:
    """
    Create a new Encounter in 'open' status.

    Validates encounter_type BEFORE hitting the DB (DB CHECK is the backstop).
    encounter_at defaults to timezone.now() if not supplied.

    Returns the created Encounter instance.
    Raises InvalidEncounterType for a bad encounter_type value.
    """
    if encounter_type not in ALLOWED_ENCOUNTER_TYPES:
        raise InvalidEncounterType(
            f"encounter_type '{encounter_type}' is not valid. "
            f"Allowed: {sorted(ALLOWED_ENCOUNTER_TYPES)}."
        )

    now = timezone.now()
    if encounter_at is None:
        encounter_at = now

    enc = Encounter.objects.create(
        tenant_id=tenant_id,
        patient_link_id=patient_link_id,
        encounter_type=encounter_type,
        encounter_at=encounter_at,
        status=Encounter.STATUS_OPEN,
        doctor_id=doctor_id,
        chief_complaint=chief_complaint,
        appointment_id=appointment_id,
        created_by=created_by,
        created_at=now,
        # updated_at is set by DB trigger — pass now() to satisfy NOT NULL
        # from ORM perspective; the trigger overwrites it on every UPDATE.
        updated_at=now,
    )

    log_activity(
        tenant_id=tenant_id,
        user_id=None,
        username=created_by,
        action_type="encounter_created",
        action_category="encounter",
        description=(
            f"Encounter {enc.id} created "
            f"(type={encounter_type}, patient_link_id={patient_link_id})"
        ),
        target_table="clinical.encounters",
        target_id=enc.id,
        patient_link_id=patient_link_id,
    )

    return enc


def add_vital_to_encounter(
    encounter_id: int,
    tenant_id: int,
    *,
    type: str,  # noqa: A002  — mirrors VitalReading.type column name
    value: float,
    unit: Optional[str] = None,
    source: str = "clinic",
    measured_at=None,
    recorded_by: Optional[str] = None,
) -> VitalReading:
    """
    Add a VitalReading linked to an open Encounter.

    Guards:
      - Encounter must exist for (encounter_id, tenant_id) → EncounterNotFound.
      - Encounter must be 'open' → EncounterSealed.
      - UNIQUE (tenant_id, patient_link_id, type, measured_at, source) → DuplicateVitalReading.

    Returns the created VitalReading.
    """
    enc = _get_encounter(encounter_id, tenant_id)
    _require_open(enc)

    if measured_at is None:
        measured_at = timezone.now()

    try:
        reading = VitalReading.objects.create(
            tenant_id=tenant_id,
            patient_link_id=enc.patient_link_id,
            type=type,
            value=value,
            unit=unit,
            measured_at=measured_at,
            source=source,
            recorded_by=recorded_by,
            # slice4b adds encounter_id to vital_readings too — link the reading
            # to the encounter it was taken in (aggregate-root invariant).
            encounter_id=enc.id,
        )
    except IntegrityError as exc:
        # The UNIQUE constraint from Step 4 fired.
        raise DuplicateVitalReading(
            f"A VitalReading with type='{type}', measured_at='{measured_at}', "
            f"source='{source}' already exists for patient_link_id={enc.patient_link_id} "
            f"in tenant {tenant_id}. (UNIQUE natural key collision)"
        ) from exc

    log_activity(
        tenant_id=tenant_id,
        user_id=None,
        username=recorded_by,
        action_type="vital_added",
        action_category="encounter",
        description=(
            f"VitalReading id={reading.id} (type={type}, value={value}) "
            f"added under encounter {encounter_id}"
        ),
        target_table="clinical.vital_readings",
        target_id=reading.id,
        patient_link_id=enc.patient_link_id,
    )

    return reading


def add_lab_to_encounter(
    encounter_id: int,
    tenant_id: int,
    *,
    test_name: str,
    test_key: Optional[str] = None,
    value: Optional[float] = None,
    unit: Optional[str] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    taken_at=None,
    recorded_by: Optional[str] = None,
) -> LabResult:
    """
    Add a LabResult linked to an open Encounter.

    Derives patient_link_id from the encounter (single source of truth).
    Sets encounter_id on the LabResult row (slice4b column).

    Guards:
      - Encounter must exist for (encounter_id, tenant_id) → EncounterNotFound.
      - Encounter must be 'open' → EncounterSealed.

    Returns the created LabResult.
    """
    enc = _get_encounter(encounter_id, tenant_id)
    _require_open(enc)

    if taken_at is None:
        taken_at = timezone.now()

    lab = LabResult.objects.create(
        tenant_id=tenant_id,
        patient_link_id=enc.patient_link_id,
        test_name=test_name,
        test_key=test_key,
        value=value,
        unit=unit,
        ref_low=ref_low,
        ref_high=ref_high,
        taken_at=taken_at,
        recorded_by=recorded_by,
        encounter_id=enc.id,
    )

    log_activity(
        tenant_id=tenant_id,
        user_id=None,
        username=recorded_by,
        action_type="lab_added",
        action_category="encounter",
        description=(
            f"LabResult id={lab.id} (test_name={test_name}, value={value}) "
            f"added under encounter {encounter_id}"
        ),
        target_table="clinical.lab_results",
        target_id=lab.id,
        patient_link_id=enc.patient_link_id,
    )

    return lab


def complete_encounter(
    encounter_id: int,
    tenant_id: int,
    *,
    summary_note: Optional[str] = None,
    completed_by: Optional[str] = None,
) -> Encounter:
    """
    Transition an open encounter to 'completed'.

    Sets completed_at = timezone.now().
    Raises InvalidEncounterTransition if the encounter is not 'open'.
    Raises EncounterNotFound if (encounter_id, tenant_id) is unknown.

    NOTE: updated_at is managed by the DB trigger — not set here.
    """
    enc = _get_encounter(encounter_id, tenant_id)

    if enc.status != Encounter.STATUS_OPEN:
        raise InvalidEncounterTransition(
            f"Cannot complete encounter {encounter_id}: "
            f"current status is '{enc.status}' (expected 'open')."
        )

    now = timezone.now()
    enc.status = Encounter.STATUS_COMPLETED
    enc.completed_at = now
    if summary_note is not None:
        enc.summary_note = summary_note
    # updated_at managed by DB trigger — pass current value so ORM save works;
    # the trigger will overwrite it.
    enc.save(update_fields=["status", "completed_at", "summary_note", "updated_at"])

    log_activity(
        tenant_id=tenant_id,
        user_id=None,
        username=completed_by,
        action_type="encounter_completed",
        action_category="encounter",
        description=(
            f"Encounter {encounter_id} completed "
            f"(patient_link_id={enc.patient_link_id})"
        ),
        target_table="clinical.encounters",
        target_id=enc.id,
        patient_link_id=enc.patient_link_id,
    )

    return enc


def cancel_encounter(
    encounter_id: int,
    tenant_id: int,
    *,
    reason: Optional[str] = None,
    cancelled_by: Optional[str] = None,
) -> Encounter:
    """
    Transition an open encounter to 'cancelled'.

    Raises InvalidEncounterTransition if the encounter is not 'open'.
    Raises EncounterNotFound if (encounter_id, tenant_id) is unknown.

    reason is stored in summary_note (no dedicated cancel_reason column in slice4b).
    """
    enc = _get_encounter(encounter_id, tenant_id)

    if enc.status != Encounter.STATUS_OPEN:
        raise InvalidEncounterTransition(
            f"Cannot cancel encounter {encounter_id}: "
            f"current status is '{enc.status}' (expected 'open')."
        )

    enc.status = Encounter.STATUS_CANCELLED
    if reason is not None:
        enc.summary_note = reason
    enc.save(update_fields=["status", "summary_note", "updated_at"])

    log_activity(
        tenant_id=tenant_id,
        user_id=None,
        username=cancelled_by,
        action_type="encounter_cancelled",
        action_category="encounter",
        description=(
            f"Encounter {encounter_id} cancelled "
            f"(patient_link_id={enc.patient_link_id}, reason={reason!r})"
        ),
        target_table="clinical.encounters",
        target_id=enc.id,
        patient_link_id=enc.patient_link_id,
    )

    return enc


# ─────────────────────────────────────────────────────────────────────────────
# Prescription constants (validated here; DB CHECK is the backstop)
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_FREQUENCIES = PrescriptionItem.ALLOWED_FREQUENCIES
_ALLOWED_ROUTES = PrescriptionItem.ALLOWED_ROUTES


def _validate_item(item: dict, index: int) -> None:
    """
    Validate one prescription item dict before writing to DB.

    Raises PrescriptionItemValidationError with a clear message on first error.
    Validated fields: frequency, route, quantity > 0, duration_days > 0.
    drug_name is required (not None/empty).
    """
    drug_name = item.get("drug_name", "")
    if not drug_name or not str(drug_name).strip():
        raise PrescriptionItemValidationError(
            f"Item [{index}]: drug_name is required and must not be empty."
        )

    frequency = item.get("frequency")
    if frequency is not None and frequency not in _ALLOWED_FREQUENCIES:
        raise PrescriptionItemValidationError(
            f"Item [{index}] drug_name={drug_name!r}: "
            f"frequency {frequency!r} is not valid. "
            f"Allowed: {sorted(_ALLOWED_FREQUENCIES)}."
        )

    route = item.get("route")
    if route is not None and route not in _ALLOWED_ROUTES:
        raise PrescriptionItemValidationError(
            f"Item [{index}] drug_name={drug_name!r}: "
            f"route {route!r} is not valid. "
            f"Allowed: {sorted(_ALLOWED_ROUTES)}."
        )

    quantity = item.get("quantity")
    if quantity is not None and quantity <= 0:
        raise PrescriptionItemValidationError(
            f"Item [{index}] drug_name={drug_name!r}: "
            f"quantity must be > 0, got {quantity}."
        )

    duration_days = item.get("duration_days")
    if duration_days is not None and duration_days <= 0:
        raise PrescriptionItemValidationError(
            f"Item [{index}] drug_name={drug_name!r}: "
            f"duration_days must be > 0, got {duration_days}."
        )


def add_prescription_to_encounter(
    encounter_id: int,
    tenant_id: int,
    *,
    kind: str,
    items: list[dict],
    mode: str = "free",
    prescriber_user_id: Optional[int] = None,
    created_by: Optional[str] = None,
) -> Prescription:
    """
    Add a free-mode Prescription (with its PrescriptionItems) to an open Encounter.

    Atomicity
    ─────────
    Prescription header + all PrescriptionItem rows are created inside a single
    Django transaction (atomic block).  If any item creation fails (e.g. a DB
    CHECK violation on an item that passed service-layer validation), the whole
    prescription is rolled back — no orphaned header row is left behind.
    This is intentionally different from the independent-item approach used for
    vitals/labs batches (see ROADMAP note §item 10), because a prescription
    without its items is semantically meaningless.

    Insurance-blocked guard
    ───────────────────────
    The MV3 browser-extension insurance bridge track is BLOCKED (gated on owner
    providing live access + page structure — see CLAUDE.md).  Passing
    mode='insurance' raises InsurancePrescriptionNotSupported so callers cannot
    accidentally initiate an insurance flow.

    Validation (service-layer, before DB)
    ─────────────────────────────────────
    Each item's frequency and route are validated against the allowed sets.
    quantity and duration_days must be > 0 if provided.
    drug_name must be non-empty.
    These checks mirror the DB CHECKs; the DB CHECKs are the backstop.

    Guards
    ──────
    - Encounter must exist for (encounter_id, tenant_id) → EncounterNotFound.
    - Encounter must be 'open' → EncounterSealed.
    - mode must not be 'insurance' → InsurancePrescriptionNotSupported.

    Returns the created Prescription instance (items are accessible via
    PrescriptionItem.objects.filter(prescription_id=rx.id, tenant_id=tenant_id)).
    """
    # ── Insurance-blocked guard (before any DB access) ────────────────────────
    if mode == Prescription.MODE_INSURANCE:
        raise InsurancePrescriptionNotSupported(
            "Insurance prescriptions (mode='insurance') are not supported. "
            "The insurance/MV3 bridge track is blocked pending owner KYC "
            "and portal access. Only mode='free' prescriptions can be written."
        )

    # ── Validate all items upfront (service layer) ────────────────────────────
    for idx, item in enumerate(items):
        _validate_item(item, idx)

    # ── Resolve encounter (also validates tenant scope) ───────────────────────
    enc = _get_encounter(encounter_id, tenant_id)
    _require_open(enc)

    now = timezone.now()

    # ── Atomic: create Prescription header + all PrescriptionItem rows ────────
    from django.db import transaction

    with transaction.atomic():
        rx = Prescription.objects.create(
            tenant_id=tenant_id,
            patient_link_id=enc.patient_link_id,
            kind=kind,
            items=None,                         # structured rows in prescription_items
            mode=mode,                          # always 'free' here; guard above blocks 'insurance'
            prescriber_user_id=prescriber_user_id,
            encounter_id=enc.id,
            issued_at=now,
        )

        for item in items:
            PrescriptionItem.objects.create(
                tenant_id=tenant_id,
                prescription_id=rx.id,
                drug_name=item["drug_name"],
                drug_class=item.get("drug_class"),
                dose_value=item.get("dose_value"),
                dose_unit=item.get("dose_unit"),
                frequency=item.get("frequency"),
                route=item.get("route"),
                quantity=item.get("quantity"),
                duration_days=item.get("duration_days"),
                instructions=item.get("instructions"),
            )

    # ── Audit ────────────────────────────────────────────────────────────────
    log_activity(
        tenant_id=tenant_id,
        user_id=prescriber_user_id,
        username=created_by,
        action_type="prescription_created",
        action_category="encounter",
        description=(
            f"Prescription id={rx.id} (kind={kind!r}, mode={mode}, "
            f"{len(items)} item(s)) added under encounter {encounter_id}"
        ),
        target_table="clinical.prescriptions",
        target_id=rx.id,
        patient_link_id=enc.patient_link_id,
    )

    return rx
