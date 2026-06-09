"""Specialized extraction (pipeline layer 4).

For M3 this extracts **terminology** claims (the foundation of the graph + entity
linking). Every atomic claim carries a SOURCE ANCHOR (document_id, page, snippet)
— the hard rule of the pipeline. With a real model an LLM extracts JSON; with the
NullModel a deterministic medical-lexicon scan produces grounded claims so the
whole flow (incl. the verification gate) is testable without spend.
"""

from typing import List, Optional, Tuple

from .gateway import NullModel, get_model
from .models import Claim, DocumentChunk

# small seed lexicon — replaced/augmented by ontology + LLM extraction later
LEXICON = [
    "diabetes", "type 2 diabetes", "hypertension", "hyperlipidemia",
    "chronic kidney disease", "ckd", "obesity",
    "metformin", "insulin", "sulfonylurea", "sglt2", "glp-1", "dpp-4",
    "ace inhibitor", "arb", "statin", "hba1c", "ldl", "egfr", "blood pressure",
]


def _window(text: str, idx: int, term: str, pad: int = 40) -> str:
    start = max(0, idx - pad)
    end = min(len(text), idx + len(term) + pad)
    return text[start:end].strip()


def deterministic_terms(text: str) -> List[Tuple[str, str]]:
    low = text.lower()
    found = []
    seen = set()
    for term in LEXICON:
        idx = low.find(term)
        if idx != -1 and term not in seen:
            seen.add(term)
            found.append((term, _window(text, idx, term)))
    return found


def extract_claims(session, chunk: DocumentChunk, model=None) -> List[Claim]:
    """Extract terminology claims from a chunk and persist them (status=extracted)."""
    model = model or get_model("extraction")
    if isinstance(model, NullModel):
        pairs = deterministic_terms(chunk.content)
    else:
        pairs = _llm_terms(model, chunk.content)

    claims = []
    for term, snippet in pairs:
        claim = Claim(
            chunk_id=chunk.id, claim_type="terminology",
            payload={"term": term},
            source_anchor={
                "document_id": str(chunk.document_id),
                "page": chunk.page_anchor, "snippet": snippet,
            },
            status="extracted",
        )
        session.add(claim)
        claims.append(claim)
    session.commit()
    for c in claims:
        session.refresh(c)
    return claims


def _llm_terms(model, text: str) -> List[Tuple[str, str]]:
    """Best-effort LLM extraction; falls back to the deterministic scan if the
    model output can't be parsed (the pipeline must never crash on bad LLM output)."""
    import json

    prompt = [
        {"role": "system", "content": "Extract medical terminology as JSON list of "
         "{term, snippet} where snippet is the exact source text. Only JSON."},
        {"role": "user", "content": text[:4000]},
    ]
    try:
        raw = model.complete(prompt, max_tokens=800)
        data = json.loads(raw)
        return [(d["term"], d.get("snippet", "")) for d in data if d.get("term")]
    except Exception:
        return deterministic_terms(text)
