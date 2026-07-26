"""Registration/auth/profile schema (SAATHI-366/448).

Explicit, IMMUTABLE Alembic operations for the Product-approved (2026-07-26)
tables. Deliberately does NOT call metadata.create_all — a historical revision
must not change when future ORM models change (independent-QA finding A1).
UUID PKs, timezone-aware timestamps, indexed FKs, explicit ON DELETE, unique
lookup hashes.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_registration_schema"
down_revision: Union[str, None] = "0001_initial_pgvector"
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
    op.create_table(
        "users",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="student"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        *_ts_cols(),
    )

    op.create_table(
        "student_registrations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.String(60), nullable=False),
        sa.Column("middle_name", sa.String(60), nullable=True),
        sa.Column("last_name", sa.String(60), nullable=False),
        sa.Column("mobile_hash", sa.String(64), nullable=False),
        sa.Column("mobile_ct", sa.String(512), nullable=False),
        sa.Column("dob_ct", sa.String(512), nullable=False),
        sa.Column("institution_ref", sa.String(120), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="otp_pending"),
        sa.Column("is_minor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        *_ts_cols(),
        sa.UniqueConstraint("mobile_hash", name="uq_student_registrations_mobile_hash"),
        sa.UniqueConstraint("idempotency_key", name="uq_student_registrations_idempotency_key"),
    )
    op.create_index("ix_student_registrations_user_id", "student_registrations", ["user_id"])
    op.create_index("ix_student_registrations_mobile_hash", "student_registrations", ["mobile_hash"])

    op.create_table(
        "student_profiles",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("registration_id", _UUID, sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("college", sa.String(160), nullable=True),
        sa.Column("year_of_study", sa.String(40), nullable=True),
        sa.Column("enrolment_ct", sa.String(512), nullable=True),
        sa.Column("enrolment_hash", sa.String(64), nullable=True),
        sa.Column("institutional_email_ct", sa.String(512), nullable=True),
        sa.Column("institutional_email_hash", sa.String(64), nullable=True),
        sa.Column("bar_enrolment_ct", sa.String(512), nullable=True),
        *_ts_cols(),
        sa.UniqueConstraint("registration_id", name="uq_student_profiles_registration_id"),
    )
    op.create_index("ix_student_profiles_registration_id", "student_profiles", ["registration_id"])
    op.create_index("ix_student_profiles_enrolment_hash", "student_profiles", ["enrolment_hash"])
    op.create_index("ix_student_profiles_institutional_email_hash", "student_profiles", ["institutional_email_hash"])

    op.create_table(
        "otp_challenges",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("registration_id", _UUID, sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("verifier_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
    )
    op.create_index("ix_otp_challenges_registration_id", "otp_challenges", ["registration_id"])

    op.create_table(
        "consents",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("registration_id", _UUID, sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False, server_default="registration"),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
    )
    op.create_index("ix_consents_registration_id", "consents", ["registration_id"])

    op.create_table(
        "student_verifications",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("registration_id", _UUID, sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(32), nullable=False, server_default="institutional_email"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        *_ts_cols(),
    )
    op.create_index("ix_student_verifications_registration_id", "student_verifications", ["registration_id"])

    op.create_table(
        "guardian_consents",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("registration_id", _UUID, sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts_cols(),
    )
    op.create_index("ix_guardian_consents_registration_id", "guardian_consents", ["registration_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("actor_user_id", _UUID, nullable=True),
        sa.Column("actor_role", sa.String(40), nullable=True),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", _UUID, nullable=True),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("user_agent_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_events_resource_id", "audit_events", ["resource_id"])


def downgrade() -> None:
    for name in [
        "audit_events",
        "guardian_consents",
        "student_verifications",
        "consents",
        "otp_challenges",
        "student_profiles",
        "student_registrations",
        "users",
    ]:
        op.drop_table(name)
