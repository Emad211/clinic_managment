"""Ingestion & Registry (pipeline layer 1).

Computes a content hash (the basis of dedup / cache / incremental updates /
versioning) and registers the document. Re-ingesting identical content is a no-op
(returns the existing row) — this is how the hash-based cache avoids re-spending
on unchanged sources.
"""

import hashlib
from typing import Optional, Tuple

from sqlmodel import Session, select

from .models import SourceDocument


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest_document(
    session: Session,
    *,
    title: str,
    raw: bytes,
    publisher: str = "",
    year: Optional[int] = None,
    evidence_level: str = "",
    meta: Optional[dict] = None,
) -> Tuple[SourceDocument, bool]:
    """Register a source document. Returns (document, created). ``created`` is
    False when the content hash already exists (dedup)."""
    h = content_hash(raw)
    existing = session.exec(
        select(SourceDocument).where(SourceDocument.content_hash == h)
    ).first()
    if existing:
        return existing, False

    doc = SourceDocument(
        title=title, content_hash=h, publisher=publisher, year=year,
        evidence_level=evidence_level, status="ingested", meta=meta or {},
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc, True
