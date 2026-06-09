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


class Verification(SQLModel, table=True):
    """Output of the critical verification gate (layer 5)."""

    __tablename__ = "verification"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    claim_id: uuid.UUID = Field(foreign_key="claim.id", index=True)
    verdict: str = ""  # verified|partial|not_found|conflicting
    confidence: Optional[float] = None
    supporting_snippet: str = ""
    model: str = ""
    created_at: datetime = Field(default_factory=_now)


class ReviewQueue(SQLModel, table=True):
    """Human-review backlog — a first-class component (safety-critical or
    gate-failed claims land here)."""

    __tablename__ = "review_queue"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    claim_id: uuid.UUID = Field(foreign_key="claim.id", index=True)
    reason: str = ""
    assigned_to: str = ""
    resolved: bool = False
    created_at: datetime = Field(default_factory=_now)


class OntologyConcept(SQLModel, table=True):
    """Canonical internal concept + crosswalk to ICD-11/MeSH/INN/ATC (layer 6).
    (SNOMED/UMLS/RxNorm avoided — sanctions/access; ICD-11+MeSH+INN+ATC base.)"""

    __tablename__ = "ontology_concept"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    canonical_name: str = Field(index=True)
    icd11: str = ""
    mesh: str = ""
    inn: str = ""
    atc: str = ""
    aliases: dict = Field(default_factory=dict, sa_column=Column(JSON))


class GraphNode(SQLModel, table=True):
    __tablename__ = "graph_node"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    concept_id: uuid.UUID = Field(foreign_key="ontology_concept.id", index=True)
    kind: str = "concept"
    props: dict = Field(default_factory=dict, sa_column=Column(JSON))


class GraphEdge(SQLModel, table=True):
    """Edge with provenance. Conflicts are NOT overwritten — parallel edges keep
    both, flagged with evidence level + version (layer 7)."""

    __tablename__ = "graph_edge"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    src: uuid.UUID = Field(foreign_key="graph_node.id", index=True)
    dst: uuid.UUID = Field(foreign_key="graph_node.id", index=True)
    rel: str = ""
    provenance: dict = Field(default_factory=dict, sa_column=Column(JSON))
    evidence_level: str = ""
    version: int = 1
