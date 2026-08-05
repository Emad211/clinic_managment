from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


@pytest.fixture()
def patient_workspace_app(tmp_path):
    from src.adapters.sqlite import core
    from src.adapters.sqlite.core import get_db
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "patient-workspace.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "patient-workspace-test",
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
               VALUES ('PWV2000001', 'بیمار فضای کاری', '09120000009',
                       'pytest', '2026-08-05 08:00:00',
                       '2026-08-05 08:00:00')"""
        ).lastrowid
    )
    db.commit()

    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}

    yield app, client, patient_id

    context.pop()
    core._initialized = False


def test_patient_detail_and_workspace_assets_are_served(patient_workspace_app):
    _app, client, patient_id = patient_workspace_app

    page = client.get(f"/patients/{patient_id}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'class="patient-hero"' in html
    assert 'class="tabbar"' in html
    assert "اولویت بعدی پرونده" in html
    assert "/static/js/automation-v1.js" in html

    for asset in (
        "/static/js/patient-workspace-automation-v2.js",
        "/static/js/patient-workspace-context-v2.js",
        "/static/css/patient-workspace-automation-v2.css",
    ):
        response = client.get(asset)
        assert response.status_code == 200, asset
        assert response.data


def test_workspace_uses_exact_five_approved_tabs_and_no_sixth_destination():
    workspace = read("src/static/js/patient-workspace-automation-v2.js")
    expected = [
        ("summary", "خلاصه"),
        ("actions", "اقدامات"),
        ("clinical-data", "داده‌های بالینی"),
        ("medications", "دارو و نسخه"),
        ("encounters-documents", "ویزیت‌ها و اسناد"),
    ]
    for name, label in expected:
        assert workspace.count(f"name: '{name}', label: '{label}'") == 1
    assert workspace.count("name: '") == 5
    assert "paneDefinitions" in workspace
    assert "newTabbar.setAttribute('role', 'tablist')" in workspace
    assert "button.role = 'tab'" in workspace
    assert "pane.setAttribute('role', 'tabpanel')" in workspace


def test_workspace_reuses_existing_nodes_and_preserves_backend_contracts():
    workspace = read("src/static/js/patient-workspace-automation-v2.js")
    source = read("src/templates/patients/detail.html")
    consent = read("src/templates/patients/_sms_consent.html")

    for marker in (
        "followupsCard",
        "quickVitalsCard",
        "careTimelineCard",
        "encounterGrid",
        "consent",
        "inviteForm",
    ):
        assert marker in workspace
    assert "appendChild(followupsCard)" in workspace
    assert "appendChild(quickVitalsCard)" in workspace
    assert "appendChild(careTimelineCard)" in workspace
    assert "appendChild(encounterGrid)" in workspace
    assert "appendChild(consent)" in workspace
    assert "grid.appendChild(inviteForm)" in workspace

    for endpoint in (
        "vitals.add_reading",
        "patients.add_medication",
        "patients.change_dose",
        "patients.stop_medication",
        "patients.prescription_free",
        "patients.invite_patient",
        "vitals.add_lab",
    ):
        assert endpoint in source
    assert "patients.sms_consent_update" in consent
    assert "confirm('وضعیت دریافت این نوع پیام برای بیمار تغییر کند؟')" in consent

    # The composer itself never persists or invents patient data.
    assert "fetch(" not in workspace
    assert "localStorage" not in workspace
    assert "sessionStorage" not in workspace
    assert "FormData" not in workspace


def test_actions_tab_contains_only_existing_safe_destinations():
    workspace = read("src/static/js/patient-workspace-automation-v2.js")
    for label in (
        "ثبت نوبت",
        "ثبت شاخص",
        "کارهای این بیمار",
        "بررسی اختلاف اطلاعات",
        "کارت بیمار و یادآوری",
        "افزودن دعوت پیامکی",
    ):
        assert label in workspace
    assert "currentPatientPath}/reconciliation" in workspace
    assert "url.searchParams.set('view', 'all')" in workspace
    assert "url.searchParams.set('q', patientName)" in workspace
    assert "closestActionLink(/appointments\\/new/)" in workspace
    assert "closestActionLink(/\\/card" in workspace


def test_legacy_hashes_resolve_to_the_five_tab_workspace():
    workspace = read("src/static/js/patient-workspace-automation-v2.js")
    aliases = {
        "cockpit": "summary",
        "worklist": "actions",
        "appointment": "actions",
        "trends": "clinical-data",
        "record": "clinical-data",
        "labs": "clinical-data",
        "vitals": "clinical-data",
        "meds": "medications",
    }
    for old, new in aliases.items():
        assert f"{old}: '{new}'" in workspace
    assert "targetElement.closest('.patient-workspace-pane')" in workspace
    assert "history.replaceState(null, '', `#${name}`)" in workspace


def test_tab_context_memory_persists_only_the_ui_tab_name():
    context = read("src/static/js/patient-workspace-context-v2.js")
    loader = read("src/static/js/automation-v1.js")

    assert "patient-workspace-context-v2.js" in loader
    assert "module.addEventListener('load'" in loader
    assert "clinic.patient-workspace.active-tab" in context
    assert "sessionStorage.setItem(STORAGE_KEY, name)" in context
    assert "sessionStorage.getItem(STORAGE_KEY)" in context
    assert "workspace_tab" in context
    assert "qsa('form', document)" in context
    assert "persist(selectedTab())" in context

    # Context memory is deliberately limited to one of five fixed strings.
    assert "patient_id" not in context.lower()
    assert "patient-link" not in context.lower()
    assert "national" not in context.lower()
    assert "phone" not in context.lower()
    assert "fetch(" not in context
    assert "localStorage" not in context
    assert "FormData" not in context


def test_workspace_keyboard_sticky_and_mobile_contracts():
    workspace = read("src/static/js/patient-workspace-automation-v2.js")
    css = read("src/static/css/patient-workspace-automation-v2.css")
    loader = read("src/static/js/automation-v1.js")

    assert "setupPatientWorkspaceModule" in loader
    assert "if (!qs('.patient-hero') || !qs('.tabbar[role=\"tablist\"]')) return" in loader
    assert "module.dataset.patientWorkspaceV2 = 'true'" in loader
    assert "context.dataset.patientWorkspaceContextV2 = 'true'" in loader
    assert "setupPatientWorkspaceModule();" in loader

    assert "['ArrowRight', 'ArrowLeft', 'Home', 'End']" in workspace
    assert "button.setAttribute('aria-selected'" in workspace
    assert "button.tabIndex = selected ? 0 : -1" in workspace
    assert "hero.classList.toggle('is-compact'" in workspace
    assert "requestAnimationFrame(syncCompactHeader)" in workspace

    for contract in (
        ".patient-hero{",
        "position:sticky",
        ".patient-workspace-tabs",
        ".patient-workspace-action-grid",
        "@media(max-width:900px)",
        "@media(max-width:700px)",
        "@media(max-width:420px)",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert contract in css


def test_workspace_javascript_is_syntactically_valid_when_node_is_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed in this test environment")
    for relative in (
        "src/static/js/automation-v1.js",
        "src/static/js/patient-workspace-automation-v2.js",
        "src/static/js/patient-workspace-context-v2.js",
    ):
        result = subprocess.run(
            [node, "--check", str(ROOT / relative)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stderr
