from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def patient_workspace_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.drug_catalog_repo import DrugCatalogRepository
    from src.adapters.sqlite.flags_repo import ClinicalFlagsRepository
    from src.adapters.sqlite.lab_catalog_repo import LabCatalogRepository
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "patient-workspace-v2.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "patient-workspace-v2-test",
        }
    )
    context = app.app_context()
    context.push()
    db = get_db()

    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, enrolled_by,
                enrolled_at, updated_at)
               VALUES ('PWS2000001', 'بیمار ورک‌اسپیس تست', '09120000001', 'pytest',
                       '2026-08-08 09:00:00', '2026-08-08 09:00:00')"""
        ).lastrowid
    )
    db.commit()

    LabCatalogRepository().upsert(
        test_key="pytest_workspace_lab",
        name_fa="آزمایش استاندارد ورک‌اسپیس",
        unit="mg/dL",
        ref_low=10,
        ref_high=20,
        category="other",
        display_order=1,
        is_active=1,
    )

    drug_classes = ClinicalFlagsRepository().drug_classes()
    assert drug_classes, "test database must seed at least one drug class"
    drug_class_key = drug_classes[0]["class_key"]
    DrugCatalogRepository().add(
        generic_fa="داروی استاندارد ورک‌اسپیس",
        drug_class_key=drug_class_key,
        standard_doses=["5 mg", "10 mg"],
    )

    admin = db.execute(
        "SELECT id, username FROM users WHERE username='admin'"
    ).fetchone()

    yield {
        "app": app,
        "db": db,
        "admin": admin,
        "patient_id": patient_id,
        "drug_class_key": drug_class_key,
    }

    context.pop()
    core._initialized = False


def client_for(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def test_patient_detail_redirects_to_native_workspace_and_all_tabs_render(
    patient_workspace_app,
):
    client = client_for(patient_workspace_app)
    patient_id = patient_workspace_app["patient_id"]

    legacy = client.get(f"/patients/{patient_id}", follow_redirects=False)
    assert legacy.status_code in {302, 303}
    assert legacy.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=summary"
    )

    markers = {
        "summary": "اقدام بعدی پیشنهادی پرونده",
        "actions": "ثبت سریع شاخص‌ها",
        "clinical": "آزمایش‌ها",
        "meds": "داروهای بیمار",
        "encounters": "تاریخچه مراقبت",
    }
    for tab, marker in markers.items():
        response = client.get(f"/patients/{patient_id}/workspace?tab={tab}")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert marker in html
        assert f"tab={tab}" in html
        assert 'aria-current="page"' in html


def test_workspace_renders_catalog_bound_lab_and_medication_controls(
    patient_workspace_app,
):
    client = client_for(patient_workspace_app)
    patient_id = patient_workspace_app["patient_id"]

    clinical = client.get(f"/patients/{patient_id}/workspace?tab=clinical")
    clinical_html = clinical.get_data(as_text=True)
    assert clinical.status_code == 200
    assert 'name="catalog_test_key"' in clinical_html
    assert 'value="pytest_workspace_lab"' in clinical_html
    assert "آزمایش استاندارد ورک‌اسپیس" in clinical_html
    assert 'name="test_name"' not in clinical_html
    assert 'name="unit"' not in clinical_html

    meds = client.get(f"/patients/{patient_id}/workspace?tab=meds")
    meds_html = meds.get_data(as_text=True)
    assert meds.status_code == 200
    assert 'id="patientWorkspaceDrugCatalog"' in meds_html
    assert 'id="workspace-drug-name" name="drug_name" required' in meds_html
    assert "داروی استاندارد ورک‌اسپیس" in meds_html
    assert 'data-drug-class=' in meds_html
    assert 'list="workspace-drug-dose-options"' in meds_html
    assert "/static/js/patient-workspace-catalogs-v2.js" in meds_html


def test_catalog_lab_post_uses_server_canonical_identity_and_returns_to_clinical_tab(
    patient_workspace_app,
):
    client = client_for(patient_workspace_app)
    patient_id = patient_workspace_app["patient_id"]

    response = client.post(
        f"/vitals/{patient_id}/lab/add",
        data={
            "catalog_test_key": "pytest_workspace_lab",
            "value": "15",
            "taken_date": "",
            "workspace_tab": "clinical",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=clinical"
    )
    row = patient_workspace_app["db"].execute(
        """SELECT test_name, test_key, value, unit, ref_low, ref_high
           FROM lab_results
           WHERE patient_link_id=? AND test_key='pytest_workspace_lab'
           ORDER BY id DESC LIMIT 1""",
        (patient_id,),
    ).fetchone()
    assert row
    assert row["test_name"] == "آزمایش استاندارد ورک‌اسپیس"
    assert row["unit"] == "mg/dL"
    assert row["ref_low"] == 10
    assert row["ref_high"] == 20
    assert row["value"] == 15


def test_catalog_medication_selection_keeps_workspace_context(patient_workspace_app):
    client = client_for(patient_workspace_app)
    patient_id = patient_workspace_app["patient_id"]
    drug_class_key = patient_workspace_app["drug_class_key"]

    response = client.post(
        f"/patients/{patient_id}/medication/add",
        data={
            "drug_name": "داروی استاندارد ورک‌اسپیس",
            "drug_class": drug_class_key,
            "dose": "5 mg",
            "schedule": "روزی یک بار",
            "refill_interval": "30",
            "workspace_tab": "meds",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=meds"
    )
    row = patient_workspace_app["db"].execute(
        """SELECT drug_name, drug_class, dose, schedule
           FROM patient_medications
           WHERE patient_link_id=? ORDER BY id DESC LIMIT 1""",
        (patient_id,),
    ).fetchone()
    assert row
    assert row["drug_name"] == "داروی استاندارد ورک‌اسپیس"
    assert row["drug_class"] == drug_class_key
    assert row["dose"] == "5 mg"
    assert row["schedule"] == "روزی یک بار"


def test_catalog_enhancement_is_progressive_and_does_not_fake_persistence():
    script = (
        ROOT / "src/static/js/patient-workspace-catalogs-v2.js"
    ).read_text(encoding="utf-8")
    clinical = (
        ROOT / "src/templates/patients/workspace/_clinical.html"
    ).read_text(encoding="utf-8")
    meds = (
        ROOT / "src/templates/patients/workspace/_meds.html"
    ).read_text(encoding="utf-8")

    assert "JSON.parse" in script
    assert "replaceChildren" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "fetch(" not in script
    assert 'name="catalog_test_key"' in clinical
    assert 'name="drug_name" required' in meds
    assert "drug_catalog|tojson" in meds
