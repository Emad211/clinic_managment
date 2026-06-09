"""FastAPI app for the knowledge pipeline (ai_service).

M1: health + a minimal ingest endpoint (text → registered SourceDocument).
Structural parsing, extraction, the verification gate, ontology, graph, and the
MCP serving layer arrive in M2–M4 (docs/PIPELINE.md §7).
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from .db import create_db_and_tables, get_session
from .ingestion import ingest_document, ingest_text_document
from .orchestrator import process_document
from .parsing import parse_and_store
from .serving import get_concept, get_neighbors


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="Clinic Knowledge Pipeline", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai_service", "version": "0.1.0"}


class IngestIn(BaseModel):
    title: str
    text: str
    publisher: str = ""
    year: int | None = None
    evidence_level: str = ""


@app.post("/ingest")
def ingest(data: IngestIn, session: Session = Depends(get_session)):
    doc, created = ingest_document(
        session, title=data.title, raw=data.text.encode("utf-8"),
        publisher=data.publisher, year=data.year, evidence_level=data.evidence_level,
    )
    return {"id": str(doc.id), "content_hash": doc.content_hash,
            "status": doc.status, "created": created}


# ── full-pipeline document processing (ingest → parse → extract → verify → graph) ──
class ProcessIn(BaseModel):
    title: str
    text: str


@app.post("/documents/process")
def documents_process(data: ProcessIn, session: Session = Depends(get_session)):
    doc = ingest_text_document(session, data.title, data.text)
    stats = process_document(session, doc)
    return {"document_id": str(doc.id), "status": doc.status, "stats": stats}


@app.post("/documents/upload")
def documents_upload(
    file: UploadFile = File(...), title: str = Form(""),
    session: Session = Depends(get_session),
):
    raw = file.file.read()
    doc, _ = ingest_document(session, title=title or (file.filename or "document"), raw=raw)
    parse_and_store(session, doc, raw)
    stats = process_document(session, doc)
    return {"document_id": str(doc.id), "status": doc.status, "stats": stats}


# ── MCP-style serving over the knowledge graph (layer 9) ──
@app.get("/knowledge/concept")
def knowledge_concept(term: str, session: Session = Depends(get_session)):
    concept = get_concept(session, term)
    return concept or {"detail": "concept not found", "term": term}


@app.get("/knowledge/neighbors")
def knowledge_neighbors(term: str, session: Session = Depends(get_session)):
    return {"term": term, "neighbors": get_neighbors(session, term)}
