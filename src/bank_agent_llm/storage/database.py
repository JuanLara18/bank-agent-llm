"""Database engine and session management.

Usage:
    from bank_agent_llm.storage.database import get_session

    with get_session() as session:
        session.add(account)
        session.commit()
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None  # type: ignore[type-arg]


def _enable_sqlite_fk(engine: Engine) -> None:
    """Enable foreign key enforcement for SQLite connections."""
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def set_fk_pragma(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()


def init_engine(url: str) -> Engine:
    """Create and configure the database engine.

    Call this once at application startup. The engine is cached globally.
    """
    global _engine, _SessionFactory
    _engine = create_engine(url, echo=False)
    _enable_sqlite_fk(_engine)
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    """Return the cached engine, initializing from config if needed."""
    global _engine
    if _engine is None:
        from bank_agent_llm.config import get_settings
        settings = get_settings()
        init_engine(settings.database.url)
    assert _engine is not None
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional database session.

    Commits on success, rolls back on any exception.
    """
    global _SessionFactory
    if _SessionFactory is None:
        get_engine()
    assert _SessionFactory is not None
    session: Session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
