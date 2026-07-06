"""SQLAlchemy 2.x declarative base and shared model conventions.

Conventions applied to every model via TimestampedBase:
- UUID primary key (`id`), portable across Postgres and SQLite.
- `created_at` / `updated_at` timestamps (UTC, DB-defaulted).
- `deleted_at` soft-delete readiness (NULL = live row).
- `metadata_json` audit-friendly free-form column.
A consistent naming convention keeps Alembic autogenerate diffs stable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampedBase(Base):
    """Abstract base carrying the standard audit/soft-delete columns."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
