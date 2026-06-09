from app.extraction import deterministic_terms, extract_claims


def test_deterministic_terms_finds_medical_lexicon():
    pairs = deterministic_terms("Patient has diabetes and hypertension; start metformin.")
    terms = {t for t, _ in pairs}
    assert {"diabetes", "hypertension", "metformin"} <= terms


def test_extract_claims_are_anchored(make_chunk, session):
    _doc, ch = make_chunk("Start metformin for diabetes; check hba1c.")
    claims = extract_claims(session, ch)
    assert len(claims) >= 3
    for c in claims:
        assert c.claim_type == "terminology"
        assert c.payload["term"]
        # the hard rule: every claim carries a source anchor
        assert c.source_anchor["page"] == 1 and c.source_anchor["snippet"]
        assert c.status == "extracted"
