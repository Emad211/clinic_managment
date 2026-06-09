import os

# in-memory DB for the app engine (used by the /health lifespan); no stray file
os.environ.setdefault("AI_DATABASE_URL", "sqlite://")

import pytest  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import app.models  # noqa: F401,E402  (register tables on the metadata)


@pytest.fixture
def session():
    """A fresh in-memory DB session per test (shared connection via StaticPool)."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def make_chunk(session):
    """Factory: persist a SourceDocument + one DocumentChunk with given text."""
    import uuid

    from app.models import DocumentChunk, SourceDocument

    def _make(text):
        doc = SourceDocument(content_hash=uuid.uuid4().hex, title="t")
        session.add(doc)
        session.commit()
        session.refresh(doc)
        ch = DocumentChunk(document_id=doc.id, ordinal=0, page_anchor=1,
                           kind="prose", content=text)
        session.add(ch)
        session.commit()
        session.refresh(ch)
        return doc, ch

    return _make
