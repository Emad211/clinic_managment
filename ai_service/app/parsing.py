"""Structural parsing (pipeline layer 2) — deterministic, BEFORE any LLM.

Turns a PDF into normalised DocumentChunks with a **page anchor** (the basis of
the verification gate's grounding). Tables are extracted as structured objects
(not flattened text) because drug doses live in tables. Uses PyMuPDF's built-in
text + table extraction — no Camelot/Ghostscript/OpenCV dependency.
"""

from typing import List

import fitz  # PyMuPDF

from .models import DocumentChunk, SourceDocument


def _rows_to_text(rows) -> str:
    out = []
    for r in rows or []:
        cells = ["" if c is None else str(c) for c in r]
        out.append(" | ".join(cells))
    return "\n".join(out)


def parse_pdf(raw: bytes) -> List[dict]:
    """Return ordered chunk dicts: {ordinal, page_anchor, kind, content, structured}."""
    doc = fitz.open(stream=raw, filetype="pdf")
    chunks: List[dict] = []
    ordinal = 0
    try:
        for pno in range(doc.page_count):
            page = doc[pno]

            # tables first (structured objects, not flat text)
            try:
                found = page.find_tables()
                tables = list(found.tables) if found else []
            except Exception:
                tables = []
            for t in tables:
                try:
                    rows = t.extract()
                except Exception:
                    rows = []
                if rows:
                    chunks.append({
                        "ordinal": ordinal, "page_anchor": pno + 1, "kind": "table",
                        "content": _rows_to_text(rows), "structured": {"rows": rows},
                    })
                    ordinal += 1

            # prose text
            text = (page.get_text("text") or "").strip()
            if text:
                chunks.append({
                    "ordinal": ordinal, "page_anchor": pno + 1, "kind": "prose",
                    "content": text, "structured": {},
                })
                ordinal += 1
    finally:
        doc.close()
    return chunks


def parse_and_store(session, document: SourceDocument, raw: bytes) -> int:
    """Parse a PDF and persist its chunks; advance the document status to 'parsed'.
    Returns the number of chunks stored."""
    chunks = parse_pdf(raw)
    for c in chunks:
        session.add(DocumentChunk(
            document_id=document.id, ordinal=c["ordinal"], page_anchor=c["page_anchor"],
            kind=c["kind"], content=c["content"], structured=c["structured"],
        ))
    document.status = "parsed"
    session.add(document)
    session.commit()
    return len(chunks)
