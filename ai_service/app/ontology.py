"""Ontology mapping (pipeline layer 6).

Resolves a claim's surface term to a CANONICAL internal concept + crosswalk to
ICD-11 / MeSH / INN / ATC (deterministic lookup; LLM only for ambiguity, later).
Entity resolution: the same term across documents maps to ONE concept node
("metformin" in two guidelines = one concept).
"""

from sqlmodel import Session, select

from .models import OntologyConcept

# seed ontology (canonical + crosswalk). Grows via a real ontology file later.
SEED = {
    "diabetes": {"canonical": "Diabetes mellitus", "icd11": "5A1", "mesh": "D003920"},
    "type 2 diabetes": {"canonical": "Type 2 diabetes mellitus", "icd11": "5A11", "mesh": "D003924"},
    "hypertension": {"canonical": "Hypertension", "icd11": "BA00", "mesh": "D006973"},
    "hyperlipidemia": {"canonical": "Hyperlipidemia", "icd11": "5C80", "mesh": "D006949"},
    "chronic kidney disease": {"canonical": "Chronic kidney disease", "icd11": "GB61", "mesh": "D051436"},
    "ckd": {"canonical": "Chronic kidney disease", "icd11": "GB61", "mesh": "D051436"},
    "obesity": {"canonical": "Obesity", "icd11": "5B81", "mesh": "D009765"},
    "metformin": {"canonical": "Metformin", "inn": "metformin", "atc": "A10BA02"},
    "insulin": {"canonical": "Insulin", "atc": "A10A"},
    "sulfonylurea": {"canonical": "Sulfonylurea", "atc": "A10BB"},
    "sglt2": {"canonical": "SGLT2 inhibitor", "atc": "A10BK"},
    "glp-1": {"canonical": "GLP-1 receptor agonist", "atc": "A10BJ"},
    "dpp-4": {"canonical": "DPP-4 inhibitor", "atc": "A10BH"},
    "ace inhibitor": {"canonical": "ACE inhibitor", "atc": "C09A"},
    "arb": {"canonical": "Angiotensin receptor blocker", "atc": "C09C"},
    "statin": {"canonical": "HMG-CoA reductase inhibitor", "atc": "C10AA"},
    "hba1c": {"canonical": "Glycated hemoglobin", "mesh": "D006442"},
    "ldl": {"canonical": "LDL cholesterol", "mesh": "D008078"},
    "egfr": {"canonical": "Estimated glomerular filtration rate", "mesh": "D005919"},
    "blood pressure": {"canonical": "Blood pressure", "mesh": "D001794"},
}
ALIASES = {"t2dm": "type 2 diabetes", "dm": "diabetes", "htn": "hypertension"}


def resolve_concept(session: Session, term: str) -> OntologyConcept:
    key = ALIASES.get(term.lower(), term.lower())
    data = SEED.get(key, {})
    canonical = data.get("canonical", term.strip().title())

    # entity resolution: reuse an existing concept with the same canonical name
    existing = session.exec(
        select(OntologyConcept).where(OntologyConcept.canonical_name == canonical)
    ).first()
    if existing:
        surface = set(existing.aliases.get("surface", []))
        if term not in surface:
            surface.add(term)
            existing.aliases = {**existing.aliases, "surface": sorted(surface)}
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return existing

    concept = OntologyConcept(
        canonical_name=canonical,
        icd11=data.get("icd11", ""), mesh=data.get("mesh", ""),
        inn=data.get("inn", ""), atc=data.get("atc", ""),
        aliases={"surface": [term]},
    )
    session.add(concept)
    session.commit()
    session.refresh(concept)
    return concept
