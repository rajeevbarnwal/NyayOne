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
