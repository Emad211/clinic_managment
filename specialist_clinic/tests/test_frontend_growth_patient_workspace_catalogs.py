from __future__ import annotations

import pytest
from flask import url_for


@pytest.fixture()
def catalog_workspace_app(tmp_path, monkeypatch):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.adapters.sqlite.drug_catalog_repo import DrugCatalogRepository
    from src.adapters.sqlite.lab_catalog_repo import LabCatalogRepository
    from src.app import create_app
    from src.services.clinical_engine.facade import ClinicalEngineReadOnlyFacade

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "catalog-workspace.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "catalog-workspace-test",
            "FOLLOWUP_UNIFIED_WORKLIST_READONLY": True,
            "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS": True,
        }
    )
    context = app.app_context()
    context.push()
    monkeypatch.setattr(
        ClinicalEngineReadOnlyFacade,
        "patient_detail",
        lambda self, patient_link_id: None,
    )
    db = get_db()
    patient_id = int(
        db.execute(
            """INSERT INTO patient_links
               (national_id, full_name, phone_number, enrolled_by,
                enrolled_at, updated_at)
               VALUES ('CATALOG-P-001', 'بیمار کاتالوگ', '09125555555',
                       'pytest', '2026-08-06 08:00:00',
                       '2026-08-06 08:00:00')"""
        ).lastrowid
    )
    db.commit()

    drug_id = DrugCatalogRepository().add(
        generic_fa="متفورمین استاندارد",
        drug_class_key="biguanide",
        standard_doses=["500 mg", "1000 mg"],
        is_active=1,
    )
    LabCatalogRepository().upsert(
        test_key="hba1c_growth_test",
        name_fa="هموگلوبین گلیکوزیله",
        unit="%",
        ref_low=4.0,
        ref_high=5.6,
        category="diabetes",
        display_order=1,
        is_active=1,
    )
    admin = db.execute(
        "SELECT id, username FROM users WHERE username='admin'"
    ).fetchone()
    yield {
        "app": app,
        "db": db,
        "patient_id": patient_id,
        "drug_id": int(drug_id),
        "admin": admin,
    }
    context.pop()
    core._initialized = False


def _client(fixture):
    client = fixture["app"].test_client()
    with client.session_transaction() as session:
        session["user_id"] = int(fixture["admin"]["id"])
    return client


def test_meds_tab_uses_catalog_identity_not_free_text(catalog_workspace_app):
    client = _client(catalog_workspace_app)
    response = client.get(
        url_for(
            "patient_workspace.detail",
            pid=catalog_workspace_app["patient_id"],
            tab="meds",
        )
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "patient_workspace_mutations.add_medication" not in html
    assert "/workspace/medications" in html
    assert 'name="drug_catalog_id"' in html
    assert 'name="drug_name"' not in html
    assert "متفورمین استاندارد" in html
    assert "patient-workspace-catalogs.js" in html


def test_valid_catalog_medication_uses_canonical_name_class_and_dose(
    catalog_workspace_app,
):
    client = _client(catalog_workspace_app)
    patient_id = catalog_workspace_app["patient_id"]
    response = client.post(
        url_for("patient_workspace_mutations.add_medication", pid=patient_id),
        data={
            "drug_catalog_id": str(catalog_workspace_app["drug_id"]),
            "dose_choice": "500 mg",
            "schedule": "روزی دو بار",
            "refill_interval": "30",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=meds"
    )
    row = catalog_workspace_app["db"].execute(
        """SELECT drug_name,drug_class,dose,drug_catalog_id
           FROM patient_medications WHERE patient_link_id=?""",
        (patient_id,),
    ).fetchone()
    assert row["drug_name"] == "متفورمین استاندارد"
    assert row["drug_class"] == "biguanide"
    assert row["dose"] == "500 mg"
    assert int(row["drug_catalog_id"]) == catalog_workspace_app["drug_id"]


def test_invalid_standard_dose_returns_422_without_creating_medication(
    catalog_workspace_app,
):
    client = _client(catalog_workspace_app)
    patient_id = catalog_workspace_app["patient_id"]
    response = client.post(
        url_for("patient_workspace_mutations.add_medication", pid=patient_id),
        data={
            "drug_catalog_id": str(catalog_workspace_app["drug_id"]),
            "dose_choice": "250 mg",
            "schedule": "شب‌ها",
        },
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 422
    assert "دوز انتخاب‌شده با فهرست استاندارد این دارو سازگار نیست" in html
    assert "شب‌ها" in html
    assert catalog_workspace_app["db"].execute(
        "SELECT COUNT(*) FROM patient_medications WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 0


def test_valid_catalog_lab_overrides_name_unit_and_reference_range(
    catalog_workspace_app,
):
    client = _client(catalog_workspace_app)
    patient_id = catalog_workspace_app["patient_id"]
    response = client.post(
        url_for("patient_workspace_mutations.add_lab", pid=patient_id),
        data={
            "test_key": "hba1c_growth_test",
            "value": "6.8",
            "notes": "کنترل دوره‌ای",
        },
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/patients/{patient_id}/workspace?tab=clinical"
    )
    row = catalog_workspace_app["db"].execute(
        """SELECT test_key,test_name,value,unit,ref_low,ref_high
           FROM lab_results WHERE patient_link_id=?""",
        (patient_id,),
    ).fetchone()
    assert row["test_key"] == "hba1c_growth_test"
    assert row["test_name"] == "هموگلوبین گلیکوزیله"
    assert float(row["value"]) == 6.8
    assert row["unit"] == "%"
    assert float(row["ref_low"]) == 4.0
    assert float(row["ref_high"]) == 5.6


def test_invalid_lab_keeps_submitted_value_and_creates_nothing(
    catalog_workspace_app,
):
    client = _client(catalog_workspace_app)
    patient_id = catalog_workspace_app["patient_id"]
    response = client.post(
        url_for("patient_workspace_mutations.add_lab", pid=patient_id),
        data={
            "test_key": "missing-test",
            "value": "7.1",
            "notes": "نمونه نامعتبر",
        },
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 422
    assert "یک آزمایش فعال از فهرست انتخاب کنید" in html
    assert "7.1" in html
    assert "نمونه نامعتبر" in html
    assert catalog_workspace_app["db"].execute(
        "SELECT COUNT(*) FROM lab_results WHERE patient_link_id=?",
        (patient_id,),
    ).fetchone()[0] == 0


def test_catalog_javascript_has_no_persistence_or_network_mutation():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (
        root / "src/static/js/patient-workspace-catalogs.js"
    ).read_text(encoding="utf-8")

    assert "data-drug-catalog-select" in source
    assert "data-lab-catalog-select" in source
    assert "fetch(" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "FormData" not in source
