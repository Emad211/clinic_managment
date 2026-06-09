"""Chronic-care API router (django-ninja). Read-only slices for the wedge UI:
recent vitals and the open follow-up worklist. Tenant-filtered by RLS."""

from typing import List, Optional

from ninja import ModelSchema, Router

from .models import FollowupTask, VitalReading

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
