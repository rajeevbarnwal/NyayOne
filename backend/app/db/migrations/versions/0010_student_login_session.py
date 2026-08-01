"""Server-authoritative student OTP login and hashed auth sessions.

Revision ID: 0010_student_login_session
Revises: 0009_wave2_session_pricing
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_student_login_session"
down_revision: Union[str, None] = "0009_wave2_session_pricing"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)


def _ts_cols() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    ]


def upgrade() -> None:
    # A login OTP cannot supersede signup or recovery, and neither may be
    # accepted for login. Keep the purpose boundary database-enforced.
    with op.batch_alter_table("otp_challenges") as batch:
        batch.drop_constraint("ck_otp_challenges_purpose", type_="check")
        batch.create_check_constraint(
            "ck_otp_challenges_purpose",
            "purpose IN ('signup', 'recovery', 'login')",
        )

    op.create_table(
        "login_attempts",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("opaque_id", sa.String(64), nullable=False),
        sa.Column("lookup_hash", sa.String(64), nullable=False),
        sa.Column(
            "registration_id",
            _UUID,
            sa.ForeignKey("student_registrations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "challenge_id",
            _UUID,
            sa.ForeignKey("otp_challenges.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
        sa.UniqueConstraint("opaque_id", name="uq_login_attempts_opaque_id"),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed', 'expired')",
            name="ck_login_attempts_status",
        ),
    )
    op.create_index("ix_login_attempts_lookup_hash", "login_attempts", ["lookup_hash"])
    op.create_index("ix_login_attempts_registration_id", "login_attempts", ["registration_id"])
    op.create_index("ix_login_attempts_challenge_id", "login_attempts", ["challenge_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_auth_sessions_status",
        ),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_sessions")
    op.drop_table("login_attempts")
    with op.batch_alter_table("otp_challenges") as batch:
        batch.drop_constraint("ck_otp_challenges_purpose", type_="check")
        batch.create_check_constraint(
            "ck_otp_challenges_purpose",
            "purpose IN ('signup', 'recovery')",
        )
