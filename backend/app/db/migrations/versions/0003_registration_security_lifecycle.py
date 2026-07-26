"""Registration security and lifecycle completion.

Revision ID: 0003_registration_security
Revises: 0002_registration_schema

Keeps the committed 0002 revision immutable and advances the deployed schema
with crypto metadata, finite-domain constraints, purpose-separated OTP
challenges, opaque recovery sessions and an after-commit delivery receipt.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# Alembic's default ``alembic_version.version_num`` is VARCHAR(32). Keep the
# identifier below that hard database boundary (SQLite would not catch it).
revision: str = "0003_registration_security"
down_revision: Union[str, None] = "0002_registration_schema"
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
    with op.batch_alter_table("users") as batch:
        batch.create_check_constraint(
            "ck_users_role", "role IN ('student', 'lawyer', 'admin')"
        )
        batch.create_check_constraint(
            "ck_users_status", "status IN ('pending', 'active', 'suspended', 'deleted')"
        )

    with op.batch_alter_table("student_registrations") as batch:
        batch.add_column(
            sa.Column(
                "dob_hash",
                sa.String(64),
                nullable=False,
                server_default="[rehash-required]",
            )
        )
        batch.add_column(
            sa.Column("key_version", sa.String(8), nullable=False, server_default="v1")
        )
        batch.alter_column("mobile_ct", type_=sa.String(600), existing_type=sa.String(512))
        batch.alter_column("dob_ct", type_=sa.String(600), existing_type=sa.String(512))
        batch.create_check_constraint(
            "ck_student_registrations_status",
            "status IN ('otp_pending', 'otp_verified', 'active', 'suspended', 'deleted')",
        )
    op.create_index(
        "ix_student_registrations_dob_hash", "student_registrations", ["dob_hash"]
    )

    with op.batch_alter_table("student_profiles") as batch:
        batch.add_column(sa.Column("bar_enrolment_hash", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column("key_version", sa.String(8), nullable=False, server_default="v1")
        )
        batch.alter_column("enrolment_ct", type_=sa.String(600), existing_type=sa.String(512))
        batch.alter_column(
            "institutional_email_ct", type_=sa.String(600), existing_type=sa.String(512)
        )
        batch.alter_column(
            "bar_enrolment_ct", type_=sa.String(600), existing_type=sa.String(512)
        )
    op.create_index(
        "ix_student_profiles_bar_enrolment_hash",
        "student_profiles",
        ["bar_enrolment_hash"],
    )

    with op.batch_alter_table("otp_challenges") as batch:
        batch.add_column(
            sa.Column("purpose", sa.String(16), nullable=False, server_default="signup")
        )
        batch.create_check_constraint(
            "ck_otp_challenges_purpose", "purpose IN ('signup', 'recovery')"
        )
        batch.create_check_constraint(
            "ck_otp_challenges_attempts_nonneg", "attempts >= 0"
        )
        batch.create_check_constraint(
            "ck_otp_challenges_max_positive", "max_attempts > 0"
        )
        batch.create_check_constraint(
            "ck_otp_challenges_attempts_le_max", "attempts <= max_attempts"
        )

    op.create_table(
        "recovery_sessions",
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
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
        sa.UniqueConstraint("opaque_id", name="uq_recovery_sessions_opaque_id"),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'consumed', 'expired')",
            name="ck_recovery_sessions_status",
        ),
    )
    op.create_index(
        "ix_recovery_sessions_registration_id",
        "recovery_sessions",
        ["registration_id"],
    )
    op.create_index(
        "ix_recovery_sessions_lookup_hash",
        "recovery_sessions",
        ["lookup_hash"],
    )
    op.create_index(
        "ix_recovery_sessions_challenge_id",
        "recovery_sessions",
        ["challenge_id"],
    )

    op.create_table(
        "otp_outbox",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "challenge_id",
            _UUID,
            sa.ForeignKey("otp_challenges.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("destination_ct", sa.String(600), nullable=False),
        sa.Column("code_ct", sa.String(600), nullable=True),
        sa.Column("key_version", sa.String(8), nullable=False, server_default="v1"),
        sa.Column("purpose", sa.String(16), nullable=False, server_default="signup"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(200), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
        sa.UniqueConstraint("challenge_id", name="uq_otp_outbox_challenge_id"),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'void')",
            name="ck_otp_outbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_otp_outbox_attempts_nonneg"),
    )
    op.create_index("ix_otp_outbox_challenge_id", "otp_outbox", ["challenge_id"])

    with op.batch_alter_table("consents") as batch:
        batch.create_check_constraint("ck_consents_affirmative", "accepted = true")

    with op.batch_alter_table("student_verifications") as batch:
        batch.create_check_constraint(
            "ck_student_verifications_method",
            "method IN ('institutional_email', 'college_id', 'manual')",
        )
        batch.create_check_constraint(
            "ck_student_verifications_status",
            "status IN ('pending', 'in_review', 'verified', 'rejected')",
        )

    with op.batch_alter_table("guardian_consents") as batch:
        batch.create_check_constraint(
            "ck_guardian_consents_status",
            "status IN ('pending', 'sent', 'verified', 'rejected')",
        )

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION legalsaathi_audit_append_only()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_events rows are append-only (% blocked)', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION legalsaathi_audit_append_only();
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events rows are append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events rows are append-only');
            END
            """
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS legalsaathi_audit_append_only()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_delete")

    with op.batch_alter_table("guardian_consents") as batch:
        batch.drop_constraint("ck_guardian_consents_status", type_="check")
    with op.batch_alter_table("student_verifications") as batch:
        batch.drop_constraint("ck_student_verifications_status", type_="check")
        batch.drop_constraint("ck_student_verifications_method", type_="check")
    with op.batch_alter_table("consents") as batch:
        batch.drop_constraint("ck_consents_affirmative", type_="check")

    op.drop_table("otp_outbox")
    op.drop_table("recovery_sessions")

    with op.batch_alter_table("otp_challenges") as batch:
        batch.drop_constraint("ck_otp_challenges_attempts_le_max", type_="check")
        batch.drop_constraint("ck_otp_challenges_max_positive", type_="check")
        batch.drop_constraint("ck_otp_challenges_attempts_nonneg", type_="check")
        batch.drop_constraint("ck_otp_challenges_purpose", type_="check")
        batch.drop_column("purpose")

    op.drop_index(
        "ix_student_profiles_bar_enrolment_hash", table_name="student_profiles"
    )
    with op.batch_alter_table("student_profiles") as batch:
        batch.alter_column("bar_enrolment_ct", type_=sa.String(512), existing_type=sa.String(600))
        batch.alter_column(
            "institutional_email_ct", type_=sa.String(512), existing_type=sa.String(600)
        )
        batch.alter_column("enrolment_ct", type_=sa.String(512), existing_type=sa.String(600))
        batch.drop_column("key_version")
        batch.drop_column("bar_enrolment_hash")

    op.drop_index("ix_student_registrations_dob_hash", table_name="student_registrations")
    with op.batch_alter_table("student_registrations") as batch:
        batch.drop_constraint("ck_student_registrations_status", type_="check")
        batch.alter_column("dob_ct", type_=sa.String(512), existing_type=sa.String(600))
        batch.alter_column("mobile_ct", type_=sa.String(512), existing_type=sa.String(600))
        batch.drop_column("key_version")
        batch.drop_column("dob_hash")

    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_status", type_="check")
        batch.drop_constraint("ck_users_role", type_="check")
