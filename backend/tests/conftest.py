"""Shared test fixtures. Uses SQLite in-memory so the base-model conventions and
repository patterns can be smoke-tested without a live Postgres, while remaining
dialect-portable to the real Postgres+pgvector runtime."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base


@pytest.fixture(autouse=True)
def _crypto_test_key():
    """Inject an explicit, non-default test key ring so crypto is deterministic
    and independent of environment settings (SAATHI-366 C3 — tests may inject
    explicit test keys). Also exercises the version-stamp path (active = v1)."""
    from app.core.crypto import KeyRing, override_keyring

    override_keyring(KeyRing(active_version="v1", secrets={"v1": b"unit-test-registration-key-v1"}))
    try:
        yield
    finally:
        override_keyring(None)


@pytest.fixture(scope="session")
def engine() -> Engine:
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def db_session(engine: Engine) -> Iterator[Session]:
    # Model modules are imported by the test suite, so their tables are on Base.metadata.
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(engine)
