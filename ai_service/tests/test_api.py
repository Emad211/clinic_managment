from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok" and r.json()["service"] == "ai_service"


def test_ingest_endpoint():
    with TestClient(app) as c:
        body = {"title": "ADA 2026", "text": "diabetes guideline", "year": 2026}
        r = c.post("/ingest", json=body)
        assert r.status_code == 200
        data = r.json()
        assert data["created"] is True and data["content_hash"] and data["status"] == "ingested"
        # re-ingest identical content -> deduped
        r2 = c.post("/ingest", json=body)
        assert r2.json()["created"] is False
