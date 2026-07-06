"""Database engine, session factory, and FastAPI dependency.

The engine is created lazily so importing this module never opens a DB driver or
connection (keeps imports/tests cheap and driver-agnostic)."""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _make_engine(url: str) -> Engine:
    # SQLite (used by tests) does not accept server-style pool sizing args.
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        connect_args = {"check_same_thread": False} if ":memory:" in url else {}
        return create_engine(
            url, echo=settings.db_echo, connect_args=connect_args, poolclass=StaticPool
        )
    return create_engine(
        url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return _make_engine(settings.database_url)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(), autoflush=False, expire_on_commit=False, class_=Session
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session and guaranteeing cleanup."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
