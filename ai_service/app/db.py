"""Database engine/session for ai_service (SQLModel)."""

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
_is_memory = _is_sqlite and (":memory:" in settings.database_url or settings.database_url == "sqlite://")
connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine_kwargs = {"echo": False, "connect_args": connect_args}
if _is_memory:
    # one shared connection so the in-memory DB is visible across threads (tests)
    engine_kwargs["poolclass"] = StaticPool
engine = create_engine(settings.database_url, **engine_kwargs)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
