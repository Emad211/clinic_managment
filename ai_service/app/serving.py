"""Serving (pipeline layer 9) — MCP-style read API over the knowledge graph.

get_concept / get_neighbors mirror the MCP tools the platform's modules will call
(get_concept / get_neighbors / get_differential). Read-only — resolves the
canonical concept without mutating the graph. EN→FA translation happens only at
display time (in the platform), never here.
"""

from typing import List, Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from .models import GraphEdge, GraphNode, OntologyConcept
from .ontology import ALIASES, SEED


def _canonical(term: str) -> str:
    key = ALIASES.get(term.lower(), term.lower())
    return SEED.get(key, {}).get("canonical", term.strip().title())


def get_concept(session: Session, term: str) -> Optional[dict]:
    concept = session.exec(
        select(OntologyConcept).where(OntologyConcept.canonical_name == _canonical(term))
    ).first()
    if not concept:
        return None
    return {
        "canonical": concept.canonical_name,
        "icd11": concept.icd11, "mesh": concept.mesh,
        "inn": concept.inn, "atc": concept.atc,
        "aliases": concept.aliases.get("surface", []),
    }


def get_neighbors(session: Session, term: str) -> List[dict]:
    concept = session.exec(
        select(OntologyConcept).where(OntologyConcept.canonical_name == _canonical(term))
    ).first()
    if not concept:
        return []
    node = session.exec(
        select(GraphNode).where(GraphNode.concept_id == concept.id)
    ).first()
    if not node:
        return []

    edges = session.exec(
        select(GraphEdge).where(or_(GraphEdge.src == node.id, GraphEdge.dst == node.id))
    ).all()
    out = []
    for e in edges:
        other_id = e.dst if e.src == node.id else e.src
        other = session.get(GraphNode, other_id)
        if other:
            out.append({
                "concept": other.props.get("name"),
                "rel": e.rel, "evidence_level": e.evidence_level,
            })
    return out
