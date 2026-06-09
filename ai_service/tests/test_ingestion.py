from sqlmodel import select

from app.ingestion import content_hash, ingest_document
from app.models import SourceDocument


def test_content_hash_stable():
    assert content_hash(b"abc") == content_hash(b"abc")
    assert content_hash(b"abc") != content_hash(b"abd")


def test_ingest_registers_document(session):
    doc, created = ingest_document(session, title="ADA 2026", raw=b"guideline text")
    assert created and doc.status == "ingested" and doc.content_hash


def test_reingest_is_deduped(session):
    doc, _ = ingest_document(session, title="ADA 2026", raw=b"same text")
    doc2, created2 = ingest_document(session, title="different title", raw=b"same text")
    assert not created2 and doc2.id == doc.id  # dedup by content hash
    assert len(session.exec(select(SourceDocument)).all()) == 1


def test_distinct_content_makes_new_row(session):
    ingest_document(session, title="A", raw=b"x")
    ingest_document(session, title="B", raw=b"y")
    assert len(session.exec(select(SourceDocument)).all()) == 2
