"""Full-pipeline HTTP tests: a document goes in, a queryable knowledge graph
comes out — all over the API."""
import fitz
from fastapi.testclient import TestClient

from app.main import app


def test_process_text_document_end_to_end():
    with TestClient(app) as c:
        r = c.post("/documents/process", json={
            "title": "ADA-text", "text": "Diabetes: start metformin and a statin.",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "graphed" and body["stats"]["claims"] > 0

        # the knowledge graph is now queryable via the MCP-style endpoint
        concept = c.get("/knowledge/concept", params={"term": "metformin"}).json()
        assert concept.get("atc") == "A10BA02"


def test_upload_pdf_runs_full_pipeline():
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), "Hypertension: use an ACE inhibitor or ARB.", fontsize=11)
    raw = d.tobytes()
    d.close()

    with TestClient(app) as c:
        r = c.post(
            "/documents/upload",
            files={"file": ("guideline.pdf", raw, "application/pdf")},
            data={"title": "HTN"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "graphed"

        neighbors = c.get("/knowledge/neighbors", params={"term": "hypertension"}).json()
        assert "neighbors" in neighbors
