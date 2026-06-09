import fitz
from sqlmodel import select

from app.ingestion import ingest_document
from app.models import Claim, ReviewQueue
from app.orchestrator import process_document, verify_and_route
from app.parsing import parse_and_store


def _pdf(text):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), text, fontsize=11)
    raw = d.tobytes()
    d.close()
    return raw


def test_orchestrator_end_to_end(session):
    raw = _pdf("Diabetes and hypertension; start metformin and a statin.")
    doc, _ = ingest_document(session, title="ADA", raw=raw)
    parse_and_store(session, doc, raw)

    stats = process_document(session, doc)
    assert stats["claims"] > 0 and stats["verified"] > 0
    session.refresh(doc)
    assert doc.status == "graphed"  # full pipeline: extract -> verify -> graph

    # idempotent: re-processing a finished document is a no-op
    assert process_document(session, doc)["skipped"] is True


def test_gate_routes_ungrounded_claim_to_review(make_chunk, session):
    _doc, ch = make_chunk("Diabetes management guideline.")
    bad = Claim(
        chunk_id=ch.id, claim_type="terminology",
        payload={"term": "leukemia"}, source_anchor={"snippet": "leukemia"},
        status="extracted",
    )
    session.add(bad)
    session.commit()
    session.refresh(bad)

    _v, needs_review = verify_and_route(session, bad, ch.content)
    assert needs_review is True
    queued = session.exec(select(ReviewQueue).where(ReviewQueue.claim_id == bad.id)).all()
    assert len(queued) == 1 and queued[0].reason == "not_found"
