"""Engine/session creation for the Skillify business database.

Production points ``index_db_url`` at the externally initialized DM8 schema. SQLite tests
still create their transient schema from ORM metadata; production databases never do so.
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
    if engine.dialect.name == "sqlite":
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
