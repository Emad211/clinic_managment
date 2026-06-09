from app.extraction import extract_claims
from app.models import Claim
from app.verification import verify_claim


def test_grounded_claim_is_verified(make_chunk, session):
    _doc, ch = make_chunk("Metformin is first-line therapy for diabetes.")
    claim = extract_claims(session, ch)[0]
    v = verify_claim(session, claim, ch.content)
    assert v.verdict == "verified" and v.confidence > 0.9
    session.refresh(claim)
    assert claim.status == "verified"


def test_gate_catches_hallucinated_claim(make_chunk, session):
    """The whole point of the gate: a claim whose term is NOT in the source text
    must be rejected (not silently accepted)."""
    doc, ch = make_chunk("Metformin is first-line therapy for diabetes.")
    bad = Claim(
        chunk_id=ch.id, claim_type="terminology",
        payload={"term": "leukemia"},
        source_anchor={"document_id": str(doc.id), "page": 1, "snippet": "leukemia chemotherapy"},
        status="extracted",
    )
    session.add(bad)
    session.commit()
    session.refresh(bad)

    v = verify_claim(session, bad, ch.content)
    assert v.verdict == "not_found" and v.confidence < 0.5
    session.refresh(bad)
    assert bad.status == "not_found"
