"""Financial reports (ACCOUNTING.md phase 5): revenue aggregation + the manager
reports page + CSV export."""
import pytest
from django.utils import timezone

from apps.accounting import reports, services
from apps.accounting.models import InsurancePlan, Tariff

pytestmark = pytest.mark.django_db


@pytest.fixture
def revenue_data(clinic, diabetic_patient):
    today = timezone.localdate()
    plan = InsurancePlan.objects.create(clinic=clinic, name="تأمین اجتماعی", patient_share_percent=30)
    vt = Tariff.objects.create(clinic=clinic, kind="visit", name="ویزیت", amount_rial=6_000_000)
    inv = services.open_invoice(clinic, diabetic_patient, today, "morning")
    services.add_visit(inv, tariff=vt, insurance_plan=plan)          # gross 6M, patient 1.8M
    services.add_procedure(inv, name="بخیه", amount_rial=2_000_000)  # gross 2M, self-pay
    return inv


def test_revenue_summary(revenue_data):
    today = timezone.localdate()
    s = reports.revenue_summary(today, today)
    assert s["total_gross"] == 8_000_000
    assert s["total_patient_share"] == 3_800_000        # 1.8M + 2.0M
    assert s["total_insurer_share"] == 4_200_000        # 6M*0.7
    assert s["by_kind"]["visit"]["gross"] == 6_000_000
    assert s["by_kind"]["procedure"]["gross"] == 2_000_000
    assert s["by_shift"]["morning"] == 8_000_000


def test_revenue_by_insurance(revenue_data):
    today = timezone.localdate()
    rows = {r["name"]: r for r in reports.revenue_by_insurance(today, today)}
    assert rows["تأمین اجتماعی"]["gross"] == 6_000_000
    assert rows["آزاد"]["gross"] == 2_000_000  # procedure had no plan -> self-pay bucket


def test_reports_page_manager_only(doctor_client):
    r = doctor_client.get("/reports/")
    assert r.status_code == 302 and "dashboard" in r["Location"]


def test_reports_page_renders(auth_client, revenue_data):
    r = auth_client.get("/reports/")
    body = r.content.decode()
    assert r.status_code == 200 and "گزارش‌های مالی" in body


def test_reports_csv_export(auth_client, revenue_data):
    today = timezone.localdate().isoformat()
    r = auth_client.get(f"/reports/export.csv?from={today}&to={today}")
    assert r.status_code == 200
    assert "text/csv" in r["Content-Type"]
    body = r.content.decode("utf-8")
    assert body.startswith("﻿")           # BOM for Excel
    assert "work_date" in body                  # header row
    assert revenue_data.patient.national_id in body


def test_dashboard_shows_revenue_for_manager(auth_client, revenue_data):
    body = auth_client.get("/dashboard/").content.decode()
    assert "درآمدِ امروز" in body
