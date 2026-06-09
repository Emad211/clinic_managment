"""Accounting generalisation backbone: clinic type, per-clinic insurance catalog,
and the editable defaults seeder (porting the legacy single-clinic app into a
multi-tenant product usable by any درمانگاه / کلینیک / مطب)."""
import pytest
from django.core.management import call_command

from apps.accounting.models import InsurancePlan, Tariff
from apps.identity.models import Clinic

pytestmark = pytest.mark.django_db


def test_clinic_type_defaults_to_polyclinic(clinic):
    assert clinic.clinic_type == "polyclinic"  # matches the legacy درمانگاه


def test_bootstrap_sets_clinic_type():
    call_command(
        "bootstrap_clinic", "--name", "Office", "--slug", "matab",
        "--admin-username", "doc", "--admin-password", "x", "--type", "office",
    )
    assert Clinic.objects.get(slug="matab").clinic_type == "office"


def test_seed_defaults_is_idempotent_and_type_aware(clinic):
    # polyclinic -> full catalog incl. nursing + consumables
    call_command("seed_accounting_defaults", "--clinic-slug", clinic.slug)
    plans = InsurancePlan.objects.filter(clinic=clinic).count()
    tariffs = Tariff.objects.filter(clinic=clinic).count()
    assert plans == 5 and tariffs >= 12
    assert InsurancePlan.objects.filter(clinic=clinic, name="آزاد", patient_share_percent=100).exists()
    assert Tariff.objects.filter(clinic=clinic, kind="nursing").exists()  # درمانگاه has nursing

    # re-run: no duplicates (idempotent)
    call_command("seed_accounting_defaults", "--clinic-slug", clinic.slug)
    assert InsurancePlan.objects.filter(clinic=clinic).count() == plans
    assert Tariff.objects.filter(clinic=clinic).count() == tariffs


def test_office_gets_lean_catalog():
    office = Clinic.objects.create(name="مطب", slug="m1", clinic_type="office")
    call_command("seed_accounting_defaults", "--clinic-slug", "m1")
    # a single-doctor office gets visits + procedures, but no nursing station
    assert Tariff.objects.filter(clinic=office, kind="visit").exists()
    assert not Tariff.objects.filter(clinic=office, kind="nursing").exists()
    assert not Tariff.objects.filter(clinic=office, kind="consumable").exists()


def test_insurance_plan_unique_per_clinic(clinic):
    InsurancePlan.objects.create(clinic=clinic, name="آزاد")
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        InsurancePlan.objects.create(clinic=clinic, name="آزاد")
