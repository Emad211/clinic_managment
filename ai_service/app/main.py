"""FastAPI app for the knowledge pipeline (ai_service).

M1: health + a minimal ingest endpoint (text → registered SourceDocument).
Structural parsing, extraction, the verification gate, ontology, graph, and the
MCP serving layer arrive in M2–M4 (docs/PIPELINE.md §7).
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlmodel import Session

from .db import create_db_and_tables, get_session
from .ingestion import ingest_document


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
