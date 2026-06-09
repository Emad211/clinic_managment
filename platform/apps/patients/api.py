"""Patients API router (django-ninja).

Queries are automatically tenant-filtered by PostgreSQL RLS once
TenantMiddleware has set ``app.current_clinic``. With no tenant context
(e.g. unauthenticated dev request) RLS returns zero rows — fail-closed.
"""

from typing import List, Optional

from django.shortcuts import get_object_or_404
from ninja import ModelSchema, Router

from .models import Patient

router = Router(tags=["patients"])


class PatientOut(ModelSchema):
    class Meta:
        model = Patient
        fields = [
            "id",
            "national_id",
            "first_name",
            "last_name",
            "phone_number",
            "gender",
            "birthdate",
            "insurance_type",
            "wallet_balance",
            "is_active",
            "created_at",
        ]


@router.get("/", response=List[PatientOut])
def list_patients(request, q: Optional[str] = None, limit: int = 50):
    qs = Patient.objects.filter(is_active=True)
    if q:
        qs = qs.filter(national_id__icontains=q)
    return list(qs.order_by("last_name", "first_name")[: min(limit, 200)])


@router.get("/{patient_id}", response=PatientOut)
def get_patient(request, patient_id: str):
    return get_object_or_404(Patient, id=patient_id)
