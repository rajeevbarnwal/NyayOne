"""Smoke tests for the database foundation: base-model conventions, a
repository-style create/query/soft-delete cycle, and the engine factory."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedBase
from app.db.session import _make_engine


class _SmokeItem(TimestampedBase):
    __tablename__ = "smoke_items"
    name: Mapped[str] = mapped_column(String(100), nullable=False)


def test_base_model_conventions() -> None:
    cols = set(_SmokeItem.__table__.columns.keys())
    assert {"id", "created_at", "updated_at", "deleted_at", "metadata_json", "name"} <= cols


def test_repository_create_query_soft_delete(db_session) -> None:
    item = _SmokeItem(name="Client Intake", metadata_json={"source": "web"})
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    assert isinstance(item.id, uuid.UUID)
    assert item.created_at is not None and item.updated_at is not None
    assert item.deleted_at is None and item.is_deleted is False

    fetched = db_session.scalar(select(_SmokeItem).where(_SmokeItem.name == "Client Intake"))
    assert fetched is not None and fetched.metadata_json == {"source": "web"}

    fetched.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    assert db_session.get(_SmokeItem, item.id).is_deleted is True


def test_engine_factory_handles_sqlite() -> None:
    eng = _make_engine("sqlite+pysqlite:///:memory:")
    assert eng.dialect.name == "sqlite"


def test_schema_template_is_identical_to_create_all() -> None:
    """Guards the test-suite schema template (``tests/dbtemplate.py``).

    The suite builds most of its per-test databases by copying a session-scoped
    template instead of re-running ``Base.metadata.create_all`` (~40x cheaper).
    That is only legitimate if the copy is indistinguishable from the real
    thing, so compare the FULL SQLite catalogue -- every table, view, trigger and
    index (explicit and implicit) with its exact DDL -- between a database built
    by ``create_all`` and one built by the template.
    """
    import app.models  # noqa: F401  (registers every table on Base.metadata)
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from tests import dbtemplate

    def fresh():
        return create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    real, copied = fresh(), fresh()
    Base.metadata.create_all(real)
    dbtemplate.create_all(copied)
    with real.connect() as a, copied.connect() as b:
        expected = a.exec_driver_sql(dbtemplate.MASTER_QUERY).fetchall()
        actual = b.exec_driver_sql(dbtemplate.MASTER_QUERY).fetchall()
    real.dispose()
    copied.dispose()

    # Sanity: the catalogue really is the whole schema, not an empty comparison.
    assert len(expected) > len(Base.metadata.tables) > 40
    assert actual == expected
