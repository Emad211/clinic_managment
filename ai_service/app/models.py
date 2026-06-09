"""Knowledge data model (SQLModel) — the source-of-truth tables for the pipeline
(docs/PIPELINE.md §4). On PostgreSQL these live in a `knowledge` schema with no
RLS (global knowledge, not per-tenant). M1 covers source_document /
document_chunk / claim; embeddings (pgvector), ontology, and graph arrive in
later milestones.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceDocument(SQLModel, table=True):
    __tablename__ = "source_document"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    title: str = ""
    publisher: str = ""
    year: Optional[int] = None
    evidence_level: str = ""
    content_hash: str = Field(index=True, unique=True)  # dedup / cache / versioning
    status: str = "ingested"  # ingested|parsed|chunked|extracted|verified|...|needs_review
    meta: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunk"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="source_document.id", index=True)
    ordinal: int = 0
    page_anchor: Optional[int] = None  # anchor used by the verification gate
    kind: str = "prose"  # prose|table|figure_caption
    content: str = ""
    structured: dict = Field(default_factory=dict, sa_column=Column(JSON))
    domain: str = ""
    evidence_level: str = ""


class Claim(SQLModel, table=True):
    __tablename__ = "claim"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    chunk_id: uuid.UUID = Field(foreign_key="document_chunk.id", index=True)
    claim_type: str = ""  # terminology|clinical_fact|drug|education
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    source_anchor: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "extracted"  # extracted|verified|partial|not_found|conflicting|needs_review
    confidence: Optional[float] = None
    version: int = 1
    created_at: datetime = Field(default_factory=_now)
