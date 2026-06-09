"""Orchestrator — the pipeline spine (Orchestrator–Worker pattern).

Drives a document through the state machine, RUNS THE GATES (the next station is
forbidden until the previous is verified), and routes failures to human review.
Designed to be idempotent + resumable + observable. For now it runs synchronously;
an arq worker (Redis) wraps `process_document` for async/at-scale execution.

Safety principle: safety-critical claim types (drug dose / contraindication) ALWAYS
go to human review regardless of the gate's confidence.
"""

from sqlmodel import select

from .extraction import extract_claims
from .models import Claim, DocumentChunk, ReviewQueue, SourceDocument
from .verification import verify_claim

SAFETY_CRITICAL = {"drug_dose", "contraindication"}


def verify_and_route(session, claim: Claim, chunk_text: str, model=None):
    """Run the gate on a claim and route it to human review if it fails the gate
    OR is safety-critical. Returns (verification, needs_review)."""
    v = verify_claim(session, claim, chunk_text, model)
    needs_review = (v.verdict != "verified") or (claim.claim_type in SAFETY_CRITICAL)
    if needs_review:
        reason = v.verdict if v.verdict != "verified" else "safety_critical"
        session.add(ReviewQueue(claim_id=claim.id, reason=reason))
        session.commit()
    return v, needs_review


def process_document(session, document: SourceDocument) -> dict:
    """Extract → verify → route, for every chunk of a parsed document. Idempotent:
    a document already past verification is skipped."""
    if document.status == "verified":
        return {"skipped": True, "claims": 0, "verified": 0, "review": 0}

    chunks = session.exec(
        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    ).all()

    stats = {"skipped": False, "claims": 0, "verified": 0, "review": 0}
    for chunk in chunks:
        for claim in extract_claims(session, chunk):
            stats["claims"] += 1
            _v, needs_review = verify_and_route(session, claim, chunk.content)
            if needs_review:
                stats["review"] += 1
            else:
                stats["verified"] += 1

    document.status = "verified"
    session.add(document)
    session.commit()
    return stats
