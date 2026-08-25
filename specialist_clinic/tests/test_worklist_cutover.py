"""Worklist cutover contract — unified reads ungated, legacy page shimmed.

Owner-approved cutover (2026-08-24): the unified work center is the single
canonical follow-up surface.  GET index/detail no longer require
FOLLOWUP_UNIFIED_WORKLIST_READONLY; the legacy ``/followups/`` page is gone
and its route redirects (302) to the unified index.  Action routes keep their
own flag gates (still default OFF → 404).
"""

import sys
from pathlib import Path

import pytest

SPECIALIST_ROOT = Path(__file__).resolve().parents[1]
if str(SPECIALIST_ROOT) not in sys.path:
    sys.path.insert(0, str(SPECIALIST_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from src.app import create_app  # noqa: E402


@pytest.fixture()
def cutover_app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "cutover.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "cutover-test",
        }
    )
    app.config["TESTING"] = True
    with app.app_context():
        yield app


def _login(client):
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert response.status_code in {302, 303}


def test_unified_index_and_detail_reachable_without_any_flag(cutover_app):
    client = cutover_app.test_client()
    _login(client)
    assert client.get("/followups/unified/").status_code == 200
    # Missing episode 404s from the handler itself — the index assertion
    # above carries the ungating proof (L1 removed the read gate).
    assert client.get("/followups/unified/fuep_none").status_code == 404


def test_action_routes_still_gated_by_their_own_flags(cutover_app):
    client = cutover_app.test_client()
    _login(client)
    assert client.post("/followups/unified/fuep_none/claim").status_code == 404
    assert client.post("/followups/unified/fuep_none/route").status_code == 404
    assert (
        client.post("/followups/unified/fuep_none/contact").status_code == 404
    )


def test_legacy_worklist_url_redirects_to_unified(cutover_app):
    client = cutover_app.test_client()
    _login(client)
    response = client.get("/followups/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/followups/unified/")
    followed = client.get("/followups/", follow_redirects=True)
    assert followed.status_code == 200


def test_patient_detail_has_zero_legacy_worklist_references(cutover_app):
    client = cutover_app.test_client()
    _login(client)
    db_path = cutover_app.config["DATABASE_PATH"]
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO patient_links (national_id, full_name) VALUES (?, ?)",
        ("CUT0001", "بیمار برش"),
    )
    conn.commit()
    patient_id = conn.execute(
        "SELECT id FROM patient_links WHERE national_id='CUT0001'"
    ).fetchone()[0]
    conn.close()
    page = client.get(f"/patients/{patient_id}")
    assert page.status_code == 200
    assert b"followups.worklist" not in page.get_data()


def test_worklist_template_file_is_gone():
    assert not (SPECIALIST_ROOT / "src/templates/followups/worklist.html").exists()
