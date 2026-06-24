"""
clinical/suggestion_service.py — Demographics bridge for the suggestion engine.

STEP 6: age fact stabilization.

This module is the ONE canonical entry point for any non-HTTP caller
(batch worklist generation, scheduler tasks, Step 12 auto-worklist, etc.)
that needs to run the clinical rule engine WITH demographics reliably supplied.

Design rules:
  - rule_engine.py stays PURE — it never imports accounting_port.
    Demographics are ALWAYS injected; the engine cannot fetch them itself.
  - This service is the ONLY place that couples patient_links → accounting_port
    to resolve a PatientDTO for the engine. This keeps the Port dependency
    in ONE place instead of scattered across callers.
  - The read direction is: clinical → accounting (read-only Port).
    This is the allowed direction per ROADMAP cluster-B.
  - Fails GRACEFULLY: if the accounting DB is absent or the link has no
    patient_id, returns None (app keeps working standalone).
  - Callers that already have a PatientDTO (e.g. get_suggestions, which
    fetches it from the uuid route param) should pass it directly to
    rule_engine.grouped() — no need to call this service.

Public API
----------
resolve_demographics(patient_link_id, tenant_id) -> PatientDTO | None
    Look up patient_links.patient_id for this link, then fetch the
    PatientDTO from the read-only accounting_port. Returns None if
    the link is absent, has no patient_id, or the accounting row
    does not exist (standalone mode).

evaluate_for_patient(patient_link_id, tenant_id) -> list[dict]
    Like rule_engine.evaluate(), but resolves demographics first.
    Use this for programmatic callers that only have a patient_link_id.

grouped_for_patient(patient_link_id, tenant_id) -> dict
    Like rule_engine.grouped(), but resolves demographics first.
    This is the PREFERRED entry point for Step 12 (auto worklist
    generation) and any future batch / scheduler caller.

    Step 12 MUST call grouped_for_patient(patient_link_id, tenant_id)
    instead of rule_engine.grouped(patient_link_id, tenant_id=…) directly,
    so that age-gated rules always have a birthdate supplied.
"""
from __future__ import annotations

import logging
from typing import Optional

from clinical.models import PatientLink
from clinical import rule_engine

# Lazy import of the accounting port so that this module can be imported
# even when the port is not configured (e.g. in isolated unit tests that
# mock at the model level).  The port is used only inside resolve_demographics.
from accounting_port.port import get_patients_by_ids, PatientDTO

logger = logging.getLogger(__name__)


def resolve_demographics(
    patient_link_id: int,
    tenant_id: int,
) -> Optional[PatientDTO]:
    """
    Resolve demographics for a patient_link_id by going through the Port.

    Steps:
      1. Fetch patient_links row → extract patient_id (accounting FK).
      2. Batch-fetch (single-row batch) via get_patients_by_ids([patient_id]).
      3. Return the PatientDTO or None.

    Returns None in all graceful-failure scenarios:
      - patient_link_id does not exist for this tenant
      - PatientLink.patient_id is NULL / falsy (unlinked standalone enrollment)
      - accounting DB is absent (standalone mode)
      - accounting.patients row does not exist for that patient_id

    Never raises for expected absence; does log unexpected exceptions.
    """
    try:
        link = PatientLink.objects.get(id=patient_link_id, tenant_id=tenant_id)
    except PatientLink.DoesNotExist:
        logger.debug(
            "resolve_demographics: no patient_link with id=%s tenant=%s",
            patient_link_id,
            tenant_id,
        )
        return None

    accounting_patient_id: Optional[int] = link.patient_id
    if not accounting_patient_id:
        logger.debug(
            "resolve_demographics: patient_link id=%s has no accounting patient_id",
            patient_link_id,
        )
        return None

    try:
        dtos = get_patients_by_ids([accounting_patient_id])
    except Exception as exc:
        # Accounting DB absent or inaccessible (standalone mode) — fail gracefully.
        logger.warning(
            "resolve_demographics: accounting port unavailable for link=%s: %s",
            patient_link_id,
            exc,
        )
        return None

    if not dtos:
        logger.debug(
            "resolve_demographics: accounting.patients id=%s not found",
            accounting_patient_id,
        )
        return None

    return dtos[0]


def evaluate_for_patient(
    patient_link_id: int,
    tenant_id: int,
) -> list[dict]:
    """
    Run rule_engine.evaluate() with demographics ALWAYS resolved.

    Returns the list of fired rule dicts (same structure as rule_engine.evaluate).
    If demographics cannot be resolved, age-gated rules will be fail-closed
    (age=None → they don't fire) — which is the documented safe behaviour.
    """
    demographics = resolve_demographics(patient_link_id, tenant_id)
    return rule_engine.evaluate(
        patient_link_id=patient_link_id,
        demographics=demographics,
        tenant_id=tenant_id,
    )


def grouped_for_patient(
    patient_link_id: int,
    tenant_id: int,
) -> dict:
    """
    Run rule_engine.grouped() with demographics ALWAYS resolved.

    This is the CANONICAL entry point for any non-HTTP caller that only
    has a patient_link_id (e.g. Step 12 auto worklist generation).

    Returns the grouped dict (same structure as rule_engine.grouped):
      {
        "sections": [...],
        "count": int,
        "has_redflag": bool,
      }

    NOTE FOR STEP 12: use this function, not rule_engine.grouped() directly.
    Calling rule_engine.grouped(patient_link_id) without demographics means
    age=None and all age-gated rules silently never fire.
    """
    demographics = resolve_demographics(patient_link_id, tenant_id)
    return rule_engine.grouped(
        patient_link_id=patient_link_id,
        demographics=demographics,
        tenant_id=tenant_id,
    )
