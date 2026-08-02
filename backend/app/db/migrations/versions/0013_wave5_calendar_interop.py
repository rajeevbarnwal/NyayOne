"""Wave 5 calendar interoperability schema (SAATHI-285/290/295).

Revision ID: 0013_wave5_calendar_interop
Revises: 0012_wave4_moderation
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013_wave5_calendar_interop"
down_revision: str | None = "0012_wave4_moderation"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)
_SOURCE_TYPES = ("internship", "exam", "clinical", "community", "tutoring", "moot", "reminder")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "calendar_event_sources",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("owner_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("source_url", sa.String(240), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        *_ts(),
        sa.UniqueConstraint("id", "owner_user_id", name="uq_calendar_source_id_owner"),
        sa.UniqueConstraint("owner_user_id", "source_type", "source_id", name="uq_calendar_source_owner_type_id"),
        sa.CheckConstraint(_in("source_type", _SOURCE_TYPES), name="source_type"),
        sa.CheckConstraint("length(source_id) BETWEEN 1 AND 120", name="source_id_length"),
        sa.CheckConstraint("length(source_url) BETWEEN 1 AND 240", name="source_url_length"),
    )
    op.create_index("ix_calendar_event_sources_owner_user_id", "calendar_event_sources", ["owner_user_id"])
    op.create_index("ix_calendar_event_sources_source_type", "calendar_event_sources", ["source_type"])

    op.create_table(
        "calendar_events",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("owner_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_source_id", _UUID, nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("source_offset_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("privacy_classification", sa.String(24), nullable=False),
        sa.Column("personal_event_kind", sa.String(24), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.ForeignKeyConstraint(
            ["event_source_id", "owner_user_id"],
            ["calendar_event_sources.id", "calendar_event_sources.owner_user_id"],
            ondelete="CASCADE",
            name="fk_calendar_event_source_owner",
        ),
        sa.UniqueConstraint("id", "owner_user_id", name="uq_calendar_event_id_owner"),
        sa.UniqueConstraint("event_source_id", name="uq_calendar_events_event_source_id"),
        sa.UniqueConstraint("owner_user_id", "idempotency_key", name="uq_calendar_event_owner_idempotency"),
        sa.CheckConstraint(
            _in("status", ("scheduled", "deadline", "tentative", "done", "cancelled")),
            name="status",
        ),
        sa.CheckConstraint(_in("privacy_classification", ("public", "personal", "restricted")), name="privacy_classification"),
        sa.CheckConstraint(
            "personal_event_kind IS NULL OR personal_event_kind IN "
            "('study', 'deadline', 'meeting', 'reminder', 'other')",
            name="personal_event_kind",
        ),
        sa.CheckConstraint("length(title) BETWEEN 1 AND 160", name="title_length"),
        sa.CheckConstraint("ends_at > starts_at", name="interval_order"),
        sa.CheckConstraint("source_offset_minutes BETWEEN -840 AND 840", name="offset_range"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index("ix_calendar_events_owner_user_id", "calendar_events", ["owner_user_id"])
    op.create_index("ix_calendar_events_starts_at", "calendar_events", ["starts_at"])
    op.create_index("ix_calendar_events_ends_at", "calendar_events", ["ends_at"])
    op.create_index("ix_calendar_events_status", "calendar_events", ["status"])
    # Composite foreign keys need an index whose LEADING columns match the
    # constrained columns IN ORDER. Two independent single-column indexes do
    # not serve a two-column FK lookup, so ON DELETE CASCADE from
    # calendar_event_sources would degrade to a sequential scan.
    op.create_index(
        "ix_calendar_events_event_source_owner",
        "calendar_events",
        ["event_source_id", "owner_user_id"],
    )

    op.create_table(
        "calendar_view_preferences",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("owner_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("view_mode", sa.String(16), server_default="month", nullable=False),
        sa.Column("source_types_json", sa.JSON(), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=True),
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column("timezone", sa.String(64), server_default="Asia/Kolkata", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.UniqueConstraint("owner_user_id", name="uq_calendar_view_preferences_owner_user_id"),
        sa.CheckConstraint(_in("view_mode", ("month", "week", "day")), name="view_mode"),
        sa.CheckConstraint("to_date IS NULL OR from_date IS NULL OR to_date >= from_date", name="date_order"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )

    op.create_table(
        "calendar_reminder_preferences",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("owner_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("lead_minutes", sa.Integer(), nullable=False),
        sa.Column("quiet_start_min", sa.Integer(), nullable=False),
        sa.Column("quiet_end_min", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.UniqueConstraint("owner_user_id", "source_type", "channel", name="uq_calendar_reminder_owner_source_channel"),
        sa.CheckConstraint(_in("source_type", _SOURCE_TYPES), name="source_type"),
        sa.CheckConstraint(_in("channel", ("in_app", "email_digest", "push")), name="channel"),
        sa.CheckConstraint("lead_minutes IN (0, 10, 30, 60, 120, 1440)", name="lead_minutes"),
        sa.CheckConstraint("quiet_start_min BETWEEN 0 AND 1439", name="quiet_start_range"),
        sa.CheckConstraint("quiet_end_min BETWEEN 0 AND 1439", name="quiet_end_range"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index("ix_calendar_reminder_preferences_owner_user_id", "calendar_reminder_preferences", ["owner_user_id"])

    op.create_table(
        "calendar_conflicts",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("owner_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("left_event_id", _UUID, nullable=False),
        sa.Column("right_event_id", _UUID, nullable=False),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.ForeignKeyConstraint(
            ["left_event_id", "owner_user_id"],
            ["calendar_events.id", "calendar_events.owner_user_id"],
            ondelete="CASCADE",
            name="fk_calendar_conflict_left_event_owner",
        ),
        sa.ForeignKeyConstraint(
            ["right_event_id", "owner_user_id"],
            ["calendar_events.id", "calendar_events.owner_user_id"],
            ondelete="CASCADE",
            name="fk_calendar_conflict_right_event_owner",
        ),
        sa.UniqueConstraint("owner_user_id", "left_event_id", "right_event_id", name="uq_calendar_conflict_pair"),
        sa.CheckConstraint(_in("status", ("active", "dismissed", "resolved")), name="status"),
        sa.CheckConstraint("left_event_id != right_event_id", name="different_events"),
        sa.CheckConstraint(
            "CAST(left_event_id AS VARCHAR(36)) < CAST(right_event_id AS VARCHAR(36))",
            name="canonical_pair_order",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index("ix_calendar_conflicts_owner_user_id", "calendar_conflicts", ["owner_user_id"])
    op.create_index("ix_calendar_conflicts_left_event_id", "calendar_conflicts", ["left_event_id"])
    op.create_index("ix_calendar_conflicts_right_event_id", "calendar_conflicts", ["right_event_id"])
    # Ordered composite indexes for the two composite owner-scoped FKs above.
    # The single-column indexes stay for the owner-scoped range reads; these
    # exist so each two-column FK has a matching leading-column index.
    op.create_index(
        "ix_calendar_conflicts_left_event_owner",
        "calendar_conflicts",
        ["left_event_id", "owner_user_id"],
    )
    op.create_index(
        "ix_calendar_conflicts_right_event_owner",
        "calendar_conflicts",
        ["right_event_id", "owner_user_id"],
    )

    op.create_table(
        "calendar_export_subscriptions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("owner_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        sa.Column("active_marker", sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.UniqueConstraint("owner_user_id", "idempotency_key", name="uq_calendar_export_owner_idempotency"),
        sa.UniqueConstraint("owner_user_id", "active_marker", name="uq_calendar_export_owner_active"),
        sa.CheckConstraint(_in("status", ("active", "revoked", "expired")), name="status"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("status != 'revoked' OR revoked_at IS NOT NULL", name="revoked_timestamp"),
        sa.CheckConstraint(
            "(status = 'active' AND active_marker IS TRUE) OR "
            "(status != 'active' AND active_marker IS NULL)",
            name="active_marker_truthful",
        ),
    )
    op.create_index("ix_calendar_export_subscriptions_owner_user_id", "calendar_export_subscriptions", ["owner_user_id"])
    op.create_index("ix_calendar_export_subscriptions_status", "calendar_export_subscriptions", ["status"])
    op.create_index("ix_calendar_export_subscriptions_expires_at", "calendar_export_subscriptions", ["expires_at"])
    op.create_index(
        "uq_calendar_export_one_active_pg",
        "calendar_export_subscriptions",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "calendar_export_tokens",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("subscription_id", _UUID, sa.ForeignKey("calendar_export_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("key_version", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint("subscription_id", name="uq_calendar_export_tokens_subscription_id"),
        sa.UniqueConstraint("token_hash", name="uq_calendar_export_tokens_token_hash"),
        sa.CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        sa.CheckConstraint("length(key_version) BETWEEN 1 AND 16", name="key_version_length"),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    op.create_index("ix_calendar_export_tokens_expires_at", "calendar_export_tokens", ["expires_at"])

    op.create_table(
        "calendar_export_revocations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("subscription_id", _UUID, sa.ForeignKey("calendar_export_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_id", _UUID, sa.ForeignKey("calendar_export_tokens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revoked_by_user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason_code", sa.String(24), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
        *_ts(),
        sa.UniqueConstraint("subscription_id", name="uq_calendar_export_revocations_subscription_id"),
        sa.UniqueConstraint("token_id", name="uq_calendar_export_revocations_token_id"),
        sa.CheckConstraint(_in("reason_code", ("user_requested", "rotated", "security", "expired")), name="reason_code"),
    )
    op.create_index("ix_calendar_export_revocations_revoked_by_user_id", "calendar_export_revocations", ["revoked_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_calendar_export_revocations_revoked_by_user_id", table_name="calendar_export_revocations")
    op.drop_table("calendar_export_revocations")
    op.drop_index("ix_calendar_export_tokens_expires_at", table_name="calendar_export_tokens")
    op.drop_table("calendar_export_tokens")
    op.drop_index("ix_calendar_export_subscriptions_expires_at", table_name="calendar_export_subscriptions")
    op.drop_index("uq_calendar_export_one_active_pg", table_name="calendar_export_subscriptions")
    op.drop_index("ix_calendar_export_subscriptions_status", table_name="calendar_export_subscriptions")
    op.drop_index("ix_calendar_export_subscriptions_owner_user_id", table_name="calendar_export_subscriptions")
    op.drop_table("calendar_export_subscriptions")
    op.drop_index("ix_calendar_conflicts_right_event_owner", table_name="calendar_conflicts")
    op.drop_index("ix_calendar_conflicts_left_event_owner", table_name="calendar_conflicts")
    op.drop_index("ix_calendar_conflicts_right_event_id", table_name="calendar_conflicts")
    op.drop_index("ix_calendar_conflicts_left_event_id", table_name="calendar_conflicts")
    op.drop_index("ix_calendar_conflicts_owner_user_id", table_name="calendar_conflicts")
    op.drop_table("calendar_conflicts")
    op.drop_index("ix_calendar_reminder_preferences_owner_user_id", table_name="calendar_reminder_preferences")
    op.drop_table("calendar_reminder_preferences")
    op.drop_table("calendar_view_preferences")
    op.drop_index("ix_calendar_events_event_source_owner", table_name="calendar_events")
    op.drop_index("ix_calendar_events_status", table_name="calendar_events")
    op.drop_index("ix_calendar_events_ends_at", table_name="calendar_events")
    op.drop_index("ix_calendar_events_starts_at", table_name="calendar_events")
    op.drop_index("ix_calendar_events_owner_user_id", table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_index("ix_calendar_event_sources_source_type", table_name="calendar_event_sources")
    op.drop_index("ix_calendar_event_sources_owner_user_id", table_name="calendar_event_sources")
    op.drop_table("calendar_event_sources")
