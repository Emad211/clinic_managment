import fitz

from app.graph import build_graph_for_document
from app.ingestion import ingest_document
from app.models import GraphEdge, GraphNode
from app.ontology import resolve_concept
from app.orchestrator import process_document
from app.parsing import parse_and_store
from app.serving import get_concept, get_neighbors
from sqlmodel import select


def _pdf(text):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), text, fontsize=11)
    raw = d.tobytes()
    d.close()
    return raw


def test_resolve_concept_crosswalk_and_entity_resolution(session):
    c1 = resolve_concept(session, "metformin")
    assert c1.canonical_name == "Metformin" and c1.atc == "A10BA02"
    # alias maps to the same canonical concept (entity resolution)
    c2 = resolve_concept(session, "dm")
    c3 = resolve_concept(session, "diabetes")
    assert c2.id == c3.id  # 'dm' alias -> 'diabetes' -> Diabetes mellitus
    assert len(session.exec(select(GraphNode)).all()) == 0  # resolve doesn't make nodes


def test_full_pipeline_builds_graph_and_serves(session):
    raw = _pdf("Diabetes and hypertension; start metformin and a statin.")
    doc, _ = ingest_document(session, title="ADA", raw=raw)
    parse_and_store(session, doc, raw)

    stats = process_document(session, doc)
    session.refresh(doc)
    assert doc.status == "graphed"
    assert stats["nodes"] >= 3 and stats["edges"] >= 1

    # nodes + provenance-bearing edges exist
    edges = session.exec(select(GraphEdge)).all()
    assert edges and edges[0].provenance.get("document_id") == str(doc.id)

    # MCP-style serving
    concept = get_concept(session, "metformin")
    assert concept and concept["atc"] == "A10BA02"
    neighbors = get_neighbors(session, "diabetes")
    names = {n["concept"] for n in neighbors}
    assert "Metformin" in names or "Hypertension" in names

    # idempotent: re-running a graphed document is a no-op
    assert process_document(session, doc)["skipped"] is True
