"""Graph build & conflict resolution (pipeline layer 7).

Builds concept nodes + provenance-bearing edges from VERIFIED claims. Conflicts
are never overwritten — parallel edges keep both, flagged with evidence level +
version. M4 derives `co_occurs` edges from concepts appearing in the same chunk
(a real relation extractor refines these later).
"""

from sqlmodel import Session, select

from .models import (
    Claim, DocumentChunk, GraphEdge, GraphNode, OntologyConcept, SourceDocument,
)
from .ontology import resolve_concept


def upsert_node(session: Session, concept: OntologyConcept) -> GraphNode:
    existing = session.exec(
        select(GraphNode).where(GraphNode.concept_id == concept.id)
    ).first()
    if existing:
        return existing
    node = GraphNode(concept_id=concept.id, kind="concept",
                     props={"name": concept.canonical_name})
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def add_edge(session: Session, src: GraphNode, dst: GraphNode, rel: str,
             provenance: dict, evidence_level: str = "") -> GraphEdge:
    edge = GraphEdge(src=src.id, dst=dst.id, rel=rel,
                     provenance=provenance, evidence_level=evidence_level)
    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


def build_graph_for_document(session: Session, document: SourceDocument) -> dict:
    """Map verified claims → concepts → nodes, add co-occurrence edges with
    provenance. Returns counts."""
    chunks = session.exec(
        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    ).all()

    stats = {"nodes": 0, "edges": 0}
    for chunk in chunks:
        verified = session.exec(
            select(Claim).where(Claim.chunk_id == chunk.id, Claim.status == "verified")
        ).all()
        nodes = []
        for claim in verified:
            term = (claim.payload or {}).get("term", "")
            if not term:
                continue
            concept = resolve_concept(session, term)
            nodes.append(upsert_node(session, concept))

        # co-occurrence edges between distinct concepts in the same chunk
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if nodes[i].id == nodes[j].id:
                    continue
                add_edge(
                    session, nodes[i], nodes[j], "co_occurs",
                    {"document_id": str(document.id), "page": chunk.page_anchor},
                    evidence_level=chunk.evidence_level,
                )
                stats["edges"] += 1

    stats["nodes"] = len(session.exec(select(GraphNode)).all())
    return stats
