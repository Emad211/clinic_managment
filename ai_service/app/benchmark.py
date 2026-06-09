"""Gold Set + benchmark harness.

A first-class quality component (docs/PIPELINE.md §5): every prompt/model change is
measured against a curated gold set, and the gold labels seed the verification
layer. The benchmark runs the full pipeline on each gold document and scores the
VERIFIED concepts against the expected ones (precision/recall/F1), surfacing
coverage gaps (terms the extractor missed) as a concrete to-do list.

GOLD grows into a curated, versioned file. Expected terms are listed as surface
forms and compared on canonical concepts.
"""

from sqlmodel import Session, select

from .ingestion import ingest_text_document
from .models import Claim, DocumentChunk
from .orchestrator import process_document
from .serving import _canonical

# Curated gold set (seed). `_GAP` items intentionally include terms the seed
# lexicon doesn't cover yet, so the benchmark reports a real recall gap.
GOLD = [
    {
        "title": "gold-diabetes",
        "text": "Type 2 diabetes with high HbA1c: start metformin.",
        "expected_terms": ["type 2 diabetes", "diabetes", "hba1c", "metformin"],
    },
    {
        "title": "gold-htn",
        "text": "Hypertension: use an ACE inhibitor or ARB; add a statin for LDL.",
        "expected_terms": ["hypertension", "ace inhibitor", "arb", "statin", "ldl"],
    },
    {
        "title": "gold-gap",
        "text": "Empagliflozin reduces cardiovascular mortality in diabetes.",
        "expected_terms": ["diabetes", "empagliflozin"],  # empagliflozin = coverage gap
    },
]


def _verified_concepts(session: Session, document) -> set:
    chunk_ids = [
        c.id for c in session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document.id)
        ).all()
    ]
    got = set()
    for ch_id in chunk_ids:
        claims = session.exec(
            select(Claim).where(Claim.chunk_id == ch_id, Claim.status == "verified")
        ).all()
        for cl in claims:
            term = (cl.payload or {}).get("term", "")
            if term:
                got.add(_canonical(term))
    return got


def run_benchmark(session: Session, gold=None) -> dict:
    gold = gold if gold is not None else GOLD
    tp = fp = fn = 0
    missed, per_doc = [], []

    for i, item in enumerate(gold):
        doc = ingest_text_document(session, item.get("title", f"gold-{i}"), item["text"])
        process_document(session, doc)
        got = _verified_concepts(session, doc)
        expected = {_canonical(t) for t in item["expected_terms"]}

        d_tp, d_fp, d_fn = len(got & expected), len(got - expected), len(expected - got)
        tp += d_tp
        fp += d_fp
        fn += d_fn
        missed.extend(expected - got)
        per_doc.append({"title": item.get("title"), "tp": d_tp, "fp": d_fp, "fn": d_fn})

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
        "tp": tp, "fp": fp, "fn": fn,
        "missed": sorted(set(missed)), "per_doc": per_doc,
    }
