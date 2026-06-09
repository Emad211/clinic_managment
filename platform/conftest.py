"""Pytest config + shared fixtures.

Tests run on in-memory SQLite for speed and CI-independence (the GUC/RLS calls
no-op off PostgreSQL — actual RLS enforcement is covered separately by
`manage.py verify_rls` against real Postgres in CI). Must be set before Django
settings import.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")
# force the dev providers (no real SMS / gateway)
os.environ.pop("MEDIANA_API_KEY", None)
os.environ.pop("ZARINPAL_MERCHANT_ID", None)

import bcrypt  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def clinic(db):
    from apps.identity.models import Clinic
    return Clinic.objects.create(name="تست", slug="test", status="active")


@pytest.fixture
def manager(clinic):
    from apps.identity.models import AppUser
    return AppUser.objects.create(
        clinic=clinic, username="mgr", role="clinic_manager",
        password_hash=bcrypt.hashpw(b"secret", bcrypt.gensalt()),
        is_active=True,
    )


@pytest.fixture
def auth_client(manager):
    """A Django test client logged in as the manager (session set directly)."""
    from django.test import Client
    c = Client()
    s = c.session
    s["clinic_id"] = str(manager.clinic_id)
    s["user_id"] = str(manager.id)
    s.save()
    return c


@pytest.fixture
def diabetic_patient(clinic):
    """A poorly-controlled diabetic + a couple of global ADA rules so the engine
    fires (self-contained — does not depend on specialist.db)."""
    from apps.chronic.models import (
        ClinicalRule, Condition, PatientCondition, VitalReading,
    )
    from apps.patients.models import Patient

    p = Patient.objects.create(
        clinic=clinic, national_id="T1", first_name="ع", last_name="ر",
        birthdate="1960-01-01", phone_number="09120000000",
    )
    diabetes = Condition.objects.create(clinic=None, code="diabetes", name="دیابت")
    PatientCondition.objects.create(clinic=clinic, patient=p, condition=diabetes)
    VitalReading.objects.create(
        clinic=clinic, patient=p, indicator_key="hba1c", value=9, measured_at="2026-04-01T10:00:00Z",
    )
    ClinicalRule.objects.create(
        clinic=None, code="T2-DX-01", title="کلاسه‌بندی دیابت", category="glycemic",
        severity="warn", action_type="classify",
        trigger_json={"any": [{"var": "indicator.hba1c.latest", "op": ">=", "value": 6.5}]},
        recommendation="ارزیابی دیابت", is_active=True,
    )
    ClinicalRule.objects.create(
        clinic=None, code="REF-ONLY", title="بدون تریگر", category="x",
        trigger_json={}, is_active=True,  # reference-only, must NOT fire
    )
    return p


@pytest.fixture
def followup(diabetic_patient):
    from apps.chronic.models import FollowupTask
    return FollowupTask.objects.create(
        clinic=diabetic_patient.clinic, patient=diabetic_patient,
        item_key="a1c", title="آزمایش HbA1c", due_date="2026-05-01", status="open",
    )
