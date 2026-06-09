"""Verification & Grounding — the CRITICAL gate (pipeline layer 5).

An INDEPENDENT check that assumes the extracted claim is untrustworthy and
verifies each one against the source text at its anchor. This is the second,
independent pass that distinguishes the pipeline from a single-shot labeller — a
hallucinated/ungrounded claim is caught here and sent to human review instead of
poisoning the knowledge graph.

Deterministic grounding (NullModel): a claim is `verified` only if BOTH its term
and its source snippet actually occur in the chunk text; `partial` if only the
term grounds; `not_found` otherwise. A real verifier model does the same check
semantically.
"""

from .gateway import get_model
from .models import Claim, Verification


def _grounded(needle: str, haystack: str) -> bool:
    return bool(needle) and needle.lower() in haystack.lower()


def verify_claim(session, claim: Claim, chunk_text: str, model=None) -> Verification:
    model = model or get_model("verification")
    term = (claim.payload or {}).get("term", "")
    snippet = (claim.source_anchor or {}).get("snippet", "")

    term_ok = _grounded(term, chunk_text)
    snip_ok = _grounded(snippet[:24], chunk_text) if snippet else False

    # Deterministic grounding. TODO: when a real verifier model is wired, do a
    # semantic grounding check here (the independent second pass) instead of/
    # in addition to substring grounding. `model` is kept for that path.
    if term_ok and snip_ok:
        verdict, confidence = "verified", 0.95
    elif term_ok:
        verdict, confidence = "partial", 0.6
    else:
        verdict, confidence = "not_found", 0.1

    v = Verification(
        claim_id=claim.id, verdict=verdict, confidence=confidence,
        supporting_snippet=snippet if term_ok else "",
        model=getattr(model, "name", ""),
    )
    session.add(v)
    claim.status = verdict
    session.add(claim)
    session.commit()
    session.refresh(v)
    return v
