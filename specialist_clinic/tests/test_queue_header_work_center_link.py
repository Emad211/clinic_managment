"""Doctor queue header carries exactly one ghost link to the work center."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def app_ctx(tmp_path):
    from src.adapters.sqlite import core
    from src.app import create_app

    core._initialized = False
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "queue-header-link.db"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "SECRET_KEY": "queue-header-link-test",
        }
    )
    context = app.app_context()
    context.push()
    yield app
    context.pop()
    core._initialized = False


def _login(app):
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    return client


def test_doctor_queue_header_links_to_work_center_exactly_once(app_ctx):
    client = _login(app_ctx)

    response = client.get("/doctor-queue/")
    assert response.status_code == 200

    page = response.get_data(as_text=True)
    # url_for() resolves the endpoint to its concrete URL in rendered HTML.
    work_center_url = "/followups/unified/"
    assert page.count(work_center_url) >= 1
    assert "مرکز کارها" in page

    header = page.split('<header class="auto-page-header">', 1)[1].split("</header>", 1)[0]
    assert header.count(work_center_url) == 1
    assert header.count("مرکز کارها") == 1
    assert 'class="btn btn-ghost"' in header
    assert "#i-list-checks" in header
