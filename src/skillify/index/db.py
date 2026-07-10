"""Engine/session creation for the index DB (T2.2). Production points `index_db_url` at
Postgres (`postgresql+psycopg://...`); tests use SQLite (`sqlite:///...` or `sqlite://`
in-memory) — the schema in `models.py` sticks to portable column types for this reason.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from skillify.index.models import Base


def make_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
