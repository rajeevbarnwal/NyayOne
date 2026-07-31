"""Wave 3 credential-trust schema (SAATHI-253 / SAATHI-258).

Evidence bytes remain in object storage. PostgreSQL stores opaque object
references, integrity/scan metadata and keyed token hashes only.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_wave3_credentials"
down_revision: Union[str, None] = "0006_lawschool_fact_backfill"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)


def _ts() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    ]


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "credential_issuers",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("issuer_type", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "display_name", name="uq_credential_issuers_display_name"
        ),
        sa.CheckConstraint(
            _in(
                "issuer_type",
                ("institution", "platform", "tutor", "employer", "external"),
            ),
            name="issuer_type",
        ),
    )

    op.create_table(
        "credentials",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "owner_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "issuer_id",
            _UUID,
            sa.ForeignKey("credential_issuers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("credential_type", sa.String(40), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            server_default="self_declared",
            nullable=False,
        ),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("identifier_hash", sa.String(64), nullable=True),
        sa.Column("identifier_ct", sa.String(600), nullable=True),
        sa.Column("key_version", sa.String(16), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_credentials_owner_idempotency",
        ),
        sa.UniqueConstraint(
            "owner_user_id",
            "identifier_hash",
            name="uq_credentials_owner_identifier_hash",
        ),
        sa.CheckConstraint(
            _in(
                "credential_type",
                (
                    "certificate",
                    "badge",
                    "moot_achievement",
                    "course_completion",
                    "employment",
                    "other",
                ),
            ),
            name="credential_type",
        ),
        sa.CheckConstraint(
            _in(
                "status",
                (
                    "self_declared",
                    "pending_verification",
                    "verified",
                    "expired",
                    "revoked",
                ),
            ),
            name="status",
        ),
        sa.CheckConstraint(
            "expiry_date IS NULL OR expiry_date >= issue_date",
            name="expiry_after_issue",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index("ix_credentials_owner_user_id", "credentials", ["owner_user_id"])
    op.create_index("ix_credentials_issuer_id", "credentials", ["issuer_id"])
    op.create_index(
        "ix_credentials_identifier_hash", "credentials", ["identifier_hash"]
    )

    op.create_table(
        "credential_evidence",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "credential_id",
            _UUID,
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_ref", sa.String(240), nullable=False),
        sa.Column("sha256_digest", sa.String(64), nullable=False),
        sa.Column("declared_mime", sa.String(80), nullable=False),
        sa.Column("detected_mime", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "scan_state",
            sa.String(32),
            server_default="quarantined",
            nullable=False,
        ),
        *_ts(),
        sa.UniqueConstraint(
            "credential_id",
            "sha256_digest",
            name="uq_credential_evidence_digest",
        ),
        sa.UniqueConstraint(
            "object_ref", name="uq_credential_evidence_object_ref"
        ),
        sa.CheckConstraint(
            _in(
                "scan_state",
                (
                    "quarantined",
                    "clean",
                    "infected",
                    "retryable_failure",
                    "deleted",
                ),
            ),
            name="scan_state",
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name="size_positive"
        ),
    )
    op.create_index(
        "ix_credential_evidence_credential_id",
        "credential_evidence",
        ["credential_id"],
    )

    op.create_table(
        "credential_status_history",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "credential_id",
            _UUID,
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        *_ts(),
        sa.CheckConstraint(
            _in(
                "to_status",
                (
                    "self_declared",
                    "pending_verification",
                    "verified",
                    "expired",
                    "revoked",
                ),
            ),
            name="to_status",
        ),
    )
    op.create_index(
        "ix_credential_status_history_credential_id",
        "credential_status_history",
        ["credential_id"],
    )
    op.create_index(
        "ix_credential_status_history_actor_user_id",
        "credential_status_history",
        ["actor_user_id"],
    )

    op.create_table(
        "credential_share_projections",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "credential_id",
            _UUID,
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fields_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_credential_share_projections_owner_idempotency",
        ),
        sa.CheckConstraint(
            "version >= 1", name="version_positive"
        ),
    )
    op.create_index(
        "ix_credential_share_projections_credential_id",
        "credential_share_projections",
        ["credential_id"],
    )
    op.create_index(
        "ix_credential_share_projections_owner_user_id",
        "credential_share_projections",
        ["owner_user_id"],
    )

    op.create_table(
        "credential_outbox",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "credential_id",
            _UUID,
            sa.ForeignKey("credentials.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "evidence_id",
            _UUID,
            sa.ForeignKey("credential_evidence.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "status", sa.String(16), server_default="pending", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "kind",
            "idempotency_key",
            name="uq_credential_outbox_kind_idempotency",
        ),
        sa.CheckConstraint(
            _in("kind", ("scan_evidence", "delete_evidence", "expiry_reminder")),
            name="kind",
        ),
        sa.CheckConstraint(
            _in("status", ("pending", "processing", "complete", "failed")),
            name="status",
        ),
        sa.CheckConstraint(
            "attempts >= 0", name="attempts_nonnegative"
        ),
    )
    op.create_index(
        "ix_credential_outbox_credential_id",
        "credential_outbox",
        ["credential_id"],
    )
    op.create_index(
        "ix_credential_outbox_evidence_id",
        "credential_outbox",
        ["evidence_id"],
    )

    op.create_table(
        "credential_reminder_jobs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "credential_id",
            _UUID,
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("days_before", sa.Integer(), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(16), server_default="pending", nullable=False
        ),
        *_ts(),
        sa.UniqueConstraint(
            "credential_id",
            "days_before",
            name="uq_credential_reminder_jobs_credential_day",
        ),
        sa.CheckConstraint(
            _in("status", ("pending", "sent", "cancelled", "failed")),
            name="status",
        ),
        sa.CheckConstraint(
            "days_before IN (30, 7, 1)",
            name="days_before",
        ),
    )
    op.create_index(
        "ix_credential_reminder_jobs_credential_id",
        "credential_reminder_jobs",
        ["credential_id"],
    )

    op.create_table(
        "credential_evidence_scan_events",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "evidence_id",
            _UUID,
            sa.ForeignKey("credential_evidence.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scan_state", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("result_code", sa.String(80), nullable=False),
        *_ts(),
        sa.CheckConstraint(
            _in(
                "scan_state",
                (
                    "quarantined",
                    "clean",
                    "infected",
                    "retryable_failure",
                    "deleted",
                ),
            ),
            name="scan_state",
        ),
    )
    op.create_index(
        "ix_credential_evidence_scan_events_evidence_id",
        "credential_evidence_scan_events",
        ["evidence_id"],
    )

    op.create_table(
        "issuer_authorisations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "issuer_id",
            _UUID,
            sa.ForeignKey("credential_issuers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("can_verify", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("can_revoke", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "granted_by_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_ts(),
        sa.UniqueConstraint(
            "issuer_id",
            "user_id",
            name="uq_issuer_authorisations_issuer_user",
        ),
    )
    op.create_index(
        "ix_issuer_authorisations_issuer_id",
        "issuer_authorisations",
        ["issuer_id"],
    )
    op.create_index(
        "ix_issuer_authorisations_user_id",
        "issuer_authorisations",
        ["user_id"],
    )
    op.create_index(
        "ix_issuer_authorisations_granted_by_user_id",
        "issuer_authorisations",
        ["granted_by_user_id"],
    )

    op.create_table(
        "credential_verification_events",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "credential_id",
            _UUID,
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "issuer_id",
            _UUID,
            sa.ForeignKey("credential_issuers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("resulting_status", sa.String(32), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "actor_user_id",
            "idempotency_key",
            name="uq_credential_verification_events_actor_idempotency",
        ),
        sa.CheckConstraint(
            _in("action", ("verified", "revoked")),
            name="action",
        ),
        sa.CheckConstraint(
            _in(
                "resulting_status",
                (
                    "self_declared",
                    "pending_verification",
                    "verified",
                    "expired",
                    "revoked",
                ),
            ),
            name="resulting_status",
        ),
    )
    op.create_index(
        "ix_credential_verification_events_credential_id",
        "credential_verification_events",
        ["credential_id"],
    )
    op.create_index(
        "ix_credential_verification_events_issuer_id",
        "credential_verification_events",
        ["issuer_id"],
    )
    op.create_index(
        "ix_credential_verification_events_actor_user_id",
        "credential_verification_events",
        ["actor_user_id"],
    )

    op.create_table(
        "verification_tokens",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "projection_id",
            _UUID,
            sa.ForeignKey("credential_share_projections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "credential_id",
            _UUID,
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("key_version", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "token_hash", name="uq_verification_tokens_token_hash"
        ),
        sa.UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_verification_tokens_owner_idempotency",
        ),
    )
    op.create_index(
        "ix_verification_tokens_projection_id",
        "verification_tokens",
        ["projection_id"],
    )
    op.create_index(
        "ix_verification_tokens_credential_id",
        "verification_tokens",
        ["credential_id"],
    )
    op.create_index(
        "ix_verification_tokens_owner_user_id",
        "verification_tokens",
        ["owner_user_id"],
    )

    op.create_table(
        "credential_revocations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "credential_id",
            _UUID,
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "issuer_id",
            _UUID,
            sa.ForeignKey("credential_issuers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason_ct", sa.Text(), nullable=False),
        sa.Column("reason_hash", sa.String(64), nullable=False),
        sa.Column("key_version", sa.String(16), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "credential_id", name="uq_credential_revocations_credential_id"
        ),
    )
    op.create_index(
        "ix_credential_revocations_credential_id",
        "credential_revocations",
        ["credential_id"],
    )
    op.create_index(
        "ix_credential_revocations_issuer_id",
        "credential_revocations",
        ["issuer_id"],
    )
    op.create_index(
        "ix_credential_revocations_actor_user_id",
        "credential_revocations",
        ["actor_user_id"],
    )

    op.create_table(
        "verification_access_logs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "token_id",
            _UUID,
            sa.ForeignKey("verification_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("bucket_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        *_ts(),
        sa.CheckConstraint(
            _in(
                "outcome",
                ("valid", "invalid", "expired", "revoked", "rate_limited"),
            ),
            name="outcome",
        ),
    )
    op.create_index(
        "ix_verification_access_logs_token_id",
        "verification_access_logs",
        ["token_id"],
    )
    op.create_index(
        "ix_verification_access_logs_bucket_hash",
        "verification_access_logs",
        ["bucket_hash"],
    )


def downgrade() -> None:
    for table_name in (
        "verification_access_logs",
        "credential_revocations",
        "verification_tokens",
        "credential_verification_events",
        "issuer_authorisations",
        "credential_evidence_scan_events",
        "credential_reminder_jobs",
        "credential_outbox",
        "credential_share_projections",
        "credential_status_history",
        "credential_evidence",
        "credentials",
        "credential_issuers",
    ):
        op.drop_table(table_name)
