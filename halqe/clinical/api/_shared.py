"""
Cross-domain shared primitives for the Halqe Platform API (cleanup step 7).

This module owns the helpers and DTOs that are used by MORE THAN ONE domain
router. It is the seam that lets the remaining domains (patients, vitals,
suggestions, worklist, encounters, self-report) be split apart without forcing
any router to import another router — which would create an import cycle.

Dependency direction (one-way, cycle-free):
  - ``_shared`` imports ONLY from services/models, ``config.*`` and
    ``config.api_base``.  It NEVER imports a domain router.
  - Domain routers import FROM ``_shared`` (and from ``config.api_base`` /
    ``config.errors`` / ``config.pagination``).

What lives here (cross-domain only — single-domain helpers stay in their router):
  - ``_resolve_patient_link_for_tenant`` — used by encounters, vitals (verify/
    reject) and self-report (which previously lazy-imported it from
    ``config.api``; step 7 makes that a normal import from here).
  - ``VitalReadingDTO`` — the read-side vital DTO used by both the patients
    domain (GET /patients/{uuid}/record) and the vitals domain
    (GET /patients/{uuid}/vitals/latest).
"""
from __future__ import annotations

import uuid as uuid_module
from typing import Optional
from datetime import datetime

from ninja import Schema
from django.http import Http404

from accounting_port.port import get_patient_by_uuid
from clinical.models import PatientLink


# ---------------------------------------------------------------------------
# Cross-domain helper — uuid → accounting patient → clinical PatientLink (tenant)
# ---------------------------------------------------------------------------

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
# Cross-domain DTO — vital reading (read side)
# Used by the patients domain (record) AND the vitals domain (latest).
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
