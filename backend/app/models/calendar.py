"""Server-authoritative unified calendar models (SAATHI-285/290/295).

The browser is never the system of record for calendar data.  Events, view and
reminder preferences, conflict results and external-feed lifecycle state are
owned by an authenticated user and persisted here.  Public feed bearer tokens
are represented only by a keyed hash; the raw token is returned once and is
never written to the database.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import TimestampedBase

CALENDAR_SOURCE_TYPES = (
    "internship",
    "exam",
    "clinical",
    "community",
    "tutoring",
    "moot",
    "reminder",
)
CALENDAR_EVENT_STATUSES = ("scheduled", "deadline", "tentative", "done", "cancelled")
CALENDAR_PRIVACY_CLASSES = ("public", "personal", "restricted")
PERSONAL_EVENT_KINDS = ("study", "deadline", "meeting", "reminder", "other")
CALENDAR_VIEW_MODES = ("month", "week", "day")
CALENDAR_REMINDER_CHANNELS = ("in_app", "email_digest", "push")
CALENDAR_CONFLICT_STATUSES = ("active", "dismissed", "resolved")
CALENDAR_EXPORT_STATUSES = ("active", "revoked", "expired")
CALENDAR_REVOCATION_REASONS = ("user_requested", "rotated", "security", "expired")


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IN ({', '.join(repr(value) for value in values)})",
        name=name,
    )


class CalendarEventSource(TimestampedBase):
    __tablename__ = "calendar_event_sources"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str] = mapped_column(String(240), nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "owner_user_id", name="uq_calendar_source_id_owner"),
        UniqueConstraint(
            "owner_user_id", "source_type", "source_id", name="uq_calendar_source_owner_type_id"
        ),
        _in("source_type", CALENDAR_SOURCE_TYPES, "source_type"),
        CheckConstraint("length(source_id) BETWEEN 1 AND 120", name="source_id_length"),
        CheckConstraint("length(source_url) BETWEEN 1 AND 240", name="source_url_length"),
    )


class CalendarEvent(TimestampedBase):
    __tablename__ = "calendar_events"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    source_offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    privacy_classification: Mapped[str] = mapped_column(String(24), nullable=False)
    # Only owner-created events set this. Imported domain events keep NULL and
    # retain their module meaning through source_type/source_id.
    personal_event_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["event_source_id", "owner_user_id"],
            ["calendar_event_sources.id", "calendar_event_sources.owner_user_id"],
            ondelete="CASCADE",
            name="fk_calendar_event_source_owner",
        ),
        UniqueConstraint("id", "owner_user_id", name="uq_calendar_event_id_owner"),
        UniqueConstraint("event_source_id", name="uq_calendar_events_event_source_id"),
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_calendar_event_owner_idempotency"),
        _in("status", CALENDAR_EVENT_STATUSES, "status"),
        _in("privacy_classification", CALENDAR_PRIVACY_CLASSES, "privacy_classification"),
        CheckConstraint(
            "personal_event_kind IS NULL OR personal_event_kind IN "
            "('study', 'deadline', 'meeting', 'reminder', 'other')",
            name="personal_event_kind",
        ),
        CheckConstraint("length(title) BETWEEN 1 AND 160", name="title_length"),
        CheckConstraint("ends_at > starts_at", name="interval_order"),
        CheckConstraint("source_offset_minutes BETWEEN -840 AND 840", name="offset_range"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class CalendarViewPreference(TimestampedBase):
    __tablename__ = "calendar_view_preferences"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    view_mode: Mapped[str] = mapped_column(String(16), default="month", server_default="month", nullable=False)
    source_types_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    from_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_user_id", name="uq_calendar_view_preferences_owner_user_id"),
        _in("view_mode", CALENDAR_VIEW_MODES, "view_mode"),
        CheckConstraint("to_date IS NULL OR from_date IS NULL OR to_date >= from_date", name="date_order"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class CalendarReminderPreference(TimestampedBase):
    __tablename__ = "calendar_reminder_preferences"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    lead_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    quiet_start_min: Mapped[int] = mapped_column(Integer, nullable=False)
    quiet_end_min: Mapped[int] = mapped_column(Integer, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "source_type", "channel", name="uq_calendar_reminder_owner_source_channel"),
        _in("source_type", CALENDAR_SOURCE_TYPES, "source_type"),
        _in("channel", CALENDAR_REMINDER_CHANNELS, "channel"),
        CheckConstraint("lead_minutes IN (0, 10, 30, 60, 120, 1440)", name="lead_minutes"),
        CheckConstraint("quiet_start_min BETWEEN 0 AND 1439", name="quiet_start_range"),
        CheckConstraint("quiet_end_min BETWEEN 0 AND 1439", name="quiet_end_range"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class CalendarConflict(TimestampedBase):
    __tablename__ = "calendar_conflicts"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    left_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    right_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["left_event_id", "owner_user_id"],
            ["calendar_events.id", "calendar_events.owner_user_id"],
            ondelete="CASCADE",
            name="fk_calendar_conflict_left_event_owner",
        ),
        ForeignKeyConstraint(
            ["right_event_id", "owner_user_id"],
            ["calendar_events.id", "calendar_events.owner_user_id"],
            ondelete="CASCADE",
            name="fk_calendar_conflict_right_event_owner",
        ),
        UniqueConstraint("owner_user_id", "left_event_id", "right_event_id", name="uq_calendar_conflict_pair"),
        _in("status", CALENDAR_CONFLICT_STATUSES, "status"),
        CheckConstraint("left_event_id != right_event_id", name="different_events"),
        CheckConstraint(
            "CAST(left_event_id AS VARCHAR(36)) < CAST(right_event_id AS VARCHAR(36))",
            name="canonical_pair_order",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class CalendarExportSubscription(TimestampedBase):
    __tablename__ = "calendar_export_subscriptions"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active", nullable=False, index=True)
    # Portable partial-uniqueness marker: one TRUE per owner, many NULLs.
    active_marker: Mapped[bool | None] = mapped_column(Boolean, default=True, server_default="true", nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_calendar_export_owner_idempotency"),
        UniqueConstraint("owner_user_id", "active_marker", name="uq_calendar_export_owner_active"),
        _in("status", CALENDAR_EXPORT_STATUSES, "status"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status != 'revoked' OR revoked_at IS NOT NULL", name="revoked_timestamp"),
        CheckConstraint(
            "(status = 'active' AND active_marker IS TRUE) OR "
            "(status != 'active' AND active_marker IS NULL)",
            name="active_marker_truthful",
        ),
        Index(
            "uq_calendar_export_one_active_pg",
            "owner_user_id",
            unique=True,
            postgresql_where=(status == "active"),
            sqlite_where=(status == "active"),
        ),
    )


class CalendarExportToken(TimestampedBase):
    __tablename__ = "calendar_export_tokens"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("calendar_export_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("subscription_id", name="uq_calendar_export_tokens_subscription_id"),
        UniqueConstraint("token_hash", name="uq_calendar_export_tokens_token_hash"),
        CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        CheckConstraint("length(key_version) BETWEEN 1 AND 16", name="key_version_length"),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class CalendarExportRevocation(TimestampedBase):
    __tablename__ = "calendar_export_revocations"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("calendar_export_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("calendar_export_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    revoked_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason_code: Mapped[str] = mapped_column(String(24), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("subscription_id", name="uq_calendar_export_revocations_subscription_id"),
        UniqueConstraint("token_id", name="uq_calendar_export_revocations_token_id"),
        _in("reason_code", CALENDAR_REVOCATION_REASONS, "reason_code"),
    )
