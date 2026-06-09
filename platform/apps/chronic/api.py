"""Chronic-care API router (django-ninja). Read-only slices for the wedge UI:
recent vitals and the open follow-up worklist. Tenant-filtered by RLS."""

from typing import List, Optional

from django.shortcuts import get_object_or_404
from ninja import ModelSchema, Router

from apps.patients.models import Patient

from . import rule_engine
from .models import ClinicalRule, FollowupTask, VitalReading

router = Router(tags=["chronic"])


class VitalOut(ModelSchema):
    class Meta:
        model = VitalReading
        fields = ["id", "patient", "indicator_key", "value", "measured_at", "source"]


class FollowupOut(ModelSchema):
    class Meta:
        model = FollowupTask
        fields = ["id", "patient", "item_key", "title", "due_date", "status", "source_rule"]


@router.get("/vitals", response=List[VitalOut])
def list_vitals(request, patient_id: str, indicator_key: Optional[str] = None, limit: int = 100):
    qs = VitalReading.objects.filter(patient_id=patient_id)
    if indicator_key:
        qs = qs.filter(indicator_key=indicator_key)
    return list(qs.order_by("-measured_at")[: min(limit, 500)])


@router.get("/followups", response=List[FollowupOut])
def list_followups(request, status: str = "open", limit: int = 100):
    qs = FollowupTask.objects.filter(status=status)
    return list(qs.order_by("due_date")[: min(limit, 500)])


@router.get("/suggestions")
def suggestions(request, patient_id: str):
    """ADA decision support for a patient (suggestion-only, physician confirms).
    Runs the ported rule engine over the patient's facts + active global rules."""
    patient = get_object_or_404(Patient, id=patient_id)
    facts = rule_engine.build_facts(patient)
    rules = ClinicalRule.objects.filter(is_active=True).order_by("priority", "code")
    result = rule_engine.grouped(facts, rules)
    result["disclaimer"] = "پیشنهاد — تأیید با پزشک"
    return result
