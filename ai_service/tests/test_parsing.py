import fitz
from sqlmodel import select

from app.ingestion import ingest_document
from app.models import DocumentChunk
from app.parsing import parse_and_store, parse_pdf


def _make_pdf(pages):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    raw = doc.tobytes()
    doc.close()
    return raw


def test_parse_pdf_prose_and_page_anchors():
    raw = _make_pdf([
        "First page about diabetes HbA1c target.",
        "Second page about hypertension management.",
    ])
    chunks = parse_pdf(raw)
    prose = [c for c in chunks if c["kind"] == "prose"]
    assert len(prose) == 2
    assert prose[0]["page_anchor"] == 1 and "diabetes" in prose[0]["content"]
    assert prose[1]["page_anchor"] == 2 and "hypertension" in prose[1]["content"]
    # ordinals are contiguous (orchestrator relies on stable ordering)
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))


def test_parse_and_store_persists_and_advances_status(session):
    raw = _make_pdf(["Guideline page one.", "Guideline page two."])
    doc, _ = ingest_document(session, title="ADA", raw=raw)
    n = parse_and_store(session, doc, raw)
    assert n >= 2

    stored = session.exec(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    ).all()
    assert len(stored) == n
    assert {c.page_anchor for c in stored} == {1, 2}
    session.refresh(doc)
    assert doc.status == "parsed"
